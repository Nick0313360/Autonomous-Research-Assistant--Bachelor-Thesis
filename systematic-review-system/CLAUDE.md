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
- SQLite via sqlite3 (DecisionLogger)
- dataclasses for all data models

## Rules
- Every function must have type hints
- Every decision-making component writes a DecisionRecord
- All LLM calls go through LLMClient, never direct
- Temperature=0.0 for all classification decisions
- Parse failures always default to UNCERTAIN (recall-safe)
- Use async/await for all LLM calls
- No hardcoded API keys — use python-dotenv

## Models
- LLM-1 (fast, bulk):** `gpt-oss:120b` (via BFH internal endpoint)
- LLM-2 (strong, reasoning): claude-sonnet-4-6
- Embeddings: allenai/specter2_base via sentence-transformers

## BFH Internal Model Configuration
- **Endpoint:** `https://inference.mlmp.ti.bfh.ch/api/v1`
- **Model name:** `gpt-oss:120b`
- **API format:** OpenAI-compatible

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
