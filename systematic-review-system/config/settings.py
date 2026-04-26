"""
config/settings.py
==================
Central configuration for the autonomous systematic review system.
Credentials are read from environment variables via python-dotenv.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Credentials (read from .env)
# ---------------------------------------------------------------------------
OPENAI_API_KEY:           str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL:          str = os.getenv("OPENAI_BASE_URL", "https://inference.mlmp.ti.bfh.ch/api/v1")
OPENAI_MODEL:             str = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
PUBMED_API_KEY:           str = os.getenv("PUBMED_API_KEY", "")
PUBMED_EMAIL:             str = os.getenv("PUBMED_EMAIL", "")
SEMANTIC_SCHOLAR_API_KEY: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
UNPAYWALL_EMAIL:          str = os.getenv("UNPAYWALL_EMAIL", "")
ANTHROPIC_API_KEY:        str = os.getenv("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
DEDUP_THRESHOLD:  float = 0.95   # Levenshtein ratio for title dedup
MAX_PAPERS_PER_DB: int  = 500

# ---------------------------------------------------------------------------
# Screening thresholds
# ---------------------------------------------------------------------------
INCLUDE_THRESHOLD: float = 0.70
EXCLUDE_THRESHOLD: float = 0.25
UNCERTAIN_P:       float = 0.50

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
RRF_CONSTANT:            int   = 60
MIN_RETRIEVAL_RRF_SCORE: float = 0.01
EMBED_DIM_ABSTRACT:      int   = 128
EMBED_DIM_SECTION:       int   = 256
EMBED_BATCH_SIZE:        int   = 32

# ---------------------------------------------------------------------------
# Search pipeline
# ---------------------------------------------------------------------------
MAX_SEARCH_ITERATIONS:  int   = 3
SATURATION_THRESHOLD:   float = 0.05
KEYWORD_MIN_FRACTION:   float = 0.05

# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
ABSTRACT_SCREENER_CONCURRENCY:  int = 20
FULLTEXT_SCREENER_CONCURRENCY:  int = 5
FULLTEXT_RETRIEVER_CONCURRENCY: int = 5
LLM_BATCH_CONCURRENCY:          int = 10

# ---------------------------------------------------------------------------
# Full-text screening tier boundaries (token count)
# ---------------------------------------------------------------------------
TIER1_TOKEN_LIMIT: int = 3_000
TIER2_TOKEN_LIMIT: int = 12_000

# ---------------------------------------------------------------------------
# Span verification
# ---------------------------------------------------------------------------
SPAN_VERIFY_THRESHOLD: float = 0.15
HALLUCINATION_PENALTY: float = 0.30

# ---------------------------------------------------------------------------
# Example buffer
# ---------------------------------------------------------------------------
EXAMPLE_BUFFER_CONFIDENCE_GATE: float = 0.90
EXAMPLE_BUFFER_TOP_K:           int   = 3

# ---------------------------------------------------------------------------
# PICO alignment
# ---------------------------------------------------------------------------
PICO_ALIGNMENT_THRESHOLD: float = 0.60
PICO_MISMATCH_PENALTY:    float = 0.80

# ---------------------------------------------------------------------------
# CriterionAwareRAG
# ---------------------------------------------------------------------------
RAG_TOP_K:        int = 5
RAG_TOKEN_BUDGET: int = 1_500

# ---------------------------------------------------------------------------
# Quality assessment
# ---------------------------------------------------------------------------
ROB2_TOOL: str = "rob2"
NOS_TOOL:  str = "nos"
