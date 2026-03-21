# Module 1 — Test Suite

## Structure

```
tests/
├── fixtures.py            ← All test data: query catalogue, golden standard, refiner cases
├── test_unit.py           ← Pure logic tests (no network, < 5 seconds)
├── test_integration.py    ← Real API tests (PubMed + S2, marked integration)
└── results/               ← Auto-generated JSON results (created on first run)
    ├── golden_standard_recall.json
    ├── stress_pubmed_max.json
    ├── stress_s2_max.json
    └── stress_pipeline_dedup.json
pytest.ini                 ← Marker definitions and run config
```

---

## Step 1 — Install test dependencies

```bash
pip install pytest rapidfuzz
```

---

## Step 2 — Run unit tests first (always, no API needed)

```bash
pytest tests/test_unit.py -v
```

Expected: **all green**, runs in < 10 seconds.  
These tests cover: SearchQuery validation, QueryBuilder output, deduplicator,
domain validator (regression for the "robotics" bug), query expansion, paper key identity.

---

## Step 3 — Run integration tests (require real API keys in `.env`)

Make sure your `.env` has:
```
SEMANTIC_SCHOLAR_API_KEY=your_key_here
```

### All integration tests:
```bash
pytest tests/test_integration.py -v -m integration
```

### Only PubMed:
```bash
pytest tests/test_integration.py -v -m pubmed
```

### Only Semantic Scholar:
```bash
pytest tests/test_integration.py -v -m semantic
```

### Golden standard recall test (thesis validation):
```bash
pytest tests/test_integration.py -v -m recall
```
This runs Module 1 against the Van Dinter et al. (2021) query and measures
what % of their 52 known included papers we retrieve.  
Results are saved to `tests/results/golden_standard_recall.json`.

### Stress test (max papers, timing):
```bash
pytest tests/test_integration.py -v -m stress
```
Tests at 1000 papers/DB. Takes ~2 minutes. Run once before thesis submission.

---

## Step 4 — Full suite (skip stress)

```bash
pytest tests/ -v -m "not stress"
```

---

## What the results mean for your thesis

### Unit tests
All green = the query-building logic is correct and all edge cases are handled.
Include the pytest output as an appendix.

### Golden standard recall
The result in `tests/results/golden_standard_recall.json` gives you:
- `recall` — the % of Van Dinter's papers Module 1 found
- `found_papers` / `not_found_papers` — exact list for PRISMA documentation
- `verdict` — EXCELLENT / ACCEPTABLE / BELOW TARGET

**Expected recall:** 40–70% (we use 2 databases, Van Dinter used 4).  
**How to cite in thesis:** "Module 1 achieved X% recall against the ground-truth  
set of Van Dinter et al. (2021), who searched 4 databases. The lower bound is  
expected given our 2-database configuration."

### Dedup rate (stress test)
The `dedup_rate` in `stress_pipeline_dedup.json` directly feeds into your  
PRISMA flow diagram's "records removed after deduplication" box.

---

## Query fixture catalogue

`tests/fixtures.py` contains 13 test queries across 4 categories:

| ID    | Category              | Purpose                                      |
|-------|-----------------------|----------------------------------------------|
| Q001  | valid_full_pico       | Thesis main query                            |
| Q002  | valid_full_pico       | Stress detection in clinical notes           |
| Q003  | valid_full_pico       | Van Dinter golden standard query             |
| Q004  | valid_minimal         | Research question only (no PICO)             |
| Q005  | valid_full_pico       | Year-range filter                            |
| Q006  | valid_full_pico       | Small limit (50) enforcement                 |
| Q007  | valid_full_pico       | Max limit (1000) enforcement                 |
| Q101  | invalid_empty_rq      | Empty research question → must raise         |
| Q102  | invalid_empty_rq      | Whitespace-only → must raise                 |
| Q103  | invalid_limit         | Limit = 0 → must raise                       |
| Q104  | invalid_limit         | Limit > 1000 → must raise                    |
| Q105  | invalid_year_range    | Inverted year range → must raise             |
| Q201  | edge_very_long_pico   | 50 synonyms → must truncate gracefully       |
| Q202  | edge_special_chars    | Special chars in query → must not crash      |
| Q203  | edge_single_word      | Single-word research question                |
| Q204  | edge_non_english      | Non-English query → must not crash           |
| Q205  | edge_generic_outcome  | Generic outcome terms → dropped from S2      |