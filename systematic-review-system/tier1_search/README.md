# Tier 1 — Literature Search

Tier 1 retrieves candidate records from multiple bibliographic databases and deduplicates them before passing results to Tier 2 screening.

## Modules

| File | Purpose |
|---|---|
| `query_builder.py` | Builds Boolean PubMed/S2 queries from a `ReviewProtocol`. Prefers `LLMQueryBuilder` (PICO → concept-block decomposition via LLM); falls back to rule-based `QueryBuilder` if the LLM call fails. |
| `pubmed_connector.py` | Queries PubMed via NCBI E-utilities (Biopython Entrez). Respects `PUBMED_API_KEY` / `PUBMED_EMAIL` from `.env`. Returns `List[CandidateRecord]`. |
| `semantic_scholar_connector.py` | Queries Semantic Scholar Academic Graph API. Optional `SEMANTIC_SCHOLAR_API_KEY` raises rate limits. |
| `database_connector.py` | Orchestrates parallel queries across all active connectors and merges results. |
| `deduplication.py` | Removes duplicate records by DOI, PMID, and fuzzy title similarity. |
| `coverage_analyzer.py` | Post-search diagnostic: computes recall against any known gold-standard set (used during development/evaluation). |
| `search_refinement.py` | Iterative query refinement loop — re-runs `query_builder` if initial recall is too low. |

## Data flow

```
ReviewProtocol → QueryBuilder → [PubMed, Semantic Scholar] → DatabaseConnector
  → deduplication → List[CandidateRecord] → Tier 2
```

## Environment variables required

```
PUBMED_API_KEY=       # optional — raises rate limit 3→10 req/s
PUBMED_EMAIL=         # required by NCBI policy
SEMANTIC_SCHOLAR_API_KEY=  # optional
```
