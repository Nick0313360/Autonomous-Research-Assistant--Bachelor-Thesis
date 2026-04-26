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