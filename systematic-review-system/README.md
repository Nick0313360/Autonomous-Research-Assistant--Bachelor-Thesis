# Autonomous Systematic Review System

An end-to-end pipeline that automates PRISMA 2020-compliant systematic literature reviews using large language models, hybrid retrieval, and structured evidence extraction.

## Overview

The system takes a structured review protocol (PICO framework + eligibility criteria) and autonomously:

1. **Searches** PubMed and Semantic Scholar, refining queries iteratively until saturation
2. **Deduplicates** records by title similarity
3. **Screens** abstracts with an LLM-based classifier (fast, bulk model)
4. **Retrieves** full texts via Unpaywall, Europe PMC, and PubMed Central
5. **Screens** full texts using a three-tier router (LLM → embedding cross-attention → RAG)
6. **Extracts** structured data fields and PICO elements per included study
7. **Assesses** study quality using Cochrane RoB 2 (RCTs) or Newcastle-Ottawa Scale (observational)
8. **Reports** a PRISMA 2020 flow diagram, full review report, and audit trail

## Architecture

```
main.py
└── orchestrators/
    ├── main_orchestrator.py      ← top-level pipeline driver
    ├── search_orchestrator.py    ← iterative search + deduplication
    └── screening_orchestrator.py ← 9-stage screening pipeline

tier1_search/
    ├── query_builder.py          ← PICO → SearchQuery
    ├── database_connector.py     ← fan-out to PubMed + Semantic Scholar
    ├── pubmed_connector.py
    ├── semantic_scholar_connector.py
    ├── deduplication.py          ← Levenshtein title dedup
    ├── coverage_analyzer.py      ← saturation detection
    └── search_refinement.py      ← gap-driven query expansion

tier2_screening/
    ├── abstract_screener.py      ← LLM criterion check on title+abstract
    ├── hybrid_retriever.py       ← FAISS + BM25 + Reciprocal Rank Fusion
    ├── fulltext_retriever.py     ← Unpaywall → Europe PMC → PubMed Central
    ├── document_parser.py        ← PDF (pdfminer) + XML (lxml/JATS)
    ├── fulltext_screener.py      ← tier-routed full-text screening
    ├── criterion_aware_rag.py    ← RAG index per document
    ├── span_verifier.py          ← Levenshtein hallucination check
    ├── pico_extractor.py         ← two-pass PICO extraction + alignment check
    ├── decision_engine.py        ← Noisy-OR aggregation → FinalDecision
    └── example_buffer.py         ← few-shot example cache

tier3_synthesis/
    ├── data_extractor.py         ← 6 standard fields per included study
    ├── quality_assessor.py       ← RoB 2 + NOS domain-level judgments
    ├── prisma_reporter.py        ← flow diagram, review report, audit trail
    └── review_evaluator.py       ← search completeness + F2 accuracy metrics

infrastructure/
    ├── llm_client.py             ← unified async LLM gateway (GPT + Claude)
    ├── encoder.py                ← SPECTER2 with abstract/pico/section heads
    ├── prisma_manager.py         ← PRISMA 2020 stage counter
    ├── logger.py                 ← SQLite DecisionRecord audit log
    └── storage.py                ← versioned file storage

models/
    └── data_classes.py           ← all dataclasses and enums

cascade_rc/                       ← certified screening module (see cascade_rc/README.md)
evaluation/
    benchmark_evaluator.py        ← CLEF-TAR benchmark runner
    build_tables.py               ← LaTeX / CSV result tables
    sac_metric.py                 ← SAC recall metric
frontend/
    server.py                     ← FastAPI async web interface
    static/index.html             ← single-page UI

config/
    ├── settings.py               ← all thresholds and credentials
    └── prompts/                  ← LLM prompt templates

Top-level scripts (new):
    rescreen_dta.py               ← DTA rescreen of main-pipeline included set
    rescreen_cascade_dta.py       ← DTA rescreen of CASCADE-RC routing decisions
    run_comparative.py            ← head-to-head numerical evaluation
    generate_graphs.py            ← publication figures
```

## Models

| Role | Model | Used for |
|---|---|---|
| LLM-1 (bulk) | `gpt-oss:120b` via BFH endpoint | Abstract screening, PICO extraction, data extraction |
| LLM-2 (reasoning) | `claude-sonnet-4-6` via Anthropic API | Full-text screening, quality assessment |
| Embeddings | `allenai/specter2_base` | Hybrid retrieval, PICO alignment, section classification |

SPECTER2 projection heads output 128-dim vectors (abstract/PICO) and 256-dim vectors (section).

> **Note:** The BFH endpoint (`https://inference.mlmp.ti.bfh.ch/api/v1`) is institution-internal. External users should set `OPENAI_BASE_URL` and `OPENAI_MODEL` in `.env` to any OpenAI-compatible endpoint.

## Requirements

- Python 3.11+
- CUDA-capable GPU recommended for SPECTER2; CPU fallback supported

```
pip install -r requirements.txt
```

Key dependencies: `anthropic`, `openai`, `sentence-transformers`, `faiss-cpu`, `rank-bm25`, `pdfminer.six`, `lxml`, `aiohttp`, `python-Levenshtein`, `python-dotenv`

## Setup

**1. Copy and fill in credentials:**

```bash
cp .env.example .env
```

```
# .env
OPENAI_API_KEY=<BFH token>
OPENAI_BASE_URL=https://inference.mlmp.ti.bfh.ch/api/v1
OPENAI_MODEL=gpt-oss:120b

ANTHROPIC_API_KEY=<Anthropic API key>

PUBMED_API_KEY=<optional, raises rate limit>
PUBMED_EMAIL=your@email.com

SEMANTIC_SCHOLAR_API_KEY=<optional>
UNPAYWALL_EMAIL=your@email.com
```

**2. Download NLTK tokenizer data** (one-time):

```python
import nltk
nltk.download("punkt_tab")
```

## Usage

**Run a review from a protocol JSON file:**

```bash
python main.py example_protocol.json
python main.py my_protocol.json --review-id my_review_2025 --output-dir data/reports/my_review
```

**Protocol JSON format:**

```json
{
  "title": "AI in education systematic review",
  "research_question": "Does AI improve student academic performance?",
  "pico": {
    "population": "university students",
    "intervention": "AI-based learning tools",
    "comparator": "traditional learning methods",
    "outcome": "academic performance grades",
    "study_design": "randomized controlled trial or quasi-experimental study"
  },
  "inclusion_criteria": [
    {"criterion_id": "IC-01", "text": "Study involves human students", "type": "MANDATORY"}
  ],
  "exclusion_criteria": [
    {"criterion_id": "EC-01", "text": "Conference abstracts without full text", "type": "MANDATORY"}
  ],
  "target_databases": ["pubmed", "semantic_scholar"],
  "date_range": [2015, 2025],
  "language_restrictions": ["en"]
}
```

See `example_protocol.json` for a complete example.

**Use as a library:**

```python
import asyncio
from main import load_protocol
from infrastructure.encoder import SharedEncoderService
from infrastructure.llm_client import LLMClient
from orchestrators.main_orchestrator import MainOrchestrator

protocol   = load_protocol("my_protocol.json")
encoder    = SharedEncoderService()
llm_client = LLMClient()

result = asyncio.run(
    MainOrchestrator(encoder, llm_client, review_id="my_review").run(protocol)
)

print(f"Included: {len(result.included)}")
```

## Outputs

All outputs are written to `--output-dir` (default: `data/reports/`):

| File | Contents |
|---|---|
| `prisma_flow.md` | PRISMA 2020 flow diagram (Markdown table) |
| `prisma_flow.json` | Machine-readable PRISMA stage counts |
| `review_report.md` | Full structured review report with LLM-generated background and conclusion |
| `review_report.json` | Included study list, PRISMA counts, review metadata |
| `audit_trail.json` | All LLM decisions by stage, model versions, timestamps |

Full-text documents are cached under `data/reviews/<review_id>/documents/`.

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
# Head-to-head numerical evaluation (CASCADE-RC vs baselines)
python run_comparative.py

# Generate publication figures
python generate_graphs.py
```

## Web Frontend

```bash
uvicorn frontend.server:app --reload --port 8000
```

Opens the single-page review dashboard at `http://localhost:8000`. All API credentials must be set in `.env`.

## Testing

```bash
# Protocol parsing unit tests (no network or GPU required)
pytest tests/test_end_to_end.py::TestProtocolLoading -v

# Full acceptance test (requires live API credentials and GPU)
pytest tests/test_end_to_end.py::TestEndToEnd -v

# All tests
pytest tests/ -v
```

The acceptance test (`TestEndToEnd`) runs the complete pipeline with `MAX_PAPERS_PER_DB=50`, then asserts:
- At least one candidate was retrieved (search is alive)
- `records_screened > 0` in the PRISMA state (screening ran)
- `prisma_flow.md`, `review_report.md`, and both JSON files were written

## Configuration

All thresholds live in `config/settings.py` and can be overridden via environment variables:

| Constant | Default | Description |
|---|---|---|
| `INCLUDE_THRESHOLD` | `0.70` | Minimum `p_include` to include a record |
| `EXCLUDE_THRESHOLD` | `0.25` | Maximum `p_include` before hard exclusion |
| `DEDUP_THRESHOLD` | `0.95` | Title similarity ratio for deduplication |
| `MAX_PAPERS_PER_DB` | `500` | Per-database retrieval cap |
| `TIER1_TOKEN_LIMIT` | `3 000` | Token ceiling for LLM full-text screening |
| `TIER2_TOKEN_LIMIT` | `12 000` | Token ceiling for embedding screening |
| `SPAN_VERIFY_THRESHOLD` | `0.15` | Max Levenshtein distance for quote verification |
| `HALLUCINATION_PENALTY` | `0.30` | Score multiplier when a quote cannot be verified |
| `PICO_ALIGNMENT_THRESHOLD` | `0.60` | Minimum cosine similarity for PICO cross-validation |
| `RAG_TOKEN_BUDGET` | `1 500` | Token budget per RAG evidence window |
| `MAX_SEARCH_ITERATIONS` | `3` | Maximum iterative search refinement rounds |

## Key Design Decisions

**Recall-safe defaults.** Parse failures default to `UNCERTAIN` rather than `EXCLUDE`. All LLM classification calls use `temperature=0.0`.

**Noisy-OR aggregation.** Per-criterion inclusion probabilities are fused as `p = 1 − ∏(1 − pⱼ)` so that independent evidence from multiple criteria compounds correctly.

**Three-tier full-text routing.** Documents are routed by token count: LLM direct (< 3 000 tokens), embedding cross-attention (3 000–12 000), or RAG (> 12 000). This keeps LLM costs proportional to document length.

**Hallucination guard.** Every LLM-cited evidence span is verified by sliding-window Levenshtein match against the source text. Unverified quotes incur a 0.30× score penalty.

**F2 evaluation metric.** The `ReviewEvaluator` reports F2 = 5·P·R / (4P + R) rather than F1, treating recall as four times more important than precision — consistent with systematic review methodology where missed studies are more harmful than false positives.
