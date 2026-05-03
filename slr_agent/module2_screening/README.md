# Module 2 — Screening Layer

Automated title/abstract screening for systematic literature reviews (SLR).

Takes a pool of deduplicated papers (from Module 1) and a PICO research query, then classifies each paper as **include**, **uncertain**, or **exclude** — replicating the manual screening step that typically takes researchers weeks.

---

## How It Works (Before You Run Anything)

### Three Distinct Operations

| # | Operation | When | What Changes |
|---|-----------|------|--------------|
| 1 | **Fine-tune SPECTER2** | Once, offline, before deployment | Updates transformer weights |
| 2 | **Cold-start SVM fitting** | Per run, at runtime, on CPU | Fits fresh every time — no persistent weights |
| 3 | **ExampleBuffer accumulation** | Per run, at runtime, no fitting | Grows during a run, resets between runs |

**You only do Operation 1 once.** Operations 2 and 3 happen automatically inside the pipeline.

### The Pipeline Flow (L1 → L5)

```
Papers + PICO Query
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ L1: EmbeddingLayer                                  │
│ • Encodes each paper title+abstract → (768,) vector  │
│ • Encodes PICO query → anchor vector                 │
│ • Model: SPECTER2 (fine-tuned) or MedCPT             │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ L2: SeparabilityLayer                               │
│ • KMeans(2) on all paper embeddings                  │
│ • Davies-Bouldin Score → how separable are clusters? │
│ • DBS < 1.5 → "classifier" path (L3a SVM)           │
│ • DBS ≥ 1.5 → "llm" path (L3b zero-shot)            │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ L3a: SVMScreeningLayer  OR  L3b: LLMZeroshotLayer   │
│ L3a (classifier path):                              │
│   • Seeds SVM from cosine-ranked papers              │
│   • Top 15% = positive, bottom 30% = negative       │
│   • Calibrated SVM → probability per paper           │
│ L3b (LLM path):                                     │
│   • Zero-shot LLM classification per paper           │
│   • Concurrent calls (10 max)                        │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ L4: ConfidenceGateLayer                             │
│ • Confident papers (score ≤0.30 or ≥0.70) → pass    │
│ • Borderline papers → Chain-of-Thought re-eval      │
│ • ExampleBuffer injects few-shot context             │
│ • Buffer grows during run (later papers richer)      │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ L5: StoppingCriterionRouter                         │
│ • Routes papers to included/excluded/uncertain       │
│ • Sliding window: 3 empty windows → stop screening  │
│ • Remaining papers → "uncertain" after stop          │
└─────────────────────────────────────────────────────┘
        │
        ▼
  ScreeningResult (3 buckets + full audit trail)
```

### Key Design Decisions

- **Review-level train/val/test split** — prevents data leakage. The model must generalise to unseen reviews, not just unseen papers from reviews it already saw.
- **Class weight 12:1 in SVM** — inclusion rates can be as low as 1%. Without this, the SVM would just predict everything as irrelevant.
- **Domain penalty (-0.20)** — catches papers that are geometrically close to PICO but topically off-topic.
- **Pass-through gate** — avoids expensive LLM calls for confident decisions. Only borderline papers get CoT re-evaluation.

---

## File Structure

### Root (`module2_screening/`)

| File | Purpose |
|------|---------|
| `models.py` | All data classes: `Paper`, `SearchQuery`, `EmbeddedPaper`, `FirstPassResult`, `ReevalResult`, `ScreeningDecision`, `ScreeningResult`, `ExampleBuffer` |
| `connectors.py` | `GptConnector` — wrapper around Anthropic Claude API for LLM calls |
| `prisma_log.py` | `PrismaLog` singleton — tracks all screening counts for PRISMA flow diagram |
| `layers.py` | L1–L5 implementation: `EmbeddingLayer`, `SeparabilityLayer`, `SVMScreeningLayer`, `LLMZeroshotScreeningLayer`, `ConfidenceGateLayer`, `StoppingCriterionRouter` |
| `orchestrator.py` | `ScreeningOrchestrator` — wires L1→L5 together. `runPipeline()` is the entry point from Module 1 |
| `audit_and_run.py` | Standalone data audit + visualization utility for inspecting data before training |

### Classifier (`module2_screening/classifier/`)

| File | Purpose |
|------|---------|
| `training.py` | `SynergyDataAudit`, `SynergySplitter`, `SynergyTrainer` — data audit, review-level splitting, and SPECTER2 fine-tuning |
| `validation.py` | `ScreeningEvaluator` — computes WSS@95 on held-out test reviews to validate the fine-tuned model |

---

## Running It

### Step 1 — Data Audit (Before Training)

```bash
cd module2_screening/classifier
python training.py --audit --synergy ./synergy_data/
```

Reads all CSVs, prints per-review stats (paper count, inclusion %, missing fields). Use this to decide which reviews to hold out for val/test.

### Step 2 — Train/Val/Test Split

```bash
python training.py --audit --split --synergy ./synergy_data/
```

Shuffles reviews (fixed seed), splits 70/15/15 at review level. Prints counts.

### Step 3 — Fine-Tune SPECTER2 (Operation 1)

```bash
python training.py --audit --split --train \
  --synergy ./synergy_data/ \
  --output ./specter2_screening/ \
  --epochs 3 --batch 16
```

Runs contrastive fine-tuning. Saves model to `./specter2_screening/`. This is the **only** true ML training — everything else is runtime fitting.

### Step 4 — Validate (WSS@95)

```python
from module2_screening.classifier.validation import ScreeningEvaluator
from module2_screening.orchestrator import ScreeningOrchestrator

evaluator = ScreeningEvaluator()
result = evaluator.evaluate(papers_with_labels, query, pipeline)
print(f"WSS@95: {result['wss_at_95']}")
```

WSS@95 > 0.50 means the pipeline saves more than half the manual screening work.

### Step 5 — Run Screening (Operations 2 + 3)

```python
from module2_screening.orchestrator import ScreeningOrchestrator, runPipeline

# From Module 1 hand-off
result = runPipeline(form_data, emit_log_callback)

# Or directly
orchestrator = ScreeningOrchestrator()
result = orchestrator.runScreening(papers, query, emit_log_callback)
```

Returns `ScreeningResult` with three buckets: `includedPapers`, `uncertainPapers`, `excludedPapers`.

---

## Expected Outputs

| Artifact | Location | Description |
|----------|----------|-------------|
| Fine-tuned model | `./specter2_screening/` | HuggingFace model directory |
| Audit CSV | `./synergy_data/audit_reviews.csv` | Per-review stats |
| Audit plots | `./synergy_data/*.png` | Inclusion % bar chart + histogram |
| PRISMA log | `PrismaLog.getInstance().toDict()` | Full audit trail for flow diagram |
| Screening result | `ScreeningResult` object | Three paper buckets + all decisions |

---

## Dependencies

```
torch
transformers
scikit-learn
sentence-transformers  # training only
pandas
numpy
anthropic              # LLM calls
```

Install: `pip install torch transformers scikit-learn sentence-transformers pandas numpy anthropic`
