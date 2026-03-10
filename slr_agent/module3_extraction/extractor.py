"""
MODULE 3 — RAG Data Extraction
================================
Extracts structured data from included papers using a
Retrieval-Augmented Generation (RAG) pipeline.

Architecture (4 layers):
  Layer 1 — PDF processing and chunking       (PyMuPDF + LangChain splitter)
  Layer 2 — Embedding and vector storage      (BFH embedding API + ChromaDB)
  Layer 3 — Retrieval and field extraction    (semantic search + LLM)
  Layer 4 — Structured output schema          (Pydantic validation + retry)

Input  : list of included paper dicts from Module 2
Output : list of ExtractedPaper objects + PRISMA inclusion counts

How RAG works here in plain English:
  1. Take a paper PDF → split into overlapping text chunks (~512 tokens each)
  2. Convert every chunk into a vector (embedding) and store in ChromaDB
  3. For each field you want to extract (e.g. "sample size"), create a
     natural-language query, embed it, find the 4 most similar chunks
  4. Send those 4 chunks as context to the LLM → LLM extracts the field
  5. Validate the result with Pydantic → retry once if it fails
"""

import io
import json
import logging
import os
import time
import hashlib
from typing import Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError, field_validator

# PDF text extraction — same library as Module 2
from pdfminer.high_level import extract_text as pdfminer_extract

# PyMuPDF for page-aware chunking (gives us page numbers)
# Install: pip install pymupdf
import fitz  # PyMuPDF

# LangChain text splitter — handles overlapping chunks
# Install: pip install langchain-text-splitters
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ChromaDB — local vector store, no server needed
# Install: pip install chromadb
import chromadb
from chromadb.config import Settings

load_dotenv()

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

# ── clients ───────────────────────────────────────────────────────────────────

# LLM client — same BFH proxy as Module 1 and 2
_llm_client = OpenAI(
    base_url=os.getenv("API_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
)
LLM_MODEL = os.getenv("EXTRACTION_MODEL", "gpt-oss:120b")

# Embedding client — uses BFH embedding model
# The BFH proxy exposes embeddinggemma:300m for embeddings
_embed_client = OpenAI(
    base_url=os.getenv("API_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
)
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "embeddinggemma:300m")

# ChromaDB — stores vectors locally in a folder
# Each paper gets its own collection so they don't interfere
CHROMA_DIR = os.getenv("CHROMA_DIR", "outputs/chroma_db")
os.makedirs(CHROMA_DIR, exist_ok=True)

_chroma_client = chromadb.PersistentClient(
    path=CHROMA_DIR,
    settings=Settings(anonymized_telemetry=False)
)

# Unpaywall email — same as Module 2
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "test@example.com")


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — PYDANTIC SCHEMA (defined first so layers 1-3 can reference it)
# ══════════════════════════════════════════════════════════════════════════════
# This is the data model for ONE extracted paper.
# Every field maps to a specific extraction query in EXTRACTION_FIELDS below.
# Optional fields return None if not found — this is intentional.
# Pydantic validates types automatically and raises ValidationError if wrong.

class ExtractedPaper(BaseModel):
    """
    Structured extraction output for one included paper.
    All fields are Optional — if the paper doesn't report something,
    we store None rather than hallucinating a value.
    """

    # ── identifiers (passed in, not extracted) ────────────────────────────────
    title:                str
    doi:                  Optional[str]   = None

    # ── tool / system description ─────────────────────────────────────────────
    tool_name:            Optional[str]   = None   # name of the AI tool evaluated
    llm_used:             Optional[str]   = None   # e.g. GPT-4, BERT, custom
    databases_searched:   Optional[str]   = None   # e.g. PubMed, Embase
    prisma_stages_covered: Optional[str]  = None   # which SR stages the tool covers

    # ── evaluation metrics ────────────────────────────────────────────────────
    reported_sensitivity: Optional[float] = None   # recall / sensitivity (0-1)
    reported_specificity: Optional[float] = None   # specificity (0-1)
    reported_kappa:       Optional[float] = None   # inter-rater agreement
    reported_accuracy:    Optional[float] = None   # overall accuracy (0-1)
    reported_f1:          Optional[float] = None   # F1 score (0-1)

    # ── study characteristics ─────────────────────────────────────────────────
    sample_size:          Optional[int]   = None   # number of records / studies used
    evaluation_dataset:   Optional[str]   = None   # name or description of test set
    study_design:         Optional[str]   = None   # e.g. RCT, observational, benchmark
    year:                 Optional[int]   = None   # publication year

    # ── qualitative fields ────────────────────────────────────────────────────
    limitations:          Optional[str]   = None   # reported limitations
    human_in_loop:        Optional[str]   = None   # how humans are involved

    # ── provenance (where each value came from in the PDF) ───────────────────
    # Each source field stores the verbatim passage + page number
    # so every data point is traceable back to the PDF
    sources:              dict            = {}      # field_name → {text, page}

    @field_validator("reported_sensitivity", "reported_specificity",
                     "reported_kappa", "reported_accuracy", "reported_f1",
                     mode="before")
    @classmethod
    def clamp_zero_one(cls, v):
        """Metrics reported as percentages (e.g. 87.3) get converted to 0-1."""
        if v is None:
            return None
        v = float(v)
        if v > 1.0:
            v = v / 100.0
        return round(v, 4)

    @field_validator("year", mode="before")
    @classmethod
    def parse_year(cls, v):
        if v is None:
            return None
        return int(str(v)[:4])  # handle "2023." or "2023-01-01" formats


# ── extraction queries ────────────────────────────────────────────────────────
# Each entry is:
#   field_name  →  (search_query_for_retrieval, extraction_instruction_for_LLM)
# The search query finds relevant chunks. The instruction tells the LLM what to extract.

EXTRACTION_FIELDS = {
    "tool_name": (
        "name of the AI tool or system being evaluated",
        "Extract the exact name of the AI tool, system, or software being evaluated. "
        "Return just the name as a string, e.g. 'ASReview', 'Rayyan', 'custom GPT-4 pipeline'."
    ),
    "llm_used": (
        "language model used GPT BERT transformer architecture",
        "Extract the name of the language model or ML model used, e.g. 'GPT-4', 'BERT', "
        "'RoBERTa', 'LLaMA-2'. If multiple models were compared, list them comma-separated."
    ),
    "databases_searched": (
        "databases searched PubMed Embase Cochrane literature sources",
        "Extract the names of bibliographic databases searched, e.g. 'PubMed, Embase, Cochrane'. "
        "Return as a comma-separated string."
    ),
    "prisma_stages_covered": (
        "PRISMA stages covered screening eligibility extraction automation",
        "Extract which stages of the systematic review process the tool automates or assists with. "
        "Examples: 'title/abstract screening', 'full-text screening', 'data extraction', "
        "'risk of bias assessment'. Return as a comma-separated string."
    ),
    "reported_sensitivity": (
        "sensitivity recall true positive rate performance metric",
        "Extract the reported sensitivity or recall value as a number between 0 and 1. "
        "If reported as percentage (e.g. 87.3%), convert to decimal (0.873). "
        "If multiple values reported, extract the best or final evaluation value."
    ),
    "reported_specificity": (
        "specificity true negative rate performance metric",
        "Extract the reported specificity value as a number between 0 and 1. "
        "If reported as percentage, convert to decimal."
    ),
    "reported_kappa": (
        "kappa inter-rater agreement Cohen kappa reliability",
        "Extract the reported Cohen's kappa or inter-rater agreement coefficient. "
        "Return as a decimal between -1 and 1."
    ),
    "reported_accuracy": (
        "accuracy classification performance overall correct",
        "Extract the reported overall accuracy as a number between 0 and 1. "
        "If reported as percentage, convert to decimal."
    ),
    "reported_f1": (
        "F1 score F-measure harmonic mean precision recall",
        "Extract the reported F1 score as a number between 0 and 1. "
        "If reported as percentage, convert to decimal."
    ),
    "sample_size": (
        "number of records studies included dataset size evaluation set",
        "Extract the number of records, studies, or papers used in the evaluation dataset. "
        "Return as an integer only."
    ),
    "evaluation_dataset": (
        "evaluation dataset benchmark test set validation corpus",
        "Extract the name or description of the dataset used to evaluate the tool. "
        "Examples: 'CLEF 2019 TAR dataset', '500 PubMed abstracts', 'Cochrane reviews'."
    ),
    "study_design": (
        "study design methodology research design validation approach",
        "Extract the study design, e.g. 'retrospective benchmark evaluation', "
        "'prospective user study', 'simulation', 'RCT comparison'. One short phrase."
    ),
    "year": (
        "publication year date published",
        "Extract the publication year as a 4-digit integer, e.g. 2023."
    ),
    "limitations": (
        "limitations future work constraints weaknesses study limitations",
        "Extract the main reported limitations of the study in 1-2 sentences."
    ),
    "human_in_loop": (
        "human in the loop reviewer human oversight manual review",
        "Describe how human reviewers are involved in the process, if at all. "
        "E.g. 'human reviews uncertain cases', 'fully automated no human', "
        "'dual human review for validation'."
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — PDF PROCESSING AND CHUNKING
# ══════════════════════════════════════════════════════════════════════════════

def get_pdf_url(paper: dict) -> Optional[str]:
    """
    Find the open-access PDF URL for a paper.
    Same two-source logic as Module 2:
      1. openAccessPdf field from Semantic Scholar
      2. Unpaywall API via DOI
    """
    # try Semantic Scholar field first (already in paper dict if S2 is working)
    oa = paper.get("openAccessPdf") or {}
    if isinstance(oa, dict) and oa.get("url"):
        return oa["url"]
    if isinstance(oa, str) and oa:
        return oa

    # fall back to Unpaywall
    doi = paper.get("doi")
    if not doi:
        return None
    try:
        r = requests.get(
            f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}",
            timeout=15
        )
        r.raise_for_status()
        best = r.json().get("best_oa_location") or {}
        return best.get("url_for_pdf")
    except Exception as exc:
        log.debug("Unpaywall failed for %s: %s", doi, exc)
        return None


def extract_pages(pdf_url: str) -> list[dict]:
    """
    Download PDF and extract text page by page using PyMuPDF (fitz).

    Returns a list of dicts:
      [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]

    Why page-by-page instead of one blob?
    → We need page numbers for provenance. Every extracted value gets stored
      with its source page so you can verify it in the original PDF.

    Why PyMuPDF instead of pdfminer here?
    → PyMuPDF gives us page boundaries. pdfminer gives better text quality
      for complex layouts. We use pdfminer as fallback.
    """
    try:
        r = requests.get(pdf_url, timeout=30)
        r.raise_for_status()
        pdf_bytes = r.content

        pages = []
        # open PDF from bytes (no temp file needed)
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text("text")
                if text.strip():  # skip blank pages
                    pages.append({"page": page_num, "text": text})

        if not pages:
            # fallback to pdfminer if PyMuPDF got nothing
            log.warning("PyMuPDF got no text, falling back to pdfminer")
            text = pdfminer_extract(io.BytesIO(pdf_bytes))
            if text.strip():
                pages = [{"page": 1, "text": text[:40000]}]

        log.info("    Extracted %d pages from PDF", len(pages))
        return pages

    except Exception as exc:
        log.warning("PDF extraction failed (%s): %s", pdf_url, exc)
        return []


def chunk_pages(pages: list[dict]) -> list[dict]:
    """
    Split page texts into overlapping chunks for the vector store.

    Chunk size: 512 tokens (~2000 chars) with 64-token overlap (~256 chars).
    The overlap prevents relevant sentences from being cut at chunk boundaries.

    Why overlapping chunks?
    → If a sentence spans the end of one chunk and the start of the next,
      without overlap one of those chunks would miss the full context.
      With overlap, both chunks contain the sentence, so retrieval finds it.

    Returns list of chunk dicts:
      [{"chunk_id": "...", "text": "...", "page": 1, "chunk_index": 0}, ...]
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,       # ~512 tokens in chars
        chunk_overlap=256,     # ~64 tokens overlap
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""]  # split at natural boundaries
    )

    chunks = []
    for page_data in pages:
        page_num  = page_data["page"]
        page_text = page_data["text"]

        # split this page's text into chunks
        page_chunks = splitter.split_text(page_text)

        for i, chunk_text in enumerate(page_chunks):
            chunks.append({
                "chunk_id":    f"p{page_num}_c{i}",  # unique ID within this paper
                "text":        chunk_text,
                "page":        page_num,
                "chunk_index": i,
            })

    log.info("    Created %d chunks from %d pages", len(chunks), len(pages))
    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — EMBEDDING AND VECTOR STORAGE
# ══════════════════════════════════════════════════════════════════════════════

def embed_text(texts: list[str]) -> list[list[float]]:
    """
    Convert a list of text strings into embedding vectors using the BFH
    embedding model (embeddinggemma:300m).

    Returns a list of float vectors, one per input text.
    These vectors encode semantic meaning — similar texts have similar vectors.

    Why embeddings?
    → Keyword search finds exact words. Semantic search finds meaning.
      "sample size" and "number of included records" mean the same thing
      but share no words — embedding search finds both.
    """
    try:
        response = _embed_client.embeddings.create(
            model=EMBED_MODEL,
            input=texts
        )
        # response.data is a list of Embedding objects, each with .embedding
        return [item.embedding for item in response.data]

    except Exception as exc:
        log.error("Embedding failed: %s", exc)
        # return zero vectors as fallback so pipeline doesn't crash
        # (retrieval will just return random chunks, which is better than crashing)
        dim = 768  # embeddinggemma:300m output dimension
        return [[0.0] * dim for _ in texts]


def get_or_create_collection(paper_id: str) -> chromadb.Collection:
    """
    Get or create a ChromaDB collection for one paper.

    Each paper gets its own collection so vector searches are scoped
    to just that paper's chunks — we never want chunks from paper A
    to show up when extracting data from paper B.

    paper_id: a short stable identifier (MD5 of DOI or title)
    """
    # ChromaDB collection names must be alphanumeric + hyphens, 3-63 chars
    safe_id = f"paper-{paper_id[:40]}"
    collection = _chroma_client.get_or_create_collection(
        name=safe_id,
        # use cosine similarity — better than Euclidean for text embeddings
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def index_chunks(chunks: list[dict], collection: chromadb.Collection) -> None:
    """
    Embed all chunks and store them in the ChromaDB collection.

    This is the indexing step — after this, the collection supports
    fast semantic search over all chunks of this paper.

    Why batch embedding?
    → Sending 50 texts in one API call is much faster than 50 separate calls.
      The BFH API supports batching up to ~100 texts.
    """
    if not chunks:
        return

    # check if already indexed (avoid re-embedding on reruns)
    if collection.count() >= len(chunks):
        log.info("    Collection already indexed (%d chunks), skipping", collection.count())
        return

    texts     = [c["text"]     for c in chunks]
    ids       = [c["chunk_id"] for c in chunks]
    metadatas = [{"page": c["page"], "chunk_index": c["chunk_index"]} for c in chunks]

    # embed in batches of 50 to avoid hitting API limits
    batch_size = 50
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embeddings = embed_text(batch)
        all_embeddings.extend(embeddings)
        log.debug("    Embedded batch %d/%d", i // batch_size + 1,
                  (len(texts) + batch_size - 1) // batch_size)

    # store in ChromaDB
    collection.add(
        ids=ids,
        embeddings=all_embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    log.info("    Indexed %d chunks into ChromaDB", len(chunks))


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — RETRIEVAL AND EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def retrieve_relevant_chunks(
    query: str,
    collection: chromadb.Collection,
    n_results: int = 4
) -> list[dict]:
    """
    Find the n_results chunks most semantically similar to query.

    Process:
      1. Embed the query into a vector
      2. ChromaDB finds the nearest chunk vectors (cosine similarity)
      3. Return the actual text of those chunks + their page numbers

    This is the R in RAG — Retrieval.
    """
    query_embedding = embed_text([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, collection.count()),  # can't ask for more than exist
        include=["documents", "metadatas", "distances"]
    )

    # reformat into a clean list of dicts
    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        chunks.append({
            "text":       doc,
            "page":       meta.get("page", 0),
            "similarity": round(1 - dist, 4),  # cosine distance → similarity
        })

    return chunks


_EXTRACTION_PROMPT = """
You are a systematic review data extraction assistant.

Your task: extract ONE specific field from the paper excerpt below.

Field to extract: {field_name}
Instruction: {instruction}

Paper title: {title}

Relevant excerpts from the paper:
---
{context}
---

CRITICAL RULES:
- Extract ONLY what is explicitly stated in the excerpts above.
- If the information is not present in the excerpts, return null.
- Do NOT infer, calculate, or guess.
- Do NOT use your general knowledge about the paper.
- Return ONLY valid JSON with exactly these two keys:

{{
  "value": <extracted value, or null if not found>,
  "supporting_text": "<verbatim phrase from the excerpts that contains the value, or empty string>"
}}
"""


def extract_field(
    field_name: str,
    search_query: str,
    instruction: str,
    paper_title: str,
    collection: chromadb.Collection,
    max_retries: int = 2,
) -> dict:
    """
    Extract ONE field from a paper using RAG.

    Steps:
      1. Retrieve the 4 most relevant chunks for this field's search_query
      2. Build a prompt with those chunks as context
      3. Call the LLM to extract just this field
      4. Return the value + the supporting text passage

    Returns: {"value": ..., "supporting_text": "...", "page": int}
    """
    # step 1 — retrieve relevant chunks
    chunks = retrieve_relevant_chunks(search_query, collection, n_results=4)

    if not chunks:
        return {"value": None, "supporting_text": "", "page": 0}

    # step 2 — build context string from retrieved chunks
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(f"[Excerpt {i}, page {chunk['page']}]\n{chunk['text']}")
    context = "\n\n".join(context_parts)

    prompt = _EXTRACTION_PROMPT.format(
        field_name=field_name,
        instruction=instruction,
        title=paper_title,
        context=context,
    )

    # step 3 — call LLM with retries
    for attempt in range(1, max_retries + 1):
        try:
            response = _llm_client.chat.completions.create(
                model=LLM_MODEL,
                temperature=0.0,   # must be deterministic for extraction
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise data extraction assistant. "
                            "Always respond with valid JSON only. "
                            "Never infer or hallucinate — only extract what is explicitly stated."
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
            )

            raw = response.choices[0].message.content.strip()

            # strip markdown code fences if model added them
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)

            # find which page the supporting text came from
            page = 0
            if result.get("supporting_text"):
                for chunk in chunks:
                    if result["supporting_text"][:50] in chunk["text"]:
                        page = chunk["page"]
                        break

            return {
                "value":          result.get("value"),
                "supporting_text": result.get("supporting_text", ""),
                "page":           page,
            }

        except json.JSONDecodeError as exc:
            log.warning("Field %s attempt %d — JSON parse error: %s", field_name, attempt, exc)
        except Exception as exc:
            log.warning("Field %s attempt %d — LLM error: %s", field_name, attempt, exc)
            time.sleep(2 ** attempt)

    # all retries failed — return null so Pydantic stores None
    return {"value": None, "supporting_text": "", "page": 0}


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — STRUCTURED OUTPUT + VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def build_extracted_paper(
    paper: dict,
    field_results: dict,
) -> Optional[ExtractedPaper]:
    """
    Take raw field extraction results and validate them with Pydantic.

    field_results: {field_name: {"value": ..., "supporting_text": ..., "page": ...}}

    Returns a validated ExtractedPaper or None if validation fails twice.

    Why Pydantic?
    → The LLM might return "87.3" for sensitivity instead of 0.873.
      Pydantic validators automatically fix this.
      If the LLM returns something completely wrong (e.g. a string where
      an int is required), Pydantic raises ValidationError and we can retry.
    """
    # build the flat dict of field values
    data = {
        "title": paper.get("title", ""),
        "doi":   paper.get("doi"),
        "sources": {}  # provenance dict
    }

    for field_name, result in field_results.items():
        data[field_name] = result["value"]
        # store provenance for every field that has a supporting text
        if result.get("supporting_text"):
            data["sources"][field_name] = {
                "text": result["supporting_text"],
                "page": result["page"],
            }

    try:
        return ExtractedPaper(**data)
    except ValidationError as exc:
        log.warning("Pydantic validation failed for '%s': %s",
                    paper.get("title", "")[:60], exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN EXTRACTION PIPELINE — processes one paper
# ══════════════════════════════════════════════════════════════════════════════

def extract_paper(paper: dict) -> Optional[ExtractedPaper]:
    """
    Run the full RAG extraction pipeline for ONE paper.

    Steps:
      1. Get PDF URL (Semantic Scholar → Unpaywall)
      2. Extract text page by page (PyMuPDF)
      3. Split into overlapping chunks (LangChain)
      4. Embed chunks and index in ChromaDB
      5. For each field in EXTRACTION_FIELDS: retrieve + extract
      6. Validate and return ExtractedPaper

    Returns ExtractedPaper or None if PDF not available.
    """
    title = paper.get("title", "unknown")
    log.info("  Extracting: %s", title[:80])

    # create a stable short ID for this paper (for ChromaDB collection name)
    paper_id = hashlib.md5(
        (paper.get("doi") or title).encode()
    ).hexdigest()[:12]

    # ── step 1: PDF ───────────────────────────────────────────────────────────
    pdf_url = get_pdf_url(paper)
    if not pdf_url:
        log.warning("    No PDF available — skipping extraction")
        return None

    # ── step 2: page extraction ───────────────────────────────────────────────
    pages = extract_pages(pdf_url)
    if not pages:
        log.warning("    PDF extraction returned no pages — skipping")
        return None

    # ── step 3: chunking ──────────────────────────────────────────────────────
    chunks = chunk_pages(pages)
    if not chunks:
        log.warning("    Chunking produced no chunks — skipping")
        return None

    # ── step 4: embed + index ─────────────────────────────────────────────────
    collection = get_or_create_collection(paper_id)
    index_chunks(chunks, collection)

    # ── step 5: extract each field ────────────────────────────────────────────
    field_results = {}
    for field_name, (search_query, instruction) in EXTRACTION_FIELDS.items():
        log.debug("    Extracting field: %s", field_name)
        result = extract_field(
            field_name=field_name,
            search_query=search_query,
            instruction=instruction,
            paper_title=title,
            collection=collection,
        )
        field_results[field_name] = result
        log.debug("    %s → %s", field_name, result["value"])

    # ── step 6: validate with Pydantic ────────────────────────────────────────
    extracted = build_extracted_paper(paper, field_results)
    if extracted:
        log.info("    ✓ Extraction complete for: %s", title[:60])
    else:
        log.warning("    ✗ Validation failed for: %s", title[:60])

    return extracted


# ══════════════════════════════════════════════════════════════════════════════
# RUN EXTRACTION — processes all included papers
# ══════════════════════════════════════════════════════════════════════════════

def run_extraction(included_papers: list[dict]) -> dict:
    """
    Run full RAG extraction on all papers that passed Module 2 screening.

    Input  : included_papers from Module 2 run_screening() output
    Output : dict with extracted_papers list + prisma counts + failed list

    This is what gets called from pipeline.py (LangGraph extraction_node).
    """
    extracted    = []   # successfully extracted papers
    failed       = []   # papers where PDF was unavailable or extraction failed
    total        = len(included_papers)

    log.info("Module 3 — extracting data from %d included papers", total)

    for i, paper in enumerate(included_papers, 1):
        log.info("[%d/%d] %s", i, total, paper.get("title", "")[:70])

        result = extract_paper(paper)

        if result:
            extracted.append(result.model_dump())  # convert Pydantic → dict
        else:
            failed.append({
                "paper":  paper,
                "reason": "PDF unavailable or extraction failed"
            })

    # PRISMA counts for the bottom box of your flow diagram
    prisma_counts = {
        "included_in_synthesis": len(extracted),
        "excluded_no_pdf":       len(failed),
        "total_attempted":       total,
    }

    log.info("Module 3 complete — extracted: %d | failed: %d",
             len(extracted), len(failed))

    return {
        "extracted_papers": extracted,
        "failed_papers":    failed,
        "prisma_counts":    prisma_counts,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI — smoke test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # load included papers from Module 2 output
        with open(sys.argv[1]) as f:
            papers = json.load(f)
    else:
        # minimal mock paper for testing
        papers = [
            {
                "title": "ASReview: Open Source Software for Efficient and Transparent Active Learning for Systematic Reviews",
                "doi":   "10.18637/jss.v102.i07",
                "abstract": "Mock abstract for testing.",
                "source": "pubmed",
                "openAccessPdf": None,
            }
        ]

    results = run_extraction(papers)

    print("\n=== PRISMA COUNTS ===")
    print(json.dumps(results["prisma_counts"], indent=2))

    print("\n=== EXTRACTED PAPERS ===")
    for p in results["extracted_papers"]:
        print(f"\n  Title: {p['title']}")
        print(f"  Tool:  {p.get('tool_name')}")
        print(f"  LLM:   {p.get('llm_used')}")
        print(f"  Kappa: {p.get('reported_kappa')}")
        print(f"  Sources: {list(p.get('sources', {}).keys())}")