# Design: Prompts 11.1 & 11.2 — AUTOSTOP and RLStop Baselines

**Date:** 2026-05-02
**Branch:** feature_redesignv2
**Files to create:**
- `cascade_rc/baselines/autostop_vendor/` (vendored from dli1/auto-stop-tar, MIT)
- `cascade_rc/baselines/run_autostop.py`
- `cascade_rc/baselines/rlstop_vendor/` (vendored from ReemBinHezam/RLStop, Apache-2.0)
- `cascade_rc/baselines/run_rlstop.py`

---

## 1. Shared Conventions

### Input: per-topic enriched parquet

Both drivers read from the canonical source of truth:

```
artefacts/cascade_rc/data/<topic_id>.parquet
```

Required columns: `pmid` (str), `title` (str), `abstract` (str), `y_abstract` (int 0/1).

Topics in scope: 6 CLEF-TAR 2019 Task 2 test topics:
- **DTA:** CD008874, CD012080, CD012768
- **Intervention:** CD011768, CD011975, CD011145

### Output schema (shared, concat-compatible)

Both parquets use identical column names and dtypes so Phase 12 figures can union them with `pd.concat`:

| column | dtype | notes |
|---|---|---|
| `method` | object | `"autostop"` or `"rlstop"` |
| `topic_id` | object | matches Phase 9/10 ablation convention |
| `target_recall` | float64 | recall the system aimed for |
| `examined` | int64 | documents examined before stopping |
| `recall_achieved` | float64 | true recall at stopping point |
| `wss_95` | float64 | WSS@95 via `cascade_rc.evaluation.metrics.wss_at_recall()` |
| `wss_status` | object | `"ok"` or `"recall_target_missed"` |
| `peak_rss_kb` | int64 | `resource.getrusage(RUSAGE_SELF).ru_maxrss` after each run |

**Target recall sweep:** `{0.80, 0.90, 0.95, 1.0}` × 6 topics = **24 rows per parquet**.

### WSS computation

Always use `cascade_rc.evaluation.metrics.wss_at_recall()` with `target_recall=0.95`:

```python
predictions = np.isin(all_pmids, examined_pmids).astype(int)
wss_result = wss_at_recall(predictions, y_true, target_recall=0.95)
# wss_result["wss"]             → wss_95 column
# wss_result["status"]          → wss_status column
# wss_result["achieved_recall"] → recall_achieved column
```

This ensures consistency with Phase 9/10 WSS values and captures `recall_target_missed` failure semantics.

---

## 2. AUTOSTOP (Prompt 11.1)

### Vendor layout

```
cascade_rc/baselines/autostop_vendor/
├── VENDORED_FROM
└── autostop/
    ├── __init__.py
    ├── main.py
    ├── tar_framework/
    │   ├── __init__.py
    │   ├── assessing.py
    │   ├── ranking.py
    │   ├── sampling_estimating.py
    │   └── utils.py
    └── tar_model/
        ├── __init__.py
        ├── auto_stop.py      ← entry point
        ├── autotar.py
        ├── knee.py
        ├── scal.py
        ├── score_distribution.py
        ├── target.py
        └── utils.py
```

Files copied verbatim from commit `7e72795` of `github.com/dli1/auto-stop-tar`.

**`VENDORED_FROM`:**
```
Source:   https://github.com/dli1/auto-stop-tar
Commit:   7e72795
License:  MIT
Vendored: 2026-05-02
Cite:     Li & Kanoulas, "When to Stop Reviewing in Technology-Assisted Reviews",
          ACM TOIS 38(4):1–36, 2020. https://doi.org/10.1145/3411755
```

### Entry point: `autostop_method()`

Located in `autostop.tar_model.auto_stop`. Signature:

```python
autostop_method(
    data_name, topic_set, topic_id,
    query_file, qrel_file, doc_id_file, doc_text_file,
    sampler_type='HTAPPriorSampler',
    stopping_recall=<target_recall>,
    target_recall=1.0,
    stopping_condition='loose',
    random_state=0,
)
```

**Returns `None`.** All results are written to files under `autostop.tar_framework.utils.RET_DIR`.

### Temp-file formats (verified against `Assessor.read_*` methods)

| file | format |
|---|---|
| `query.json` | `{"title": "<topic title>"}` — only `title` is read |
| `qrels.txt` | TREC: `<topic_id> 0 <pmid> <0|1>` per line |
| `docids.txt` | one PMID per line |
| `docs.jsonl` | `{"id": "<pmid>", "title": "<title>", "content": "<abstract>"}` per line |

### `RET_DIR` patching

`autostop.tar_framework.utils.RET_DIR` is a module-level constant pointing to `autostop_vendor/ret/`. The driver patches it to a `tempfile.TemporaryDirectory` before calling and restores it in a `finally` block:

```python
import autostop.tar_framework.utils as _as_utils

with tempfile.TemporaryDirectory() as tmpdir:
    _as_utils.RET_DIR = tmpdir
    try:
        autostop_method(data_name="crc", topic_set="test", topic_id=topic_id, ...)
    finally:
        _as_utils.RET_DIR = _ORIGINAL_RET_DIR
    
    # Parse interaction CSV for examined count
    csv_path = next(Path(tmpdir).rglob(f"{topic_id}.csv"))
    interaction = pd.read_csv(csv_path, header=None)
    # Columns: t, batch_size, total_num, sampled_num, total_true_r, total_esti_r,
    #          var1, var2, running_true_r, ap, running_esti_recall, running_true_recall
    examined = int(interaction.iloc[-1][3])   # sampled_num at stopping
    
    # Parse TAR run file for examined PMIDs (for WSS prediction vector)
    run_path = next(Path(tmpdir).rglob(f"{topic_id}.run"))
    examined_pmids = {line.split()[2] for line in run_path.read_text().splitlines() if line.strip()}
```

### Driver: `run_autostop.py`

```
python -m cascade_rc.baselines.run_autostop \
  --data-dir artefacts/cascade_rc/data \
  --out-dir  artefacts/baselines/autostop \
  [--topics CD008874 CD012080 CD012768] \
  [--recalls 0.80 0.90 0.95 1.0]
```

Output: `artefacts/baselines/autostop/autostop_results.parquet` (24 rows).

---

## 3. RLStop (Prompt 11.2)

### Vendor layout

```
cascade_rc/baselines/rlstop_vendor/
├── VENDORED_FROM
├── rl_utils/
│   ├── __init__.py           (added — empty)
│   ├── rlstop_tar_env.py     (verbatim)
│   └── ranking_utils.py      (verbatim)
└── data/
    ├── rankings/topics/      (42 CLEF-2017 topic ranking files — training corpus)
    └── qrels/
        └── CLEF2017_qrels.txt
```

Files copied verbatim from commit `a59b622` of `github.com/ReemBinHezam/RLStop`.

**`VENDORED_FROM`:**
```
Source:   https://github.com/ReemBinHezam/RLStop
Commit:   a59b622
License:  Apache-2.0
Vendored: 2026-05-02
Cite:     Bin-Hezam & Stevenson, "RLStop: A Reinforcement Learning Stopping Method for TAR",
          SIGIR 2024. https://doi.org/10.1145/3626772.3657837

Deviations from paper:
  - Training data: CLEF 2017 only (42 Intervention topics). CLEF 2018 not shipped
    with the vendor repo. One model per target_recall is trained and applied
    cross-family. Per-family training protocol (paper §4) cannot be replicated
    without CLEF 2018 family labels.
  - n_steps=100 per vendor notebook (paper §4 states batch=100; vendor confirms).
```

### Global-injection pattern

`TAREnv` reads six module-level globals. The driver injects them serially before every env instantiation:

```python
import cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env as _env_mod

_env_mod.doc_rank_dic = {topic_id: [pmid1, pmid2, ...]}  # sorted by s desc
_env_mod.rank_rel_dic = {topic_id: [y1, y2, ...]}        # y_abstract in rank order
_env_mod.SELECTED_TOPICS = []
_env_mod.TRAINING = True
_env_mod.SELECTED_TOPICS_ORDERERD = [topic_id]
_env_mod.SELECTED_TOPICS_ORDERERD_INDEX = 0
```

**`n_jobs=1` enforced throughout** — global mutation is not thread-safe. Documented in driver docstring. The 24-inference run takes minutes serially; no parallelism needed.

### 4 models, one per target recall

```
artefacts/baselines/rlstop/
├── README.md
├── recall_0.80.zip
├── recall_0.90.zip
├── recall_0.95.zip
└── recall_1.00.zip
```

`README.md` contents:
```
Naming:     recall_<target_recall>.zip  (SB3 PPO format)
Trained on: CLEF 2017 (42 Intervention topics, vendor-provided rankings)
PPO steps:  100 000
Hyperparams: n_steps=100 batch_size=100 n_epochs=8 gamma=0.99 gae_lambda=0.98
             ent_coef=0.01 clip_range=0.2 lr=linear_schedule(1e-4) seed=0
Applied to: all 6 CLEF-TAR 2019 test topics (cross-family — see VENDORED_FROM)
```

### PPO hyperparameters (verbatim from vendor notebook)

```python
def linear_schedule(initial_value):
    def func(progress_remaining):
        return progress_remaining * initial_value
    return func

PPO(
    policy="MlpPolicy",
    env=DummyVecEnv([lambda: TAREnv(target_recall=r, topics_list=train_topic_ids)]),
    n_steps=100,
    batch_size=100,
    n_epochs=8,
    gamma=0.99,
    gae_lambda=0.98,
    ent_coef=0.01,
    clip_range=0.2,
    learning_rate=linear_schedule(1e-4),
    seed=0,
).learn(total_timesteps=100_000)
```

### Train flow (`--skip-train` fast path)

```python
cache = out_dir / f"recall_{target_recall:.2f}.zip"
if cache.exists() and not force_retrain:
    model = PPO.load(cache, env=env)
else:
    model = PPO(...)
    model.learn(total_timesteps=100_000)
    model.save(cache)
```

### Inference flow

For each `(topic_id, target_recall)`:
1. Rank documents by `s` descending from parquet → `doc_rank_dic`, `rank_rel_dic`
2. Inject globals, instantiate `TAREnv(target_recall=target_recall, topic_id=topic_id)`
3. `obs, _ = env.reset()`; step loop: `action, _ = model.predict(obs, deterministic=True)`
4. At `STOP` or truncation: `examined = env.n_samp_docs`; `examined_pmids` = first N pmids in rank order
5. Compute WSS via `wss_at_recall()`; log `peak_rss_kb`

### Driver: `run_rlstop.py`

```
python -m cascade_rc.baselines.run_rlstop \
  --data-dir  artefacts/cascade_rc/data \
  --out-dir   artefacts/baselines/rlstop \
  --train-dir artefacts/baselines/rlstop \
  [--topics CD008874 ...] \
  [--recalls 0.80 0.90 0.95 1.0] \
  [--skip-train] \
  [--force-retrain]
```

Output: `artefacts/baselines/rlstop/rlstop_results.parquet` (24 rows).

---

## 4. Acceptance Criteria

1. `artefacts/baselines/autostop/autostop_results.parquet` — 24 rows, 8 columns, correct dtypes.
2. `artefacts/baselines/rlstop/rlstop_results.parquet` — 24 rows, 8 columns, correct dtypes.
3. `pd.concat([autostop_df, rlstop_df])` produces 48 rows with no NaN columns — schema parity verified.
4. `method` column contains only `"autostop"` or `"rlstop"` (no NaN).
5. `--dry-run` flag writes 0-row schema-only parquets without calling `autostop_method()` or loading SB3.
6. `peak_rss_kb` is logged per run (non-zero on all platforms except Windows where `ru_maxrss` needs platform guard).

---

## 5. Files Changed / Created

| file | change |
|---|---|
| `cascade_rc/baselines/autostop_vendor/` | **New** — vendored package |
| `cascade_rc/baselines/rlstop_vendor/` | **New** — vendored package + training data |
| `cascade_rc/baselines/run_autostop.py` | **New** — driver script |
| `cascade_rc/baselines/run_rlstop.py` | **New** — driver script |
| `artefacts/baselines/rlstop/README.md` | **New** — model weight documentation |
