# Tier 3 — Evidence Synthesis

Tier 3 processes studies that passed full screening and produces the final systematic review outputs: structured data extraction, methodological quality assessment, aggregate evidence synthesis, and PRISMA reporting.

> **Why two Tier 3 folders?**
> `tier3_synthesis/` contains the full LLM-driven synthesis workflow. `tier3_quality/` is a separate, standalone utility for rendering the PRISMA 2020 SVG flow diagram — it has no LLM dependency and can be called independently from any pipeline stage (including directly from `main.py`) without importing the rest of the synthesis stack. Keeping it separate avoids a circular import between the PRISMA reporter and the visual renderer, and makes the diagram generator reusable outside the full review context.

## Modules

| File | Purpose |
|---|---|
| `data_extractor.py` | Structured data extraction from included full-text documents. One LLM call per standard field (`sample_size`, `study_design`, `population_description`, `intervention_description`, `primary_outcome`, `follow_up`). Fields are extracted concurrently; evidence spans are verified with `SpanVerifier`. |
| `quality_assessor.py` | Methodological quality and risk-of-bias assessment. Auto-detects study design: RCTs → Cochrane RoB 2 (5 domains); observational studies → simplified NOS (3 domains). Overall judgment: `low` / `some_concerns` / `high`. |
| `review_evaluator.py` | Evaluation utilities: computes search completeness, screening accuracy, and PRISMA compliance. Validates that all required PRISMA flow counts are present and internally consistent. |
| `prisma_reporter.py` | Assembles the final structured review report (JSON + Markdown) and PRISMA flow counts from all upstream stages. Calls `tier3_quality.prisma_visual` to embed the SVG diagram. |

## Data flow

```
List[ScreeningDecision] + full-text documents
  → DataExtractor (per-field LLM, concurrent)
  → QualityAssessor (RoB 2 or NOS)
  → ReviewEvaluator (PRISMA compliance check)
  → PRISMAReporter → review_report.json + prisma_flow.json + SVG diagram
```
