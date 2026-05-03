# CASCADE-RC Orchestrator Design

**Date:** 2026-05-04  
**Status:** Approved  
**File to create:** `run_orchestrator.py` (repo root)

---

## Goal

Replace manual CLI sequencing with a single, resumable Python script that drives the full CASCADE-RC evaluation pipeline end-to-end for one topic at a time.

**Hard constraint:** Do NOT modify any existing mathematical, calibration, or baseline modules. The orchestrator is pure glue.

---

## Architecture

### Class: `CascadeOrchestrator`

Instantiated from CLI args. Owns all path resolution and calls each phase as a method. Phases are idempotent via file-existence checkpoints — re-running the orchestrator on a partially-completed topic skips already-completed phases.

```
CascadeOrchestrator
├── __init__(topic, artefact_dir, data_dir, out_dir, db_path, model_id, template_v)
├── run()                          # top-level; calls phases 1–6 in order
├── _run(cmd, label, env=None)     # subprocess helper
├── _skip_if_exists(path, label)   # returns True + logs if checkpoint exists
│
├── phase1_independent_baselines() # AUTOSTOP + RLStop (sequential)
├── phase2_merge_llm_u()           # SQLite → step2/{topic}.parquet (in-process)
├── phase3_scrc()                  # SCRC-I and SCRC-T
├── phase4_calibration()           # LTT calibration; halts pipeline on abstention
├── phase5_metrics()               # capture JSON stdout → cascade_rc_results.parquet
└── phase6_figures()               # figures with PYTHONHASHSEED=0
```

---

## CLI

```
python run_orchestrator.py \
    --topic        CD008874          \   # required
    --artefact-dir artefacts/cascade_rc  \   # optional
    --data-dir     artefacts/cascade_rc/data  \   # optional
    --out-dir      artefacts/cascade_rc/baselines  \   # optional
    --db-path      artefacts/cascade_rc/llm_cache.db  \   # optional
    --model-id     gpt-oss:120b      \   # optional, for SQLite filter
    --template-v   v1                    # optional, for SQLite filter
```

All path arguments default to the values shown. `--data-dir` defaults to `{artefact-dir}/data`; `--out-dir` defaults to `{artefact-dir}/baselines`; `--db-path` defaults to `{artefact-dir}/llm_cache.db`.

---

## Logging

```python
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
)
```

No raw `print()` calls anywhere in the orchestrator. Subprocess stdout/stderr is captured and re-emitted line-by-line at DEBUG level. Phase entry/exit and skip decisions are logged at INFO.

---

## Core Helpers

### `_run(cmd, label, env=None)`

```
1. Log INFO: "→ {label}"
2. subprocess.run(cmd, env=env, text=True, capture_output=True)
3. Emit stdout lines at DEBUG, stderr lines at WARNING
4. If returncode != 0: raise RuntimeError(f"{label} failed (exit {returncode})")
5. Log INFO: "✓ {label} complete"
```

Uses `sys.executable` for all Python module invocations to ensure the same interpreter/venv.

### `_skip_if_exists(path, label) -> bool`

```
if path.exists():
    log INFO: "SKIP {label} — checkpoint exists: {path}"
    return True
return False
```

---

## Phase Specifications

### Phase 1a — AUTOSTOP

**Checkpoint:** `{out_dir}/autostop/autostop_results.parquet`

```
_run([sys.executable, "-m", "cascade_rc.baselines.run_autostop",
      "--data-dir", str(data_dir),
      "--out-dir",  str(out_dir / "autostop"),
      "--topics",   topic],
     label="Phase 1a: AUTOSTOP")
```

### Phase 1b — RLStop

**Checkpoint:** `{out_dir}/rlstop/rlstop_results.parquet`

```
_run([sys.executable, "-m", "cascade_rc.baselines.run_rlstop",
      "--data-dir",  str(data_dir),
      "--out-dir",   str(out_dir / "rlstop"),
      "--train-dir", str(out_dir / "rlstop"),
      "--topics",    topic],
     label="Phase 1b: RLStop")
```

### Phase 2 — Merge LLM Ensemble → step2 parquet

**Checkpoint:** `{data_dir}/step2/{topic}.parquet`

Runs entirely in-process. Does NOT load the original parquet into memory to check columns; uses file existence only.

#### Step2 Parquet Schema Contract

`{data_dir}/step2/{topic}.parquet` must contain **all** of the following columns before Phase 3 or 4 may run. This contract is enforced by a post-write assertion inside Phase 2 (see step 7 below).

| Column | Type | Source | Consumer |
|---|---|---|---|
| `pmid` | str | original parquet | all phases |
| `title` | str | original parquet | — |
| `abstract` | str | original parquet | — |
| `y_abstract` | int8 | original parquet | SCRC, calibration, metrics |
| `is_calib` | int8 | original parquet | SCRC, calibration, metrics |
| `s` | float64 | original parquet (update_parquet.py) | SCRC, calibration |
| `u` | float64 | **Phase 2** (LLM self-consistency score) | SCRC, calibration |
| `llm_y_hat` | int8 | **Phase 2** (LLM majority vote) | calibration |

`s` and `u` in `step2/{topic}.parquet` have different semantics from the original: `u` is now the LLM ensemble self-consistency score (∈ [0, 1]), overwriting the ranker-score placeholder written by `update_parquet.py`.

**Algorithm:**

```
1. df = pd.read_parquet(data_dir / f"{topic}.parquet")
   # Expected columns: pmid, title, abstract, y_abstract, is_calib, s, u

2. conn = sqlite3.connect(db_path)
   rows = conn.execute(
       "SELECT pmid, vote_label FROM llm_calls
        WHERE model_id=? AND template_v=?
        ORDER BY pmid, seed_b",
       (model_id, template_v)
   ).fetchall()
   conn.close()

3. Group rows by pmid → votes_by_pmid: dict[str, list[str]]

4. For each pmid in df["pmid"]:
       votes = votes_by_pmid.get(pmid, [])
       if not votes:
           log WARNING: "PMID {pmid} has no LLM cache entries — using u=0.0, llm_y_hat=0"
           u_val, y_hat_val = 0.0, 0
       else:
           _, u_val, y_hat_val = _majority_and_u(votes, n=len(votes))

5. df["u"]          = [computed u_vals]       # float64, overwrites ranker u
   df["llm_y_hat"]  = [computed y_hat_vals]   # int8

6. (data_dir / "step2").mkdir(parents=True, exist_ok=True)
   df.to_parquet(data_dir / "step2" / f"{topic}.parquet", index=False)

7. POST-WRITE ASSERTION (guards Phase 3 and 4):
   _STEP2_REQUIRED = {"pmid","title","abstract","y_abstract","is_calib","s","u","llm_y_hat"}
   written = pd.read_parquet(data_dir / "step2" / f"{topic}.parquet").columns
   missing = _STEP2_REQUIRED - set(written)
   if missing:
       raise RuntimeError(
           f"Phase 2 schema assertion failed for {topic}: missing columns {sorted(missing)}"
       )
   log INFO: "Phase 2 schema OK — {len(written)} columns present in step2/{topic}.parquet"
```

`_majority_and_u` is imported directly from `cascade_rc.cache.llm_ensemble` — no reimplementation.

### Phase 3 — SCRC

**Checkpoint:** `{out_dir}/scrc/scrc_results.parquet`

Reads from `{data_dir}/step2/` so SCRC finds `{topic}.parquet` under its expected naming convention.

```
_run([sys.executable, "-m", "cascade_rc.baselines.scrc",
      "--data-dir", str(data_dir / "step2"),
      "--out-dir",  str(out_dir / "scrc"),
      "--topics",   topic],
     label="Phase 3: SCRC")
```

### Phase 4 — LTT Calibration

**Checkpoint (presence = certified):** `{artefact_dir}/certificates/{topic}.json`

```
_run([sys.executable, "-m", "cascade_rc.calibration.main_calibrate",
      "--topic",         topic,
      "--calib-parquet", str(data_dir / "step2" / f"{topic}.parquet"),
      "--artefact-dir",  str(artefact_dir)],
     label="Phase 4: Calibration")

cert_path = artefact_dir / "certificates" / f"{topic}.json"
if not cert_path.exists():
    log WARNING: "Calibration abstained for topic {topic} "
                 "(certificate not written). Pipeline halting gracefully."
    return   # clean exit, no exception
```

### Phase 5 — Metrics

**Checkpoint:** `{out_dir}/cascade_rc_results.parquet`

```
result = subprocess.run(
    [sys.executable, "-m", "cascade_rc.evaluation.metrics",
     "--topic",        topic,
     "--artefact-dir", str(artefact_dir)],
    capture_output=True, text=True, check=True
)

payload  = json.loads(result.stdout)
wss95    = payload["wss95"]
fnr      = 1.0 - wss95["achieved_recall"]   # None-safe: keep None if achieved_recall is None

row = {
    "topic":  payload["topic"],
    "wss":    wss95["wss"],
    "fnr":    fnr,
}
pd.DataFrame([row]).to_parquet(out_dir / "cascade_rc_results.parquet", index=False)
```

`achieved_recall` can be `None` (serialised as JSON `null`) when the metric is undefined. `fnr` is set to `None` rather than crashing.

### Phase 6 — Figures

**Checkpoint:** `{artefact_dir}/figures/figure1.pdf`

```
env = {**os.environ, "PYTHONHASHSEED": "0"}
_run([sys.executable, "-m", "cascade_rc.evaluation.figures",
      "--artefact-dir", str(artefact_dir)],
     env=env,
     label="Phase 6: Figures")
```

---

## Error Handling

```python
def run(self):
    try:
        self.phase1_independent_baselines()
        self.phase2_merge_llm_u()
        self.phase3_scrc()
        halted = self.phase4_calibration()
        if halted:
            return
        self.phase5_metrics()
        self.phase6_figures()
    except RuntimeError as exc:
        log ERROR: str(exc)
        sys.exit(1)
    except Exception as exc:
        log ERROR with traceback
        sys.exit(1)
    log INFO: "Pipeline complete for topic {topic}"
```

Phase 4 returns `True` if calibration abstained (halting the pipeline cleanly). All other phases raise `RuntimeError` on failure, which propagates to `run()` and exits with code 1.

---

## File Layout After Full Run

```
artefacts/cascade_rc/
├── data/
│   ├── CD008874.parquet          # original (s, u=ranker-score)
│   └── step2/
│       └── CD008874.parquet      # hydrated (u=LLM-score, llm_y_hat added)
├── baselines/
│   ├── autostop/autostop_results.parquet
│   ├── rlstop/rlstop_results.parquet
│   ├── scrc/scrc_results.parquet
│   └── cascade_rc_results.parquet
├── certificates/
│   └── CD008874.json
├── routing/
│   └── CD008874.parquet
└── figures/
    ├── figure1.pdf / figure1.png
    ├── figure2.pdf / figure2.png
    └── figure3.pdf / figure3.png
```

---

## What This Design Does NOT Do

- Does not run the LLM ensemble itself (assumes `llm_cache.db` is pre-populated)
- Does not run `update_parquet.py` (assumes `s` is already present in `{topic}.parquet`)
- Does not support multi-topic batching in a single invocation (one topic per run)
- Does not modify any existing module
