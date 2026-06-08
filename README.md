# Autonomous Research Assistant — Bachelor Thesis

An end-to-end system that automates PRISMA 2020-compliant systematic literature reviews using large language models, hybrid retrieval, and statistically certified screening.

---

## Components

### 1. Autonomous Systematic Review Pipeline (`systematic-review-system/`)

Orchestrates a nine-stage pipeline from protocol JSON to a finished review report:

1. Iterative PubMed + Semantic Scholar search with PICO-driven query refinement
2. Title-based deduplication (Levenshtein)
3. LLM abstract screening (bulk model, `temperature=0`)
4. Full-text retrieval via Unpaywall / Europe PMC / PubMed Central
5. Three-tier full-text screening: LLM direct → embedding cross-attention → RAG
6. Hallucination-guarded evidence extraction (sliding-window span verifier)
7. PICO element extraction with cosine-similarity alignment check
8. Study quality assessment (Cochrane RoB 2 / Newcastle-Ottawa Scale)
9. PRISMA 2020 flow diagram, structured review report, and full audit trail

### 2. CASCADE-RC (`systematic-review-system/cascade_rc/`)

A standalone certified-screening package built on the **Learn Then Test** framework.

Given a scored corpus (embedding score `s` and LLM self-consistency score `u`), it calibrates a three-threshold routing decision θ̂ = (λ_lo, λ_hi, τ_SE) that **provably bounds the False-Negative Rate ≤ α at confidence ≥ 1−δ**. Documents are routed to auto-reject, auto-accept, LLM escalation, or human review. Baselines (AUTOSTOP, RLStop, SCRC-I/T) and ablation studies are included.

---

## Repository Layout

```
.
├── README.md                          ← this file
├── systematic-review-system/
│   ├── main.py                        ← pipeline entry point
│   ├── run_pipeline.py                ← cascade_rc pipeline entry point
│   ├── requirements.txt
│   ├── example_protocol.json          ← sample review protocol
│   ├── CD008874_protocol.json         ← CLEF-TAR DTA topic protocols (×6)
│   ├── config/
│   │   ├── settings.py                ← all thresholds and credentials
│   │   └── prompts/                   ← LLM prompt templates
│   ├── infrastructure/
│   │   ├── llm_client.py              ← unified async LLM gateway
│   │   ├── encoder.py                 ← SPECTER2 embedding service
│   │   └── logger.py / storage.py
│   ├── orchestrators/
│   │   ├── main_orchestrator.py
│   │   ├── search_orchestrator.py
│   │   └── screening_orchestrator.py
│   ├── tier1_search/                  ← query builder, database connectors, dedup
│   ├── tier2_screening/               ← abstract screener, retrieval, full-text screening
│   ├── tier3_synthesis/               ← data extraction, quality assessment, reporting
│   ├── frontend/                      ← web UI (uvicorn)
│   ├── cascade_rc/                    ← CASCADE-RC package (see below)
│   │   ├── config.py
│   │   ├── data/                      ← CLEF-TAR loader, PubMed fetcher, splits
│   │   ├── cache/                     ← LLM ensemble + SQLite cache
│   │   ├── calibration/               ← Algorithm 1, LTT, WSR confidence sequences
│   │   ├── certificates/              ← CertificationResult store
│   │   ├── evaluation/                ← metrics, figures, tar_eval wrapper
│   │   ├── baselines/                 ← AUTOSTOP, RLStop, SCRC-I/T
│   │   ├── ablations/                 ← m-sensitivity, δ-split, walk-ordering
│   │   └── synthetic/                 ← Beta-mixture data generator
│   ├── artefacts/                     ← scored parquets, certificates, figures
│   └── tests/                         ← pipeline test suite
├── tests/                             ← top-level integration tests
├── data/                              ← CLEF-TAR benchmark data
├── code/                              ← auxiliary scripts
└── documenation/                      ← thesis-related documents
```

---

## Quick Start

### Prerequisites

```bash
cd systematic-review-system
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in API keys (see systematic-review-system/README.md)
```

### Run the full review pipeline

```bash
python main.py example_protocol.json
# with options:
python main.py my_protocol.json --review-id my_review_2025 --output-dir data/reports/my_review
```

### Run CASCADE-RC (certified screening)

```bash
# 1. Load CLEF-TAR benchmark data and score corpus
python -m cascade_rc.data.clef_tar_loader \
    --data-dir data/clef_tar --out-dir artefacts/cascade_rc/data \
    --topics CD008874 CD012080 CD012768 CD011768 CD011975 CD011145

# 2. Populate LLM self-consistency scores (u)
python -m cascade_rc.cache.llm_ensemble \
    --parquet artefacts/cascade_rc/data/CD008874.parquet --topic CD008874

# 3. Calibrate — produces certified θ̂ certificate
python -m cascade_rc.calibration.main_calibrate \
    --topic CD008874 --calib-parquet artefacts/cascade_rc/data/CD008874.parquet

# 4. Evaluate (WSS@95, routing breakdown)
python -m cascade_rc.evaluation.metrics --topic CD008874
```

### Start the web frontend

```bash
uvicorn frontend.server:app --reload
```

---

## Dataset

Experiments use the **CLEF-TAR 2017–2019 Cochrane Diagnostic Test Accuracy (DTA)** benchmark topics:

| Topic ID | Description |
|----------|-------------|
| CD008874 | Point-of-care tests for diagnosis |
| CD011145 | Rapid tests for group A streptococcal pharyngitis |
| CD011768 | Pulse oximetry for detecting hypoxaemia |
| CD011975 | Ultrasonography for diagnosis of appendicitis |
| CD012080 | Liquid-based vs. conventional cytology |
| CD012768 | Imaging for hepatic lesions |

Topic protocol JSONs live at `systematic-review-system/CD<id>_protocol.json`. Raw benchmark data is in `data/clef_tar/`.

---

## Component READMEs

Full documentation for each component:

- **Systematic Review Pipeline:** [`systematic-review-system/README.md`](systematic-review-system/README.md)
- **CASCADE-RC:** [`systematic-review-system/cascade_rc/README.md`](systematic-review-system/cascade_rc/README.md)

---

## Tests

```bash
# Pipeline unit and acceptance tests (from systematic-review-system/)
pytest tests/test_end_to_end.py::TestProtocolLoading -v        # no network/GPU needed
pytest tests/test_end_to_end.py::TestEndToEnd -v               # requires live API + GPU
pytest tests/ -v                                               # full pipeline suite

# CASCADE-RC tests
pytest cascade_rc/tests/ -v                                    # all cascade_rc tests
pytest cascade_rc/tests/ -v -n auto                            # parallel (faster)

# Key cascade_rc test files
pytest cascade_rc/tests/test_main_calibrate_synthetic.py -v   # calibration on synthetic data
pytest cascade_rc/tests/test_figures.py -v                    # figure rendering
pytest cascade_rc/tests/test_scrc.py -v                       # SCRC baseline
pytest cascade_rc/tests/test_metrics.py -v                    # evaluation metrics
```
