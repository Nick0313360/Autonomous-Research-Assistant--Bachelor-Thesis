# Tier 2 — Screening

Tier 2 screens candidates in two stages — abstract-level and full-text — and routes certified topics through the CASCADE-RC certified screening pipeline.

## Modules

| File | Purpose |
|---|---|
| `abstract_screener.py` | Per-criterion LLM screening at abstract level. Applies Noisy-OR fusion over mandatory inclusion criteria; thresholds at ≥0.70 (INCLUDE) / ≤0.25 (EXCLUDE). Runs up to 20 candidates concurrently via `asyncio.Semaphore`. |
| `fulltext_screener.py` | Full-text screening for candidates that passed abstract screening. Retrieves PDFs via Unpaywall, parses with `pdfminer`, and re-applies criterion-level LLM calls against the full document. |
| `fulltext_retriever.py` | Fetches open-access PDFs via the Unpaywall API. Falls back to publisher page scraping where available. |
| `document_parser.py` | Extracts structured text from PDFs using `pdfminer.six`. |
| `cascade_rc_router.py` | Routes topics through CASCADE-RC certified screening when a calibrated certificate exists. Uses tier1 scores (`s`) and LLM self-consistency scores (`u`) to assign records to tier1-pass, tier2-review, or human-review buckets via the three-threshold decision boundary (λ_lo, λ_hi, τ_SE). |
| `pico_extractor.py` | Extracts Population, Intervention, Comparator, Outcome fields from a protocol using an LLM call. |
| `hybrid_retriever.py` | Combines BM25 sparse retrieval and SPECTER2 dense retrieval for criterion-aware RAG examples. |
| `criterion_aware_rag.py` | Retrieves few-shot examples per inclusion criterion from the hybrid index to improve screening accuracy. |
| `example_buffer.py` | Manages the in-memory pool of labelled examples used by criterion-aware RAG. |
| `decision_engine.py` | Final decision arbiter: merges abstract and full-text decisions, applies override rules (e.g. language exclusion), and emits a `ScreeningDecision`. |
| `span_verifier.py` | Verifies that evidence spans cited by the LLM actually appear verbatim in the source document. |

## Data flow

```
List[CandidateRecord]
  → AbstractScreener (LLM per criterion, Noisy-OR)
  → [CascadeRCRouter if certified] or [FulltextScreener]
  → DecisionEngine
  → List[ScreeningDecision] → Tier 3
```

## CASCADE-RC routing

If a calibrated certificate exists for the review topic (produced by `cascade_rc/calibration/`), the `CascadeRCRouter` bypasses manual full-text screening for records that fall clearly inside or outside the certified inclusion boundary, sending only uncertain records to full human review. See [`cascade_rc/README.md`](../cascade_rc/README.md) for details.
