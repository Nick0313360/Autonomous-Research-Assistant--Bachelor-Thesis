# Project: Autonomous Systematic Review System

## Stack
- Python 3.11
- anthropic SDK (claude-haiku-4-5 for LLM-1, claude-sonnet-4-6 for LLM-2)
- sentence-transformers (SPECTER2)
- faiss-cpu
- rank-bm25
- grobid-client-python
- pdfminer.six
- asyncio for concurrency
- SQLite via sqlite3 (SQLiteEnsembleCache — see LLM Cache below)
- dataclasses for all data models

## Rules
- Every function must have type hints
- All LLM calls go through LLMClient, never direct
- Temperature=0.0 for all classification decisions
- Parse failures always default to UNCERTAIN (recall-safe)
- Use async/await for all LLM calls
- No hardcoded API keys — use python-dotenv

## Models
- LLM-1 (fast, bulk):** `gpt:oss120b` (via BFH internal endpoint)
- LLM-2 (strong, reasoning): claude-sonnet-4-6
- Embeddings: allenai/specter2_base via sentence-transformers

## BFH Internal Model Configuration
- **Endpoint:** `https://inference.mlmp.ti.bfh.ch/api/v1`
- **Model name:** `gpt:oss120b`
- **API format:** OpenAI-compatible

## LLM Cache Architecture
All LLM screening decisions (Step 3 ensemble votes) are stored in:

    artefacts/cascade_rc/llm_cache.db

The cache is managed by `SQLiteEnsembleCache` (`cascade_rc/cache/sqlite_cache.py`).
The `llm_calls` table stores one row per (model_id, prompt_sha, pmid, temperature, seed_b, template_v).
`prompt_sha` is a SHA-256 of the **full, untruncated** prompt text (title + full abstract + PICO text).

There is **no** `DecisionLogger` class and **no** `decisions.db` file — those were stale documentation artifacts.

### SHA stability contract
Step 3 (`step_score_u`) and Step 4 (`step_merge_u`) must compute identical `prompt_sha` values:
- Use the **full abstract** (never `abstract[:N]`) when building the prompt.
- Use the same PICO text — both steps load PICO via `_load_pico()` from `{topic_id}_protocol.json`.
- Breaking either invariant causes a SHA mismatch → cache miss → `u` falls back to `s` → `θ̂ = 0.0`.


## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
