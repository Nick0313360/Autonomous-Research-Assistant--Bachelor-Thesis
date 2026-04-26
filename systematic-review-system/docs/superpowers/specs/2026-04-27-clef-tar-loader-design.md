# CLEF-TAR 2019 Benchmark Ingestion — Design Spec

**Date:** 2026-04-27  
**Branch:** feature_redesignv2  
**Scope:** Add a parallel benchmark data path for validating CASCADE-RC on CLEF-TAR 2019 (Kanoulas et al., 2019). Does NOT touch the live Tier 1 pipeline.

---

## Context

CASCADE-RC requires validation against a gold-standard benchmark. CLEF-TAR 2019 provides per-topic Boolean queries, candidate PMIDs, and binary relevance judgments at abstract and full-text level. We use **abstract-level** qrels. Three DTA (Diagnostic Test Accuracy) topics are in scope: CD008874, CD012080, CD012768 — all confirmed to have ≥26 positives (N_min for α=0.10, δ_LTT=0.07).

Confirmed positive counts from `full.test.dta.abs.2019.qrels`:
- CD008874: 118 positives / 2264 negatives / 2382 total
- CD012080: 77 positives / 6566 negatives / 6643 total
- CD012768: 45 positives / 86 negatives / 131 total

---

## File Layout

```
systematic-review-system/
├── cascade_rc/
│   ├── __init__.py                  (empty)
│   └── data/
│       ├── __init__.py              (empty)
│       └── clef_tar_loader.py       (main deliverable)
├── tests/
│   └── test_clef_tar_loader.py
└── requirements.txt                 (add: pandas>=2.0, pyarrow>=14.0)
```

No changes to `tier1_search/`, `tier2_screening/`, orchestrators, or models.

---

## CLEF-TAR 2019 Data Layout (on disk after download)

```
<data_dir>/2019-TAR/Task2/Testing/DTA/
    topics/
        CD008874        ← text file: Title, Query (multi-line), Pids
        CD012080
        CD012768
    qrels/
        full.test.dta.abs.2019.qrels   ← "<topic_id> 0 <pmid> <relevance>\n"
```

Source repo: https://github.com/CLEF-TAR/tar  
Download method: `git sparse-checkout set "2019-TAR"` with `--filter=blob:none` (sparse clone, ~100KB vs ~50MB full repo).

---

## Public API

### `Topic` dataclass

```python
@dataclass
class Topic:
    topic_id: str
    title: str
    boolean_query: str               # raw multi-line MeSH/Boolean string
    candidate_pmids: list[str]       # from Pids: section of topic file
    qrels_abstract: dict[str, int]   # pmid → 0|1, from full.test.dta.abs qrels
```

Defined at module level in `clef_tar_loader.py`. Not added to `models/data_classes.py` (benchmark-specific, no downstream consumers yet).

### `download_clef_tar_2019(target_dir: Path) -> None`

- If `target_dir/2019-TAR` already exists: no-op (idempotent).
- Otherwise: runs `git clone --depth=1 --filter=blob:none --sparse <repo_url> <tmp>`, then `git sparse-checkout set "2019-TAR"`, moves `2019-TAR/` into `target_dir`.
- Raises `RuntimeError` with subprocess stderr if git fails.
- Uses `subprocess.run(..., check=True)` — no shell=True.

### `load_topic(topic_id: str, data_dir: Path) -> Topic`

- Validates `topic_id ∈ {"CD008874", "CD012080", "CD012768"}` → `ValueError` otherwise.
- Raises `FileNotFoundError` if `data_dir/2019-TAR` doesn't exist.
- Parses topic file line-by-line:
  - `Title: ...` → `title` (single line after the tag)
  - `Query:` → collect lines until `Pids:` → `boolean_query`
  - `Pids:` → collect stripped integers → `candidate_pmids`
- Reads `full.test.dta.abs.2019.qrels`, filters rows where column 0 == `topic_id` → `qrels_abstract`.
- Qrels row format: 4 whitespace-separated columns — `topic_id iter pmid relevance`.

### `fetch_abstracts(pmids: list[str], cache_dir: Path) -> dict[str, dict]`

- Loads `cache_dir/abstracts.jsonl` (one JSON object per line, keyed by `pmid`).
- For PMIDs not in cache: instantiates `PubMedConnector()` (sets `Entrez.email` + `Entrez.api_key` from env), then calls `Entrez.efetch(db="pubmed", id=chunk, rettype="medline", retmode="text")` in chunks of 500.
- Parses each MEDLINE record: extracts `TI` → `title`, `AB` → `abstract`, `PMID` → `pmid`.
- Appends new records to `cache_dir/abstracts.jsonl`.
- Returns `{pmid: {"title": str, "abstract": str}}` for all requested PMIDs that returned a non-empty title. PMIDs with no abstract or no title are excluded from the returned dict (not from the cache).
- `cache_dir` is created if absent.

---

## Data Flow

```
download_clef_tar_2019(target_dir)
    └─ sparse-clone → target_dir/2019-TAR/Task2/Testing/DTA/{topics,qrels}/

load_topic(topic_id, data_dir)
    ├─ parse topic file  → title, boolean_query, candidate_pmids
    ├─ parse qrels file  → qrels_abstract {pmid → 0|1}
    └─ return Topic

fetch_abstracts(pmids, cache_dir)
    ├─ load cache (abstracts.jsonl)
    ├─ efetch uncached PMIDs via PubMedConnector credential setup
    ├─ append to cache
    └─ return {pmid → {title, abstract}}

CLI  (python -m cascade_rc.data.clef_tar_loader --topic <id> --out <dir>)
    ├─ for each topic:
    │   ├─ load_topic(topic_id, out_dir)
    │   ├─ fetch_abstracts(topic.candidate_pmids, out_dir/cache)
    │   ├─ inner-join: pmid ∈ qrels_abstract AND in fetch result
    │   │   (drops PMIDs with no abstract/title OR no qrels entry)
    │   ├─ write out_dir/<topic_id>.parquet
    │   │   columns: pmid (str), title (str), abstract (str), y_abstract (int8)
    │   └─ print summary stats
    └─ exit 0
```

---

## CLI

```
python -m cascade_rc.data.clef_tar_loader \
    --topic CD008874 \
    --out data/clef_tar/
```

Arguments:
- `--topic`: one or more topic IDs (repeatable; defaults to all three if omitted)
- `--out`: output directory for parquet files and abstract cache
- `--data-dir`: directory containing the downloaded `2019-TAR/` tree (defaults to `--out`)
- `--skip-download`: skip `download_clef_tar_2019` (use if data already present)

Summary stats printed per topic (to stdout):
```
CD008874  total=2382  pos=118  neg=2264  prevalence=0.0496
```

---

## Output Parquet Schema

| column     | dtype  | notes                        |
|------------|--------|------------------------------|
| pmid       | str    | PubMed ID                    |
| title      | str    | non-empty                    |
| abstract   | str    | non-empty                    |
| y_abstract | int8   | 0 or 1 (binary qrel)         |

One file per topic: `<out_dir>/CD008874.parquet`, etc.

---

## Tests (`tests/test_clef_tar_loader.py`)

Three parametrized integration tests over `["CD008874", "CD012080", "CD012768"]`. Each test loads `data/clef_tar/<topic_id>.parquet` (relative to repo root); skips with `pytest.skip` if the file is absent.

| test | assertion |
|------|-----------|
| `test_minimum_positives` | `df["y_abstract"].sum() >= 26` |
| `test_no_empty_title_or_abstract` | all rows: `title != ""` and `abstract != ""` |
| `test_y_abstract_binary` | `set(df["y_abstract"]) ⊆ {0, 1}` |

No mocking — tests exercise the real output parquet.

---

## Dependencies Added

```
pandas>=2.0
pyarrow>=14.0
```

Added to `systematic-review-system/requirements.txt`. Neither was previously installed.

---

## Constraints

- Temperature=0.0 / LLM rules do not apply — no LLM calls in this module.
- No hardcoded API keys — `PubMedConnector` reads from `.env` via `python-dotenv`.
- All functions have type hints.
- `fetch_abstracts` is synchronous (matches MEDLINE parse pattern in `PubMedConnector`).
