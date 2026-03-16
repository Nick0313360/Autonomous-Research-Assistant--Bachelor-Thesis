"""
diagnose.py — Full Health Check for Module 1
=============================================
Run this BEFORE running the full test suite. It tells you exactly what
is working, what is broken, and why — without assuming anything.

Usage:
    python files/diagnose.py

Output:
    - Live connectivity check for PubMed and Semantic Scholar
    - LLM endpoint reachability and latency measurement
    - Golden standard: searches for each gold paper individually by DOI/title
      and confirms whether it is actually in PubMed/S2
    - AI refinement dry-run: shows exactly what the LLM suggests and what
      the domain validator accepts/rejects, without running a full search
    - Saved to: diagnose_report.json

This script is standalone — it imports from files/ directly.
"""

import sys
import os
import json
import time
import logging
from datetime import datetime

# ── Path setup ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
# If run from module1_searc/: files/ is a subdirectory
# If run from inside files/: it's the current directory
if os.path.basename(_HERE) == "files":
    _FILES = _HERE
else:
    _FILES = os.path.join(_HERE, "files")
sys.path.insert(0, _FILES)

from search_query import SearchQuery, QueryBuilder
from pubmed_connector import search as pubmed_search
from semantic_connector import search as semantic_search
from deduplicator import deduplicate
from rapidfuzz import fuzz

logging.basicConfig(level=logging.WARNING)  # suppress noisy logs during diagnosis

REPORT = {
    "timestamp": datetime.now().isoformat(),
    "checks": {}
}

SEP  = "=" * 60
SEP2 = "─" * 60

def section(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def ok(msg):  print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def fail(msg): print(f"  ❌ {msg}")
def info(msg): print(f"     {msg}")


# =============================================================================
# CHECK 1 — PubMed connectivity and basic query
# =============================================================================

section("CHECK 1 — PubMed Connectivity")

try:
    sq_test = SearchQuery(
        research_question="systematic review automation",
        population="systematic review",
        intervention="machine learning, NLP",
        max_papers_per_db=10,
    )
    q = QueryBuilder.build_pubmed(sq_test)
    info(f"Query: {q[:120]}")

    t0 = time.time()
    papers = pubmed_search(q, retmax=10)
    elapsed = time.time() - t0

    if len(papers) > 0:
        ok(f"PubMed returned {len(papers)} papers in {elapsed:.1f}s")
        info(f"First result: {papers[0].get('title', '')[:80]}")
        REPORT["checks"]["pubmed"] = {"status": "ok", "papers": len(papers), "latency_s": round(elapsed, 2)}
    else:
        fail("PubMed returned 0 papers — check network or NCBI Entrez email setting")
        REPORT["checks"]["pubmed"] = {"status": "zero_results", "latency_s": round(elapsed, 2)}

except Exception as e:
    fail(f"PubMed failed: {e}")
    REPORT["checks"]["pubmed"] = {"status": "error", "error": str(e)}


# =============================================================================
# CHECK 2 — Semantic Scholar connectivity
# =============================================================================

section("CHECK 2 — Semantic Scholar Connectivity")

time.sleep(1.2)  # rate limit
try:
    t0 = time.time()
    papers = semantic_search("systematic review automation machine learning NLP", limit=20)
    elapsed = time.time() - t0

    if len(papers) > 0:
        ok(f"S2 returned {len(papers)} papers in {elapsed:.1f}s")
        info(f"First result: {papers[0].get('title', '')[:80]}")
        REPORT["checks"]["semantic"] = {"status": "ok", "papers": len(papers), "latency_s": round(elapsed, 2)}
    else:
        fail("S2 returned 0 papers — check SEMANTIC_SCHOLAR_API_KEY in .env")
        REPORT["checks"]["semantic"] = {"status": "zero_results"}

except Exception as e:
    fail(f"S2 failed: {e}")
    REPORT["checks"]["semantic"] = {"status": "error", "error": str(e)}


# =============================================================================
# CHECK 3 — LLM endpoint reachability and latency
# =============================================================================

section("CHECK 3 — LLM Endpoint (University API)")

try:
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()

    base_url = os.getenv("OPENAI_BASE_URL", "https://inference.mlmp.ti.bfh.ch/api/v1")
    model    = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
    api_key  = os.getenv("OPENAI_API_KEY", "")

    info(f"Endpoint: {base_url}")
    info(f"Model:    {model}")
    info(f"API key present: {'yes' if api_key else 'NO — set OPENAI_API_KEY in .env'}")

    if not api_key:
        warn("OPENAI_API_KEY is not set — LLM calls will fail")
        REPORT["checks"]["llm"] = {"status": "no_api_key"}
    else:
        client = OpenAI(base_url=base_url, api_key=api_key)

        # Minimal probe — shortest possible request
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with: ok"}],
            timeout=90,  # generous timeout for slow uni GPU
        )
        elapsed = time.time() - t0
        reply = resp.choices[0].message.content.strip()

        ok(f"LLM responded in {elapsed:.1f}s → '{reply[:50]}'")
        REPORT["checks"]["llm"] = {
            "status": "ok",
            "latency_s": round(elapsed, 2),
            "model": model,
            "reply": reply[:50],
        }

        if elapsed > 60:
            warn(f"LLM latency is {elapsed:.0f}s — very slow. "
                 "Set LLM_TIMEOUT_SECONDS=120 in .env to avoid timeouts during --ai mode.")
        elif elapsed > 30:
            warn(f"LLM latency is {elapsed:.0f}s — moderate. "
                 "Consider setting LLM_TIMEOUT_SECONDS=90 in .env.")

except Exception as e:
    fail(f"LLM endpoint failed: {e}")
    REPORT["checks"]["llm"] = {"status": "error", "error": str(e)}
    warn("AI refinement (--ai mode) will not work until this is fixed.")


# =============================================================================
# CHECK 4 — Golden standard: verify each gold paper is actually retrievable
# =============================================================================

section("CHECK 4 — Golden Standard Retrievability")
print("  Searching for each gold paper individually to confirm it exists in PubMed/S2.")
print("  This is the ground-truth check — if papers don't exist here, recall will always be low.\n")

# Import gold papers from fixtures
try:
    _tests_dir = os.path.join(_HERE if os.path.basename(_HERE) != "files" else os.path.dirname(_HERE), "tests")
    sys.path.insert(0, _tests_dir)
    from fixtures import GOLDEN_STANDARD
    gold_papers = GOLDEN_STANDARD["gold_papers"]
except Exception as e:
    fail(f"Could not load fixtures: {e}")
    gold_papers = []

gold_results = []

for i, gp in enumerate(gold_papers, 1):
    title = gp["title"]
    doi   = gp.get("doi")

    # Search PubMed by DOI if available, else by title
    found_pubmed = False
    found_s2     = False

    time.sleep(0.5)  # gentle rate limiting

    # PubMed: search by DOI field tag if DOI available, else title search
    try:
        if doi:
            pm_query = f'"{doi}"[DOI]'
        else:
            # Use first 6 words of title as a phrase search
            short_title = " ".join(title.split()[:6])
            pm_query = f'"{short_title}"[Title]'

        pm_papers = pubmed_search(pm_query, retmax=5)
        for p in pm_papers:
            p_title = (p.get("title") or "").lower()
            if fuzz.ratio(title.lower(), p_title) >= 70:
                found_pubmed = True
                break
            p_doi = (p.get("doi") or "").lower()
            if doi and doi.lower() in p_doi:
                found_pubmed = True
                break
    except Exception as e:
        pass

    # S2: search by title keywords
    time.sleep(1.2)
    try:
        short_title = " ".join(title.split()[:5])
        s2_papers = semantic_search(short_title, limit=10)
        for p in s2_papers:
            p_title = (p.get("title") or "").lower()
            if fuzz.ratio(title.lower(), p_title) >= 70:
                found_s2 = True
                break
    except Exception:
        pass

    status = "✅" if (found_pubmed or found_s2) else "❌"
    pm_str = "PubMed✓" if found_pubmed else "PubMed✗"
    s2_str = "S2✓"     if found_s2     else "S2✗"
    print(f"  {status} [{pm_str}] [{s2_str}]  {title[:65]}")

    gold_results.append({
        "title": title,
        "doi": doi,
        "found_pubmed": found_pubmed,
        "found_s2": found_s2,
        "retrievable": found_pubmed or found_s2,
    })

retrievable_count = sum(1 for g in gold_results if g["retrievable"])
print(f"\n  {SEP2}")
print(f"  Retrievable: {retrievable_count}/{len(gold_papers)} gold papers found in at least one DB")

if retrievable_count < len(gold_papers) * 0.5:
    warn("Fewer than 50% of gold papers are retrievable — the gold set needs updating")
    warn("Re-run the recall test after fixing the gold paper titles/DOIs")
else:
    ok(f"{retrievable_count}/{len(gold_papers)} gold papers confirmed retrievable")

REPORT["checks"]["golden_standard"] = {
    "retrievable_count": retrievable_count,
    "total": len(gold_papers),
    "papers": gold_results,
}


# =============================================================================
# CHECK 5 — AI refinement dry-run (uses real LLM if available)
# =============================================================================

section("CHECK 5 — AI Refinement Dry-Run")
print("  Simulates one LLM refinement step using a small paper sample.")
print("  Shows exactly what the LLM suggests and what the domain validator accepts/rejects.\n")

if REPORT["checks"].get("llm", {}).get("status") != "ok":
    warn("Skipping — LLM endpoint is not reachable (see Check 3)")
    REPORT["checks"]["refinement_dryrun"] = {"status": "skipped_no_llm"}
else:
    try:
        from llm_refiner import analyse_query_gaps

        # Use the 10 most recent papers from a fresh search as the sample
        sq_refine = SearchQuery(
            research_question="automated systematic literature review",
            population="systematic review, literature review",
            intervention="machine learning, NLP, automation",
            domain_keywords=["systematic review", "NLP", "automation", "screening", "PRISMA"],
            max_papers_per_db=50,
        )
        sample_query = QueryBuilder.build_pubmed(sq_refine)
        sample_papers = pubmed_search(sample_query, retmax=20)

        info(f"Using {len(sample_papers)} papers as context for LLM")
        info(f"Query being refined: {QueryBuilder.build_semantic(sq_refine)}")
        info(f"Domain anchors: {sq_refine.effective_domain_keywords()}")
        print()

        used_terms = set()
        t0 = time.time()
        result = analyse_query_gaps(
            papers=sample_papers,
            original_query=QueryBuilder.build_semantic(sq_refine),
            domain_keywords=sq_refine.effective_domain_keywords(),
            used_terms=used_terms,
            iteration=1,
            max_new_terms=5,
        )
        elapsed = time.time() - t0

        if result.error:
            fail(f"LLM call failed: {result.error}")
            REPORT["checks"]["refinement_dryrun"] = {"status": "llm_error", "error": result.error}
        else:
            print(f"  LLM raw output : '{result.llm_raw_output}'")
            print(f"  Elapsed        : {elapsed:.1f}s")
            print()
            print(f"  Accepted terms ({len(result.accepted_terms)}):")
            for t in result.accepted_terms:
                ok(f"  '{t}'")
            print()
            print(f"  Rejected terms ({len(result.rejected_terms)}):")
            for d in result.rejected_terms:
                fail(f"  '{d.term}'  reason={d.reason}")

            print(f"\n  Acceptance rate: {result.acceptance_rate:.0%}")
            print(f"  Expanded query : {result.expanded_query[:200]}")

            if result.acceptance_rate < 0.2:
                warn("Acceptance rate < 20% — domain validator may be too strict, "
                     "or LLM is suggesting off-topic terms. Check domain_keywords.")
            elif result.acceptance_rate > 0.8:
                ok("Acceptance rate looks healthy")

            REPORT["checks"]["refinement_dryrun"] = {
                "status": "ok",
                "llm_raw": result.llm_raw_output,
                "accepted": result.accepted_terms,
                "rejected": [(d.term, d.reason) for d in result.rejected_terms],
                "acceptance_rate": result.acceptance_rate,
                "expanded_query": result.expanded_query,
                "latency_s": round(elapsed, 2),
            }

    except Exception as e:
        fail(f"Refinement dry-run failed: {e}")
        REPORT["checks"]["refinement_dryrun"] = {"status": "error", "error": str(e)}


# =============================================================================
# CHECK 6 — .env configuration
# =============================================================================

section("CHECK 6 — Configuration (.env)")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    warn("python-dotenv not installed — install with: pip install python-dotenv")

env_vars = {
    "OPENAI_API_KEY":              os.getenv("OPENAI_API_KEY"),
    "OPENAI_BASE_URL":             os.getenv("OPENAI_BASE_URL"),
    "OPENAI_MODEL":                os.getenv("OPENAI_MODEL"),
    "SEMANTIC_SCHOLAR_API_KEY":    os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
    "LLM_TIMEOUT_SECONDS":         os.getenv("LLM_TIMEOUT_SECONDS"),
}

for key, val in env_vars.items():
    if val:
        # Don't print actual key values — just confirm presence
        display = "[SET]" if "KEY" in key else val
        ok(f"{key} = {display}")
    else:
        level = fail if key in ("OPENAI_API_KEY", "SEMANTIC_SCHOLAR_API_KEY") else warn
        level(f"{key} = NOT SET")

if not os.getenv("LLM_TIMEOUT_SECONDS"):
    warn("LLM_TIMEOUT_SECONDS not set — defaulting to 30s. "
         "University GPU can be slow; add LLM_TIMEOUT_SECONDS=120 to .env")

REPORT["checks"]["env"] = {k: ("set" if v else "missing") for k, v in env_vars.items()}


# =============================================================================
# SUMMARY
# =============================================================================

section("SUMMARY")

checks_status = {
    "PubMed":              REPORT["checks"].get("pubmed", {}).get("status"),
    "Semantic Scholar":    REPORT["checks"].get("semantic", {}).get("status"),
    "LLM endpoint":        REPORT["checks"].get("llm", {}).get("status"),
    "Golden retrievable":  f"{retrievable_count}/{len(gold_papers)}" if gold_papers else "skipped",
    "Refinement dry-run":  REPORT["checks"].get("refinement_dryrun", {}).get("status", "skipped"),
}

all_critical_ok = all(
    checks_status[k] == "ok"
    for k in ["PubMed", "Semantic Scholar"]
)

for name, status in checks_status.items():
    if status == "ok":
        ok(f"{name}: OK")
    elif status and status.startswith("skipped"):
        warn(f"{name}: SKIPPED")
    elif status == "zero_results":
        fail(f"{name}: ZERO RESULTS")
    elif status and "/" in str(status):
        info(f"{name}: {status}")
    else:
        fail(f"{name}: {status}")

print()
if all_critical_ok:
    ok("Pipeline is functional — PubMed and S2 both working.")
    if REPORT["checks"].get("llm", {}).get("status") != "ok":
        warn("--ai mode will not work until LLM endpoint responds.")
        warn("Basic search (python literature_handler.py) works fine without LLM.")
else:
    fail("Critical components are not working — fix before running tests.")

# Save report
report_path = os.path.join(_HERE if os.path.basename(_HERE) != "files" else os.path.dirname(_HERE), "diagnose_report.json")
with open(report_path, "w") as f:
    json.dump(REPORT, f, indent=2, default=str)
print(f"\n  📄 Full report saved → {report_path}")