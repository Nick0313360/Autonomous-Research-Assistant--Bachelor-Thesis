# CASCADE-RC — Calibrated Cascade with Risk Control

A standalone Python package for **certified systematic-review screening**.  
Given a scored corpus (embedding score `s`, LLM self-consistency score `u`, and relevance label `y`), it calibrates a three-threshold routing decision θ̂ = (λ_lo, λ_hi, τ_SE) that provably keeps the False-Negative Rate ≤ α at confidence ≥ 1−δ (Learn Then Test framework).

> **Relationship to `main.py`:** CASCADE-RC is currently self-contained and operates on pre-scored parquet files.  
> It is designed to be wired into the main orchestrator pipeline in a future integration step.

---

## Package layout

```
cascade_rc/
├── config.py                   # All tunable parameters (LTTBudget, TopicConfig, CascadeRCConfig)
├── data/
│   ├── clef_tar_loader.py      # Ingest CLEF-TAR 2017–2019 benchmark topics
│   ├── pubmed_fetch.py         # Async PubMed abstract fetcher (with per-PMID cache)
│   ├── splits.py               # Stratified calibration / test split
│   └── score_normalizer.py     # Isotonic + Platt calibration for raw ranker scores
├── cache/
│   ├── llm_ensemble.py         # B=5 stochastic LLM screening ensemble → (vote, u score)
│   └── sqlite_cache.py         # Persistent SQLite cache for LLM calls
├── calibration/
│   ├── surrogate_loss.py       # Dominating FNR loss + slack tensors on the θ grid
│   ├── wsr_lcb.py              # Predictable-plug-in Waudby-Smith-Ramdas LCB
│   ├── hb_pvalue.py            # Hoeffding-Bentkus p-value (LTT multiple testing)
│   ├── walker.py               # Safest-to-riskiest fixed-sequence grid walk
│   └── main_calibrate.py       # Algorithm 1 orchestrator → writes certificate
├── certificates/
│   └── store.py                # CertificationResult serialisation / CertificateStore
├── evaluation/
│   ├── metrics.py              # wss_at_recall, llm_query_volume, bootstrap_eta_upper, …
│   ├── tar_eval_wrapper.py     # Subprocess wrapper for vendored CLEF tar_eval.py
│   └── figures.py              # Three publication figures (PDF + PNG)
├── baselines/
│   ├── run_autostop.py         # AUTOSTOP (Li & Kanoulas 2020) driver
│   ├── run_rlstop.py           # RLStop (PPO-based) driver
│   └── scrc.py                 # SCRC-I and SCRC-T (Xu et al. 2025) driver
├── ablations/
│   ├── m_sensitivity.py        # Sweep grid resolution M ∈ {26,35,50,75,100}
│   ├── budget_split.py         # Sweep δ_η / δ_LTT split with fixed δ_total
│   └── walk_ordering.py        # Safest-first vs riskiest-first walk comparison
└── synthetic/
    └── beta_mixture.py         # Beta-mixture generator for unit tests & paper example
```

---

## Core concepts

### The cascade routing

Every document gets two scores:

| Score | Meaning | Source |
|-------|---------|--------|
| `s` | BM25 / embedding relevance score in [0, 1] | Ranker |
| `u` | LLM self-consistency in [0, 1] — fraction of B=5 calls that agree | Ensemble cache |

At inference time the certified threshold θ̂ = (λ_lo, λ_hi, τ_SE) routes each document:

```
s < λ_lo              → cheap-reject   (auto_reject)    — skip cheaply
s ≥ λ_hi              → auto-include   (auto_accept)    — safe include
λ_lo ≤ s < λ_hi
  and u ≥ τ_SE        → LLM-self-evident (llm_escalate) — LLM confirms
  and u < τ_SE        → human review   (human_review)   — uncertain, escalate
```

### The certificate

Calibration (Algorithm 1 in `main_calibrate.py`) searches for the θ̂ on a 3D grid that:
1. Minimises human-review volume
2. Maintains FNR ≤ α with probability ≥ 1−δ (Learn Then Test + Waudby-Smith-Ramdas confidence sequences)

The result is a `CertificationResult` JSON saved under `artefacts/cascade_rc/certificates/`.

### Key parameters (all in `config.py`)

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `ltt.alpha` | 0.10 | Target FNR bound |
| `ltt.delta_total` | 0.10 | Total failure probability |
| `ltt.delta_eta` | 0.03 | Budget for η upper bound |
| `ltt.delta_LTT` | 0.07 | Budget for LTT calibration |
| `ltt.K` | 20 | Grid resolution per axis |
| `ltt.B` | 5 | LLM ensemble size |
| `ltt.c_human` | 5.0 | Cost weight for human review |
| `ltt.c_llm` | 0.001 | Cost weight for LLM escalation |

Override via env vars prefixed `CRC_` or a `cascade_rc.yaml` file:

```bash
CRC_LTT__ALPHA=0.05 venv/bin/python -m cascade_rc.calibration.main_calibrate ...
```

---

## Full workflow (step by step)

### Prerequisites

All commands are run from `systematic-review-system/` with:

```bash
source venv/bin/activate   # or prefix every command with venv/bin/python
```

---

### Step 1 — Prepare scored parquet

Each topic needs a parquet file with these columns:

| Column | Type | Description |
|--------|------|-------------|
| `pmid` | str | Document ID |
| `s` | float64 | Relevance score ∈ [0, 1] |
| `u` | float64 | LLM self-consistency ∈ [0, 1] |
| `y_abstract` | int8 | Ground-truth label (1=relevant, 0=not) |
| `llm_y_hat` | int8 | LLM majority prediction |
| `is_calib` | int8 | 1=calibration set, 0=test set |

**Option A — use CLEF-TAR benchmark data:**

```bash
# Loads topics from data/clef_tar/, fetches PubMed abstracts, writes parquets
venv/bin/python -m cascade_rc.data.clef_tar_loader \
    --data-dir data/clef_tar \
    --out-dir  artefacts/cascade_rc/data \
    --topics   CD008874 CD012080 CD012768 CD011768 CD011975 CD011145
```

**Option B — generate synthetic data (for testing/development):**

```bash
venv/bin/python -m cascade_rc.synthetic.beta_mixture \
    --n-docs 2000 \
    --prevalence 0.05 \
    --out-dir artefacts/cascade_rc/data
```

---

### Step 2 — Run LLM ensemble (populate `u` scores)

```bash
venv/bin/python -m cascade_rc.cache.llm_ensemble \
    --parquet artefacts/cascade_rc/data/CD008874.parquet \
    --topic   CD008874 \
    --cache-db artefacts/cascade_rc/llm_cache.db
```

The ensemble makes B=5 stochastic calls per document, aggregates votes, and writes `u` back into the parquet. Results are cached in SQLite so re-runs are free.

---

### Step 3 — Calibrate (produce certificate)

```bash
venv/bin/python -m cascade_rc.calibration.main_calibrate \
    --topic         CD008874 \
    --calib-parquet artefacts/cascade_rc/data/CD008874.parquet \
    --artefact-dir  artefacts/cascade_rc \
    --chunk-size    500
```

Writes `artefacts/cascade_rc/certificates/CD008874.json` containing θ̂, FNR bound, slack matrix, and certification status (`certified` | `abstained`).

---

### Step 4 — Evaluate per topic

```bash
venv/bin/python -m cascade_rc.evaluation.metrics \
    --topic        CD008874 \
    --artefact-dir artefacts/cascade_rc
```

Prints JSON with:
- `wss95` — Work Saved over Sampling at 95% recall
- `llm_volume` — routing breakdown (auto_reject/accept/llm_escalate/human_review counts)
- `slack_ratio_mean` — tightness of the WSR bound

---

### Step 5 — Run baseline comparisons

Each baseline produces a results parquet with identical schema (`method, topic_id, target_recall, examined, recall_achieved, wss_95, wss_status`).

**AUTOSTOP** (Li & Kanoulas 2020 — CAL-based stopping):

```bash
venv/bin/python -m cascade_rc.baselines.run_autostop \
    --data-dir data/clef_tar \
    --out-dir  artefacts/baselines/autostop \
    --topics   CD008874 CD012080 CD012768 \
    --recalls  0.80 0.90 0.95 1.0

# Schema-only dry run (fast, no computation):
venv/bin/python -m cascade_rc.baselines.run_autostop --dry-run
```

**RLStop** (PPO reinforcement learning):

```bash
# Full run (trains PPO models, then infers):
venv/bin/python -m cascade_rc.baselines.run_rlstop \
    --data-dir  data/clef_tar \
    --out-dir   artefacts/baselines/rlstop \
    --train-dir artefacts/baselines/rlstop \
    --recalls   0.80 0.90 0.95 1.0

# Reuse cached PPO models (skip training):
venv/bin/python -m cascade_rc.baselines.run_rlstop --skip-train

# Force PPO retraining:
venv/bin/python -m cascade_rc.baselines.run_rlstop --force-retrain

# Dry run:
venv/bin/python -m cascade_rc.baselines.run_rlstop --dry-run
```

**SCRC-I and SCRC-T** (Xu et al. 2025 — Selective Conformal Risk Control):

```bash
# Both variants:
venv/bin/python -m cascade_rc.baselines.scrc \
    --data-dir     artefacts/cascade_rc/data \
    --out-dir      artefacts/baselines/scrc \
    --recalls      0.80 0.90 0.95 1.0 \
    --variants     I T \
    --abstain-rate 0.10

# SCRC-I only:
venv/bin/python -m cascade_rc.baselines.scrc --variants I

# SCRC-T only:
venv/bin/python -m cascade_rc.baselines.scrc --variants T

# Dry run:
venv/bin/python -m cascade_rc.baselines.scrc --dry-run
```

---

### Step 6 — Generate publication figures

Copy baseline parquets to the figures loader's expected location, then generate:

```bash
mkdir -p artefacts/cascade_rc/baselines
cp artefacts/baselines/autostop/autostop_results.parquet artefacts/cascade_rc/baselines/
cp artefacts/baselines/rlstop/rlstop_results.parquet     artefacts/cascade_rc/baselines/
cp artefacts/baselines/scrc/scrc_results.parquet         artefacts/cascade_rc/baselines/
# cascade_rc_results.parquet and cascade_rc_routing.parquet (if available)

PYTHONHASHSEED=0 venv/bin/python -m cascade_rc.evaluation.figures \
    --artefact-dir artefacts/cascade_rc
```

Outputs to `artefacts/cascade_rc/figures/`:

| File | Figure |
|------|--------|
| `figure1_risk_validity.pdf/.png` | FNR vs target α — CASCADE-RC always ≤ diagonal |
| `figure2_wss_efficiency.pdf/.png` | WSS vs target recall — efficiency comparison |
| `figure3_escalation.pdf/.png` | Routing fractions vs α — cascade dynamics |

> If any baseline parquet is missing, that method's line is synthesised deterministically (seed=0). Figures always render.

---

### Step 7 — Run ablation studies

**Grid resolution (m-sensitivity):**

```bash
venv/bin/python -m cascade_rc.ablations.m_sensitivity \
    --data-dir artefacts/cascade_rc/data \
    --out-dir  artefacts/cascade_rc/ablations \
    --topics   CD008874 CD012080 CD012768 \
    --seed     42 \
    --n-jobs   4

# Dry run:
venv/bin/python -m cascade_rc.ablations.m_sensitivity --dry-run
```

Sweeps M ∈ {26, 35, 50, 75, 100} and writes `m_sensitivity.parquet` + per-topic plots.

**δ budget split (δ_η vs δ_LTT):**

```bash
venv/bin/python -m cascade_rc.ablations.budget_split \
    --data-dir artefacts/cascade_rc/data \
    --out-dir  artefacts/cascade_rc/ablations \
    --n-jobs   4 \
    --dry-run
```

Sweeps 5 δ splits: (0.01,0.09), (0.03,0.07), (0.05,0.05), (0.07,0.03), (0.09,0.01).

**Walk ordering (safest-first vs riskiest-first):**

```bash
venv/bin/python -m cascade_rc.ablations.walk_ordering \
    --data-dir artefacts/cascade_rc/data \
    --out-dir  artefacts/cascade_rc/ablations \
    --n-jobs   4 \
    --dry-run
```

Compares the paper's safest-to-riskiest walk against the reverse ordering.

---

## Artefacts directory layout

```
artefacts/
├── cascade_rc/
│   ├── data/                   # Scored parquets — one per topic (CD008874.parquet, …)
│   ├── certificates/           # CertificationResult JSON — one per topic
│   ├── routing/                # Per-topic routing decisions (pmid, decision)
│   ├── baselines/              # Baseline result parquets + cascade_rc_results.parquet
│   ├── ablations/              # Ablation sweep parquets and plots
│   └── figures/                # Publication figures (.pdf + .png)
└── baselines/
    ├── autostop/               # autostop_results.parquet
    ├── rlstop/                 # rlstop_results.parquet + PPO model zips
    └── scrc/                   # scrc_results.parquet
```

---

## Tests

```bash
# All cascade_rc tests
venv/bin/pytest cascade_rc/tests/ -v

# Specific modules
venv/bin/pytest cascade_rc/tests/test_figures.py -v
venv/bin/pytest cascade_rc/tests/test_main_calibrate_synthetic.py -v
venv/bin/pytest cascade_rc/tests/test_scrc.py -v
venv/bin/pytest cascade_rc/tests/test_metrics.py -v

# Parallel (faster)
venv/bin/pytest cascade_rc/tests/ -v -n auto
```

---

## Common flags

| Flag | Available in | Effect |
|------|-------------|--------|
| `--dry-run` | autostop, rlstop, scrc, m_sensitivity, budget_split, walk_ordering | Write schema-only 0-row parquet, no computation |
| `--topics` | all sweeps | Restrict to a subset of topic IDs |
| `--recalls` | autostop, rlstop, scrc | Override target recall grid |
| `--n-jobs N` | calibrate, ablations | Parallel workers (loky backend) |
| `--skip-train` | rlstop | Reuse cached PPO zip files |
| `--force-retrain` | rlstop | Retrain even if cache exists |
| `--variants I T` | scrc | Select SCRC-I, SCRC-T, or both |
| `--artefact-dir` | calibrate, metrics, figures | Override default artefacts root |
| `--seed` | m_sensitivity | RNG seed for reproducibility |

---

## Future integration with `main.py`

The cascade_rc package is currently fed pre-scored parquets. The planned integration path:

1. `main.py` runs the existing Tier-1 / Tier-2 screening pipeline → produces ranked candidates
2. A new adapter writes scored parquets in the cascade_rc format (`s`, `u`, `y_abstract`, `is_calib`)
3. `cascade_rc.calibration.main_calibrate` is called per topic at the end of calibration phase
4. `cascade_rc.evaluation.metrics` is called at evaluation time to get certified routing decisions
5. The `ScreeningOrchestrator` uses the certified θ̂ from `CertificateStore` for final routing

The key interface point is the parquet schema in Step 1 above — once `main.py` emits files in that format, the cascade_rc pipeline runs unchanged.
