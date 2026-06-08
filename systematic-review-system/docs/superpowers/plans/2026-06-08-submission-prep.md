# Submission Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge finalization and documentation branches into development, delete macOS iCloud conflict-copy files (untracked, never committed), update/create README files at the root and per-component level, fix missing requirements, and verify both the CASCADE-RC and general pipeline still work perfectly after every destructive step.

**Architecture:** Repository hygiene and documentation pass only — no algorithm or pipeline changes. All changes land on `development`. The two pipelines (cascade_rc and main orchestrator) must remain runnable after every task; verification runs after each deletion task.

**Tech Stack:** Python 3.11, git, bash, existing `venv` inside `systematic-review-system/`

---

## Context for executor

### Branch reality (assessed at plan-write time)

| Branch | Status vs `development` |
|--------|------------------------|
| `finalization` | 1 commit ahead — NOT merged |
| `documentation` | 4 commits ahead — NOT merged |

### What "macOS duplicate files" means

macOS iCloud Drive creates conflict copies when two devices sync the same file simultaneously. The copies are named with a space+number before the extension: `config 2.py`, `config 3.py`, `README 2.md`, `main 2.py`, etc. — identical pattern to the real files but with a space-number suffix. Every single one of these files is **untracked by git** (`??` in `git status`), meaning they were **never committed** and deleting them cannot affect the repository or the Python interpreter (Python ignores filenames with spaces for module imports).

### Desktop output path

`rescreen_cascade_dta.py` has `BASE_OUTPUT = Path("/Users/nikitagolovanov/Desktop/final_Data")`. **Do not change this** — it is intentional.

---

## Files to modify / create

| Action | Path |
|--------|------|
| Create | `README.md` (root) — project-level overview |
| Modify | `systematic-review-system/README.md` — add new scripts, frontend, DTA rescreen, update cascade-RC integration status |
| Modify | `systematic-review-system/cascade_rc/README.md` — update "future integration" language to reflect live integration |
| Modify | `systematic-review-system/requirements.txt` — add `fastapi`, `uvicorn[standard]`, `matplotlib`, `seaborn`, `scipy`, `scikit-learn`, `pydantic`, `pydantic-settings` |
| Modify | root `.gitignore` — add macOS duplicate pattern |
| Delete | All untracked `* 2.*`, `* 3.*`, `* 4.*` macOS conflict files (identified via `git status --short | grep "^??" | grep " [234]\."`) |

---

## Task 1: Merge `documentation` into `development`

**Files:** git only

- [ ] **Step 1: Switch to development**

```bash
git checkout development
```

- [ ] **Step 2: Merge documentation**

```bash
git merge documentation --no-ff -m "merge(documentation): meeting minutes, thesis link, gitignore"
```

Expected: clean merge — documentation only adds files under `documenation/` and `.gitignore`.

- [ ] **Step 3: Verify**

```bash
git log --oneline -5
```

Expected: merge commit on top.

---

## Task 2: Merge `finalization` into `development`

**Files:** git only

- [ ] **Step 1: Still on development — merge finalization**

```bash
git merge finalization --no-ff -m "merge(finalization): DTA rescreen, comparative evaluation, frontend, pipeline extensions"
```

Expected: clean merge. If conflicts arise, keep finalization's version for all `systematic-review-system/` code files.

- [ ] **Step 2: Verify the new files landed**

```bash
ls systematic-review-system/evaluation/ && ls systematic-review-system/frontend/
```

Expected: lists `benchmark_evaluator.py`, `build_tables.py`, `sac_metric.py` and `server.py`, `static/`.

- [ ] **Step 3: Sanity-check imports**

```bash
cd systematic-review-system && source venv/bin/activate && python -c "import cascade_rc; from evaluation.benchmark_evaluator import BenchmarkEvaluator; print('imports ok')"
```

Expected: `imports ok`

---

## Task 3: Delete macOS iCloud duplicate files and update .gitignore

**IMPORTANT:** Only files matching the pattern `* 2.*`, `* 3.*`, `* 4.*` that are **untracked** (`??` in git status) are deleted. Never touch tracked files.

**Files:** untracked duplicates; modify root `.gitignore`

- [ ] **Step 1: Confirm the exact list of files to delete — only untracked ones**

```bash
cd /Users/nikitagolovanov/Documents/GitHub/Autonomous-Research-Assistant--Bachelor-Thesis
git status --short | grep "^??" | grep -E '".*[[:space:]][234]\.' | wc -l
```

Expected: a number (the count of duplicate files). All are untracked.

- [ ] **Step 2: Double-check that none of the deletion targets are tracked by git**

```bash
git ls-files | grep -E " [234]\." | wc -l
```

Expected: `0` — confirms zero tracked files match the pattern.

- [ ] **Step 3: Delete only untracked duplicate files**

```bash
# Extract paths from git status, strip quotes, and delete
git status --short | grep "^??" | grep -E '".*[[:space:]][234]\.' \
  | sed 's/^?? "//' | sed 's/"$//' \
  | while read f; do rm -f "$f"; done
```

- [ ] **Step 4: Handle duplicate directories (e.g. `<cache_path> 3`, `superpowers 2`)**

```bash
git status --short | grep "^??" | grep -E '".*[[:space:]][234]/' \
  | sed 's/^?? "//' | sed 's/"$//' \
  | while read d; do rm -rf "$d"; done
```

- [ ] **Step 5: Verify deletion — git status should show no more duplicates**

```bash
git status --short | grep -E " [234]\." | wc -l
```

Expected: `0`

- [ ] **Step 6: Immediately verify cascade_rc pipeline still imports**

```bash
cd systematic-review-system && source venv/bin/activate
python -c "
import cascade_rc
from cascade_rc.config import CascadeRCConfig
from cascade_rc.calibration.main_calibrate import run_calibration
from cascade_rc.evaluation.metrics import compute_metrics
print('cascade_rc ok')
"
```

Expected: `cascade_rc ok` — if this fails, stop immediately and diagnose.

- [ ] **Step 7: Verify main pipeline still imports**

```bash
python -c "
from main import load_protocol
from orchestrators.main_orchestrator import MainOrchestrator
from orchestrators.screening_orchestrator import ScreeningOrchestrator
from tier2_screening.cascade_rc_router import CascadeRCRouter
print('main pipeline ok')
"
```

Expected: `main pipeline ok` — if this fails, stop immediately and diagnose.

- [ ] **Step 8: Add pattern to root .gitignore so macOS duplicates are ignored going forward**

Open the root `.gitignore` and append:

```
# macOS iCloud sync conflict copies (never real files)
*\ 2.*
*\ 3.*
*\ 4.*
*\ 2/
*\ 3/
*\ 4/
```

- [ ] **Step 9: Commit**

```bash
git add .gitignore
git commit -m "chore: delete macOS iCloud duplicate files; gitignore pattern to prevent recurrence"
```

---

## Task 4: Fix missing dependencies in requirements.txt

New files added in finalization (`frontend/server.py`, `generate_graphs.py`, `run_comparative.py`, `evaluation/`) use packages not currently in `requirements.txt`.

**Files:**
- Modify: `systematic-review-system/requirements.txt`

- [ ] **Step 1: Replace requirements.txt**

Full file content:

```
anthropic>=0.49.0
openai>=1.30.0
sentence-transformers>=2.7.0
faiss-cpu>=1.7.4
rank-bm25>=0.2.2
numpy>=1.24.0
scipy>=1.11.0
scikit-learn>=1.3.0
pandas>=2.0
pyarrow>=14.0
matplotlib>=3.7.0
seaborn>=0.13.0
python-dotenv>=1.0.0
nltk>=3.8.0
pdfminer.six>=20221105
lxml>=4.9.0
requests>=2.31.0
python-Levenshtein>=0.21.0
torch>=2.0.0
transformers>=4.35.0
aiohttp>=3.9.0
biopython>=1.81
pyltr>=0.2.6
stable-baselines3>=2.0.0
gymnasium>=0.29.0
pydantic>=2.7.0
pydantic-settings>=2.3.0
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
tqdm>=4.66.0
joblib>=1.4.0
tenacity>=8.3.0
confseq>=0.0.11
```

- [ ] **Step 2: Verify the venv already satisfies these (dry run)**

```bash
cd systematic-review-system && source venv/bin/activate
pip install -r requirements.txt --dry-run 2>&1 | grep -i "would install\|already satisfied" | wc -l
```

Expected: most lines say "already satisfied"; any "would install" lines are the newly added packages — that is expected and correct.

- [ ] **Step 3: Commit**

```bash
git add systematic-review-system/requirements.txt
git commit -m "chore(deps): add fastapi, uvicorn, matplotlib, seaborn, scipy, sklearn, pydantic to requirements.txt"
```

---

## Task 5: Write root README.md

The current root `README.md` is two lines. Replace it with a proper project overview that explains both pipelines and links to the per-component READMEs.

**Files:**
- Modify: `README.md` (root)

- [ ] **Step 1: Rewrite root README.md**

```markdown
# Autonomous Research Assistant — Bachelor Thesis

**BFH Bachelor Thesis 2024/25 · Nikita Golovanov**

End-to-end system for automated PRISMA 2020-compliant systematic literature reviews, combining a multi-tier LLM screening pipeline with CASCADE-RC — a statistically-certified abstract screening module evaluated on Cochrane Diagnostic Test Accuracy benchmarks.

---

## What this project contains

### 1. Full Systematic Review Pipeline (`systematic-review-system/`)

Automates the complete PRISMA 2020 workflow from a structured protocol JSON:

- **Tier 1 — Search:** PubMed + Semantic Scholar with iterative query refinement and deduplication
- **Tier 2 — Screening:** LLM abstract screening → hybrid full-text retrieval → three-tier full-text router (LLM / embedding cross-attention / RAG)
- **Tier 3 — Synthesis:** PICO extraction, quality assessment (RoB 2 / NOS), PRISMA flow diagram, full review report

→ [Full pipeline documentation](systematic-review-system/README.md)

### 2. CASCADE-RC (`systematic-review-system/cascade_rc/`)

Calibrated Cascade with Risk Control — a standalone certified screening module that provably bounds the False-Negative Rate ≤ α at confidence ≥ 1−δ using the Learn Then Test framework. Evaluated on six CLEF-TAR 2017–2019 Cochrane DTA benchmark topics.

→ [CASCADE-RC documentation](systematic-review-system/cascade_rc/README.md)

---

## Quick start

```bash
cd systematic-review-system
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, OPENAI_API_KEY, …

# Run a full systematic review
python main.py CD008874_protocol.json

# Run CASCADE-RC on a CLEF-TAR topic
python cascade_rc/run_pipeline.py --topic CD008874

# Start the web frontend
uvicorn frontend.server:app --reload --port 8000
```

---

## Repository layout

```
README.md                          ← this file
systematic-review-system/
  main.py                          ← full pipeline entry point
  cascade_rc/                      ← CASCADE-RC certified screening module
  evaluation/                      ← comparative evaluation framework
  frontend/                        ← FastAPI web interface
  rescreen_cascade_dta.py          ← DTA rescreen for CASCADE-RC routing decisions
  rescreen_dta.py                  ← DTA rescreen for main-pipeline included set
  run_comparative.py               ← head-to-head numerical evaluation
  generate_graphs.py               ← publication figures
  README.md                        ← full pipeline documentation
documenation/                      ← meeting minutes, thesis links
```

---

## Datasets

The numerical evaluation uses the [CLEF-TAR 2017–2019](https://github.com/CLEF-TAR/tar) Cochrane DTA benchmark topics:
`CD008874`, `CD012768`, `CD011145`, `CD011768`, `CD011975`, `CD012080`.

Pre-scored parquets are expected under `systematic-review-system/artefacts/cascade_rc/data/` and CLEF-TAR qrel files under `systematic-review-system/data/clef_tar/`.

---

## Tests

```bash
cd systematic-review-system && source venv/bin/activate
pytest cascade_rc/tests/ -v          # CASCADE-RC unit + integration tests
pytest tests/ -v                      # main pipeline unit tests
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(root): replace 2-line stub with full project overview"
```

---

## Task 6: Update `systematic-review-system/README.md`

The existing README is solid but needs four updates: (1) architecture section is missing new scripts and directories, (2) models table needs a note about BFH internal endpoint, (3) "future integration" language about CASCADE-RC needs removing since `cascade_rc_router.py` now exists, (4) new usage sections for DTA rescreen, comparative eval, and the frontend.

**Files:**
- Modify: `systematic-review-system/README.md`

- [ ] **Step 1: Read the current file to know exact line numbers before editing**

Read `systematic-review-system/README.md` in full.

- [ ] **Step 2: Update the Architecture section**

After the existing `models/` block in the architecture tree, add:

```
cascade_rc/                       ← certified screening module (see cascade_rc/README.md)
evaluation/
    benchmark_evaluator.py        ← CLEF-TAR benchmark runner
    build_tables.py               ← LaTeX / CSV result tables
    sac_metric.py                 ← SAC recall metric
frontend/
    server.py                     ← FastAPI async web interface
    static/index.html             ← single-page UI

Top-level scripts:
    main.py                       ← run a full review
    rescreen_dta.py               ← DTA rescreen of main-pipeline included set
    rescreen_cascade_dta.py       ← DTA rescreen of CASCADE-RC routing decisions
    run_comparative.py            ← head-to-head numerical evaluation
    generate_graphs.py            ← publication figures
```

- [ ] **Step 3: Update the Models section**

Replace the existing Models table note to add:

```markdown
> **Note:** The BFH endpoint (`https://inference.mlmp.ti.bfh.ch/api/v1`) is institution-internal.
> External users should substitute any OpenAI-compatible endpoint and set `OPENAI_BASE_URL` and `OPENAI_MODEL` in `.env` accordingly.
```

- [ ] **Step 4: Add new usage sections before the Testing section**

Insert after the existing "Outputs" section:

```markdown
## DTA Rescreen

After running the main pipeline or CASCADE-RC, verify precision on included papers using a strict Diagnostic Test Accuracy prompt:

```bash
# Re-screen the main pipeline's included set for CD008874
python rescreen_dta.py

# Re-screen CASCADE-RC auto-included set for a given topic
python rescreen_cascade_dta.py CD008874
```

## Comparative Evaluation

```bash
# Head-to-head numerical evaluation (CASCADE-RC vs baselines) with result tables
python run_comparative.py

# Generate publication figures
python generate_graphs.py
```

## Web Frontend

```bash
uvicorn frontend.server:app --reload --port 8000
```

Opens the single-page review dashboard at `http://localhost:8000`. All API credentials must be set in `.env`.
```

- [ ] **Step 5: Commit**

```bash
git add systematic-review-system/README.md
git commit -m "docs(pipeline): add new scripts, frontend, DTA rescreen sections; BFH endpoint note"
```

---

## Task 7: Update `systematic-review-system/cascade_rc/README.md`

Only one change needed: the "Future integration with main.py" section at the bottom says the integration is planned — it is now live via `tier2_screening/cascade_rc_router.py`.

**Files:**
- Modify: `systematic-review-system/cascade_rc/README.md`

- [ ] **Step 1: Find the "Future integration" section**

Read the bottom 30 lines of `cascade_rc/README.md` to locate the exact text.

- [ ] **Step 2: Replace "Future integration" section**

Replace the existing `## Future integration with main.py` section with:

```markdown
## Integration with `main.py`

CASCADE-RC is self-contained and operates on pre-scored parquet files. It is wired into the main screening pipeline via `tier2_screening/cascade_rc_router.py`, which:

1. Receives ranked candidates from the Tier-1 / Tier-2 screening pipeline
2. Writes scored parquets in the CASCADE-RC format (`s`, `u`, `y_abstract`, `is_calib`)
3. Calls `cascade_rc.calibration.main_calibrate` per topic to produce the certified θ̂
4. Reads the `CertificateStore` at inference time to apply certified routing decisions

The key interface point is the parquet schema described in Step 1 above.
```

- [ ] **Step 3: Commit**

```bash
git add systematic-review-system/cascade_rc/README.md
git commit -m "docs(cascade-rc): update integration section — router is live in tier2_screening"
```

---

## Task 8: Final verification — run tests on development

- [ ] **Step 1: Run CASCADE-RC unit tests**

```bash
cd systematic-review-system && source venv/bin/activate
pytest cascade_rc/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests PASS (pre-existing skips are OK). If any test FAILS, stop and fix before proceeding.

- [ ] **Step 2: Run main pipeline unit tests**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 3: Protocol parse smoke test (DTA topic)**

```bash
python -c "
from main import load_protocol
p = load_protocol('CD008874_protocol.json')
print('DTA protocol ok:', p.title)
"
```

Expected: prints the protocol title without error.

- [ ] **Step 4: Full import chain smoke test**

```bash
python -c "
from orchestrators.main_orchestrator import MainOrchestrator
from tier2_screening.cascade_rc_router import CascadeRCRouter
from evaluation.benchmark_evaluator import BenchmarkEvaluator
from frontend import server
print('all imports ok')
"
```

Expected: `all imports ok`

---

## Task 9: Push development to remote

- [ ] **Step 1: Confirm working tree is clean**

```bash
git status
```

Expected: `nothing to commit, working tree clean`

- [ ] **Step 2: Push**

```bash
git push origin development
```

Expected: remote development is up to date.

---

## Self-Review

### Spec coverage

| Requirement | Task |
|------------|------|
| Check finalization merged to development | Pre-check (NOT merged — answered before plan) |
| Merge documentation → development | Task 1 |
| Merge finalization → development | Task 2 |
| Delete macOS iCloud duplicate files safely | Task 3 |
| Verify pipeline works after deletion | Task 3 steps 6–7 + Task 8 |
| Fix missing requirements | Task 4 |
| Root README — general project overview | Task 5 |
| Full pipeline README updated | Task 6 |
| CASCADE-RC README updated | Task 7 |
| Run all tests, double-check pipelines | Task 8 |
| Push to remote | Task 9 |

### Decisions NOT in scope

- **Hardcoded desktop path** in `rescreen_cascade_dta.py` — intentional, left as-is per user instruction
- **Leftover fix_syntax scripts** — kept; user did not explicitly ask to delete them
- No merges to `main` — user decision

### Placeholder scan

No TBD, TODO, or "fill in" placeholders — all steps include exact commands.

### Type consistency

No new types introduced — docs/cleanup only.
