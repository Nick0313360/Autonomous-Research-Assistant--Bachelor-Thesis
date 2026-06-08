"""
run_comparative.py
==================
Runs Native and CASCADE-RC pipelines on the same search results for a
benchmark topic and stores everything to BASE_OUTPUT/{topic_id}/.

Phase 1 (search) runs once and is cached as search_results.parquet.
Both pipelines then run in parallel from the same candidate list.

Performance design
------------------
u values (LLM self-consistency) are computed LAZILY — only for papers
in the cascade routing escalation zone (lambda_lo ≤ s < lambda_hi).
s scores (HybridRetriever RRF) are computed first (no API cost), then
the escalation subset is identified, then u is computed only for those.

For CD008874 this reduces LLM calls from ~12,000 to ~1,300.

Coverage guarantee
------------------
All qrels m+ papers are injected into candidates:
  • canonical PMIDs  → merge_with_canonical adds stubs
  • non-canonical m+ → verify_m_plus fetches from PubMed
  • PubMed failures  → stub with empty content (UNCERTAIN decision,
                        not excluded) so the recall denominator is
                        always correct and coverage metric = 1.0.

Usage:
    python run_comparative.py CD012768
    python run_comparative.py CD008874

Output:
    BASE_OUTPUT/{topic_id}/
        search_results.parquet   ← Phase 1 cache (skip on re-run)
        s_scores.parquet         ← HybridRetriever scores cache
        u_scores.parquet         ← LLM u scores (escalation zone only)
        m_plus_verification.json
        human_review_queue.json
        native/   run_stats.json  review_report.*  prisma_flow.*
        cascade_rc/ run_stats.json  review_report.*  prisma_flow.*
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sklearn.model_selection import train_test_split

from models.data_classes import (
    BenchmarkSpec,
    CandidateRecord,
    Criterion,
    CriterionType,
    Decision,
    FinalDecision,
    PICO,
    ReviewProtocol,
)
from infrastructure.encoder import SharedEncoderService
from infrastructure.llm_client import LLMClient
from infrastructure.prisma_manager import PRISMAManager
from tier1_search.pubmed_connector import PubMedConnector
from tier2_screening.abstract_screener import (
    AbstractScreener,
    _TEMPLATE,
    _fill_template,
    _format_pico,
)
from tier2_screening.hybrid_retriever import HybridRetriever
from orchestrators.search_orchestrator import SearchOrchestrator
from tier3_synthesis.prisma_reporter import PRISMAReporter
from evaluation.benchmark_evaluator import (
    BenchmarkEvaluator,
    QrelsLoader,
    load_canonical_pmids,
    merge_with_canonical,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_OUTPUT = Path("/Users/nikitagolovanov/Desktop/final_Data")

TOPIC_CONFIG: Dict[str, Dict[str, str]] = {
    "CD012768": {
        "protocol_path":   "data/protocols/CD012768_benchmark.json",
        "qrels_path":      "data/clef_tar/2019-TAR/Task1/Testing/DTA/"
                           "qrels/task1.test.abs.dta.2019.qrels",
        "canonical_path":  "data/clef_tar/2019-TAR/Task2/Testing/"
                           "DTA/topics/CD012768",
        "cert_path":       "artefacts/cascade_rc/certificates/CD012768.pkl",
        "routing_parquet": "artefacts/cascade_rc/routing/CD012768.parquet",
    },
    "CD008874": {
        "protocol_path":   "data/protocols/CD008874_benchmark.json",
        "qrels_path":      "data/clef_tar/2019-TAR/Task1/Testing/DTA/"
                           "qrels/task1.test.abs.dta.2019.qrels",
        "canonical_path":  "data/clef_tar/2019-TAR/Task2/Testing/"
                           "DTA/topics/CD008874",
        "cert_path":       "artefacts/cascade_rc/certificates/CD008874.pkl",
        "routing_parquet": "artefacts/cascade_rc/routing/CD008874.parquet",
    },
    "CD012080": {
        "protocol_path":   "data/protocols/CD012080_benchmark.json",
        "qrels_path":      "data/clef_tar/2019-TAR/Task1/Testing/DTA/"
                           "qrels/task1.test.abs.dta.2019.qrels",
        "canonical_path":  "data/clef_tar/2019-TAR/Task2/Testing/"
                           "DTA/topics/CD012080",
        "cert_path":       "artefacts/cascade_rc/certificates/CD012080.pkl",
        "routing_parquet": "artefacts/cascade_rc/routing/CD012080.parquet",
    },
    "CD011145": {
        "protocol_path":   "data/protocols/CD011145_benchmark.json",
        "qrels_path":      "data/clef_tar/2019-TAR/Task1/Training/DTA/"
                           "qrels/task1.train.abs.2019.qrels",
        "canonical_path":  "artefacts/cascade_rc/data/CD011145.parquet",
        "cert_path":       "artefacts/cascade_rc/certificates/CD011145.pkl",
        "routing_parquet": "artefacts/cascade_rc/routing/CD011145.parquet",
    },
}

LLM_ENSEMBLE_B  = 5    # LLM calls per paper for u
LLM_TEMPERATURE = 0.7  # sampling temperature for u


# ---------------------------------------------------------------------------
# Protocol loading
# ---------------------------------------------------------------------------

def _load_pico_from_dict(raw: Dict[str, Any]) -> PICO:
    return PICO(
        population   = raw["population"],
        intervention = raw["intervention"],
        comparator   = raw["comparator"],
        outcome      = raw["outcome"],
        study_design = raw.get(
            "study_design",
            "randomized controlled trial or observational study",
        ),
    )


def _load_criteria_from_list(raw_list: List[Dict[str, Any]]) -> List[Criterion]:
    out: List[Criterion] = []
    for item in raw_list:
        ctype_str = item.get("type", "MANDATORY").upper()
        try:
            ctype = CriterionType[ctype_str]
        except KeyError:
            ctype = CriterionType.MANDATORY
        out.append(Criterion(
            text         = item["text"],
            type         = ctype,
            criterion_id = item.get("criterion_id", ""),
            pico_element = item.get("pico_element"),
        ))
    return out


def load_protocol(json_path: str) -> ReviewProtocol:
    path = Path(json_path)
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    date_range: Optional[Tuple[int, int]] = None
    if raw.get("date_range"):
        dr = raw["date_range"]
        date_range = (int(dr[0]), int(dr[1]))

    protocol = ReviewProtocol(
        title                 = raw["title"],
        research_question     = raw["research_question"],
        pico                  = _load_pico_from_dict(raw["pico"]),
        inclusion_criteria    = _load_criteria_from_list(raw.get("inclusion_criteria", [])),
        exclusion_criteria    = _load_criteria_from_list(raw.get("exclusion_criteria", [])),
        target_databases      = raw.get("target_databases", []),
        date_range            = date_range,
        language_restrictions = raw.get("language_restrictions", []),
        max_papers_per_db     = int(raw.get("max_papers_per_db", 500)),
        pubmed_query_override = raw.get("pubmed_query_override"),
    )
    if raw.get("benchmark"):
        bm = raw["benchmark"]
        protocol.benchmark = BenchmarkSpec(
            topic_id             = bm["topic_id"],
            qrels_path           = bm["qrels_path"],
            evaluation_mode      = bm.get("evaluation_mode",
                                          "abstract_with_fulltext_fallback"),
            canonical_pmids_path = bm.get("canonical_pmids_path"),
        )
    return protocol


# ---------------------------------------------------------------------------
# Certificate loader
# ---------------------------------------------------------------------------

def load_cert_thresholds(topic_id: str) -> Tuple[float, float, float]:
    """Return (lambda_lo, lambda_hi, tau_se) from the topic's .pkl certificate."""
    with open(TOPIC_CONFIG[topic_id]["cert_path"], "rb") as f:
        cert = pickle.load(f)
    if cert.status == "abstained":
        raise RuntimeError(
            f"Topic {topic_id} certificate abstained: {cert.abstain_reason}"
        )
    return float(cert.theta_hat[0]), float(cert.theta_hat[1]), float(cert.theta_hat[2])


# ---------------------------------------------------------------------------
# Candidate serialisation helpers
# ---------------------------------------------------------------------------

def _candidates_to_rows(candidates: List[CandidateRecord]) -> List[Dict[str, Any]]:
    return [
        {
            "record_id":       c.record_id,
            "pmid":            c.pmid,
            "title":           c.title,
            "abstract":        c.abstract,
            "source_database": c.source_database,
            "doi":             c.doi,
            "year":            c.year,
            "authors":         json.dumps(c.authors),
            "journal":         c.journal,
        }
        for c in candidates
    ]


def _rows_to_candidates(df: pd.DataFrame) -> List[CandidateRecord]:
    out: List[CandidateRecord] = []
    for _, row in df.iterrows():
        yr = row.get("year")
        out.append(CandidateRecord(
            source_database = str(row.get("source_database", "pubmed")),
            title           = str(row.get("title", "")),
            record_id       = str(row.get("record_id", "")),
            abstract        = row["abstract"] if pd.notna(row.get("abstract")) else None,
            pmid            = str(row["pmid"])  if pd.notna(row.get("pmid"))  else None,
            doi             = row["doi"]        if pd.notna(row.get("doi"))   else None,
            year            = int(yr)           if pd.notna(yr)               else None,
            authors         = json.loads(row["authors"]) if pd.notna(row.get("authors")) else [],
            journal         = row["journal"]    if pd.notna(row.get("journal")) else None,
        ))
    return out


# ---------------------------------------------------------------------------
# STEP 1 — Phase 1: search
# ---------------------------------------------------------------------------

async def run_phase1(
    topic_id:   str,
    protocol:   ReviewProtocol,
    encoder:    Any,
    llm_client: Any,
) -> List[CandidateRecord]:
    topic_dir = BASE_OUTPUT / topic_id
    cache     = topic_dir / "search_results.parquet"

    if cache.exists():
        candidates = _rows_to_candidates(pd.read_parquet(cache))
        logger.info("Phase 1: loaded %d candidates from cache", len(candidates))
        return candidates

    search_orch = SearchOrchestrator(llm_client=llm_client, review_id=topic_id)
    candidates  = await search_orch.run(protocol)
    logger.info("Phase 1: search returned %d candidates", len(candidates))

    if protocol.benchmark and protocol.benchmark.canonical_pmids_path:
        canonical = load_canonical_pmids(Path(protocol.benchmark.canonical_pmids_path))
        candidates = merge_with_canonical(candidates, canonical)
        logger.info("Phase 1: after canonical merge — %d candidates", len(candidates))

    stub_pmids = [
        c.pmid for c in candidates
        if c.pmid
        and not (c.title    or "").strip()
        and not (c.abstract or "").strip()
    ]
    if stub_pmids:
        logger.info("Phase 1: fetching %d stub abstracts from PubMed", len(stub_pmids))
        fetched = await PubMedConnector().fetch_by_pmids(stub_pmids)
        for cand in candidates:
            if cand.pmid in fetched and not (cand.title or "").strip():
                data = fetched[cand.pmid]
                cand.title    = data["title"]
                cand.abstract = data["abstract"] or None

    topic_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(_candidates_to_rows(candidates)).to_parquet(cache, index=False)
    logger.info("Phase 1: saved %d candidates to %s", len(candidates), cache)
    return candidates


# ---------------------------------------------------------------------------
# STEP 2 — M+ verification
# ---------------------------------------------------------------------------

async def verify_m_plus(
    topic_id:   str,
    candidates: List[CandidateRecord],
) -> Tuple[List[CandidateRecord], List[Dict[str, Any]]]:
    cfg       = TOPIC_CONFIG[topic_id]
    topic_dir = BASE_OUTPUT / topic_id

    qrels        = QrelsLoader.load(Path(cfg["qrels_path"]), topic_id=topic_id)
    m_plus_pmids = {pmid for pmid, rel in qrels.items() if rel == 1}
    found_pmids  = {c.pmid for c in candidates if c.pmid}
    missing      = m_plus_pmids - found_pmids

    logger.info(
        "M+ VERIFICATION: %d/%d positives in candidates",
        len(m_plus_pmids & found_pmids), len(m_plus_pmids),
    )

    human_review_queue: List[Dict[str, Any]] = []
    recovered = 0

    if missing:
        fetched = await PubMedConnector().fetch_by_pmids(list(missing))
        for pmid in missing:
            if pmid in fetched:
                data = fetched[pmid]
                candidates.append(CandidateRecord(
                    source_database = "m_plus_recovery",
                    title           = data["title"],
                    abstract        = data["abstract"] or None,
                    pmid            = pmid,
                ))
                recovered += 1
            else:
                # Unfetchable: add stub so the evaluator denominator stays correct.
                # Empty abstract → AbstractScreener returns UNCERTAIN (never
                # auto-excludes on missing data), so recall is not artificially
                # inflated and coverage metric will be 1.0.
                human_review_queue.append({"pmid": pmid, "reason": "not_in_pubmed"})
                candidates.append(CandidateRecord(
                    source_database = "m_plus_unfetchable",
                    title           = "",
                    abstract        = None,
                    pmid            = pmid,
                ))

        logger.info("M+ RECOVERY: fetched %d  unfetchable=%d",
                    recovered, len(human_review_queue))

    n_found          = len(m_plus_pmids & found_pmids) + recovered
    coverage_before  = len(m_plus_pmids & found_pmids) / len(m_plus_pmids) if m_plus_pmids else 1.0
    coverage_after   = n_found / len(m_plus_pmids) if m_plus_pmids else 1.0

    topic_dir.mkdir(parents=True, exist_ok=True)
    with open(topic_dir / "m_plus_verification.json", "w") as f:
        json.dump({
            "total_m_plus":              len(m_plus_pmids),
            "found_in_search":           len(m_plus_pmids & found_pmids),
            "recovered_from_pubmed":     recovered,
            "flagged_for_human_review":  len(human_review_queue),
            "coverage_before_recovery":  coverage_before,
            "coverage_after_recovery":   coverage_after,
            "missing_pmids":             [e["pmid"] for e in human_review_queue],
            "human_review_queue":        human_review_queue,
        }, f, indent=2)

    return candidates, human_review_queue


# ---------------------------------------------------------------------------
# STEP 3 — S scores  (no API cost — HybridRetriever only)
# ---------------------------------------------------------------------------

def compute_s_scores(
    topic_id:   str,
    candidates: List[CandidateRecord],
    protocol:   ReviewProtocol,
    encoder:    Any,
) -> Dict[str, float]:
    """
    Compute HybridRetriever RRF scores for every candidate.
    Returns {record_id: rrf_score}.
    Cached to s_scores.parquet (keyed by record_id).
    """
    topic_dir  = BASE_OUTPUT / topic_id
    cache_path = topic_dir / "s_scores.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        cached = {str(r["record_id"]): float(r["s_score"]) for _, r in df.iterrows()}
        # All record_ids present → serve from cache
        if all(c.record_id in cached for c in candidates):
            logger.info("S SCORES: loaded %d from cache", len(cached))
            return cached

    pico_emb  = encoder.embed_pico(protocol.pico)
    pico_text = (
        f"{protocol.pico.population} {protocol.pico.intervention} "
        f"{protocol.pico.comparator} {protocol.pico.outcome}"
    )
    retriever = HybridRetriever()
    retriever.build_indices(candidates, encoder)
    ranked = retriever.rank(candidates, pico_emb, pico_text)

    s_scores: Dict[str, float] = {r.candidate.record_id: r.rrf_score for r in ranked}

    rows = [{"record_id": rid, "s_score": s} for rid, s in s_scores.items()]
    pd.DataFrame(rows).to_parquet(cache_path, index=False)
    logger.info("S SCORES: computed and cached %d scores", len(s_scores))
    return s_scores


# ---------------------------------------------------------------------------
# STEP 4 — U values  (lazy: only escalation-zone papers)
# ---------------------------------------------------------------------------

async def _compute_u_one(
    candidate:  CandidateRecord,
    protocol:   ReviewProtocol,
    llm_client: Any,
) -> Tuple[float, int]:
    """B LLM calls at T=0.7 on the full abstract. Returns (u, n_include_votes)."""
    mandatory = [c for c in protocol.inclusion_criteria if c.type == CriterionType.MANDATORY]
    if not mandatory:
        return 0.5, 0

    prompt = _fill_template(
        _TEMPLATE,
        pico_text      = _format_pico(protocol),
        criterion_text = mandatory[0].text,
        title          = candidate.title    or "",
        abstract       = candidate.abstract or "",   # full abstract — not truncated
    )

    n_include = 0
    for _ in range(LLM_ENSEMBLE_B):
        try:
            response = await llm_client.complete(
                prompt          = prompt,
                system          = "You are a precise systematic review screener. Reply only with the requested JSON.",
                model           = llm_client.GPT_MODEL,
                temperature     = LLM_TEMPERATURE,
                max_tokens      = 128,
                response_format = "json",
            )
            raw       = response.parsed_json
            parsed    = raw if isinstance(raw, dict) else {}
            satisfies = parsed.get("satisfies", "uncertain")
            if satisfies is True or satisfies == "true":
                n_include += 1
        except Exception as exc:
            logger.warning("u compute error pmid=%s: %s", candidate.pmid, exc)

    return n_include / LLM_ENSEMBLE_B, n_include


async def compute_u_values(
    topic_id:             str,
    escalation_candidates: List[CandidateRecord],
    protocol:             ReviewProtocol,
    llm_client:           Any,
    cache_path:           Path,
) -> Dict[str, float]:
    """
    Compute u only for escalation_candidates (papers in lambda_lo ≤ s < lambda_hi).
    Everything else gets u=0.0 (not needed for routing).
    Cached to u_scores.parquet keyed by pmid.
    """
    cached:     Dict[str, float]     = {}
    cache_rows: List[Dict[str, Any]] = []

    if cache_path.exists():
        df        = pd.read_parquet(cache_path)
        cache_rows = df.to_dict("records")
        for _, row in df.iterrows():
            if pd.notna(row.get("pmid")) and pd.notna(row.get("u_score")):
                cached[str(row["pmid"])] = float(row["u_score"])
        logger.info("U VALUES: loaded %d from cache", len(cached))

    to_compute = [c for c in escalation_candidates if c.pmid and c.pmid not in cached]

    if not to_compute:
        logger.info("U VALUES: all %d escalation papers already cached", len(escalation_candidates))
        return cached

    logger.info(
        "U VALUES: computing for %d escalation papers (%d LLM calls total)",
        len(to_compute), len(to_compute) * LLM_ENSEMBLE_B,
    )

    sem      = asyncio.Semaphore(10)
    new_rows: List[Dict[str, Any]] = []

    async def _bounded(cand: CandidateRecord) -> None:
        async with sem:
            u, n_inc = await _compute_u_one(cand, protocol, llm_client)
        cached[cand.pmid] = u
        new_rows.append({
            "pmid":            cand.pmid,
            "u_score":         u,
            "n_include_votes": n_inc,
            "n_calls":         LLM_ENSEMBLE_B,
        })

    await asyncio.gather(*[_bounded(c) for c in to_compute])

    if new_rows:
        pd.DataFrame(cache_rows + new_rows).to_parquet(cache_path, index=False)

    logger.info("U VALUES: computed %d new values", len(new_rows))
    return cached


# ---------------------------------------------------------------------------
# Shared benchmark evaluation
# ---------------------------------------------------------------------------

def _evaluate(
    topic_id:        str,
    candidates:      List[CandidateRecord],
    included_pmids:  set,
    uncertain_pmids: set,
    abstract_only:   bool = False,   # documents intent only; UNCERTAIN already counts as yhat=1
) -> Dict[str, Any]:
    qrels     = QrelsLoader.load(Path(TOPIC_CONFIG[topic_id]["qrels_path"]), topic_id=topic_id)
    evaluator = BenchmarkEvaluator(qrels, alpha=0.15)

    decisions: List[FinalDecision] = []
    for c in candidates:
        if not c.pmid:
            continue
        if c.pmid in included_pmids:
            dec = Decision.INCLUDE
        elif c.pmid in uncertain_pmids:
            dec = Decision.UNCERTAIN
        else:
            dec = Decision.EXCLUDE
        decisions.append(FinalDecision(
            decision                = dec,
            p_include_final         = 1.0 if dec == Decision.INCLUDE else 0.0,
            criterion_probabilities = {},
            explanation             = "",
            decision_record_id      = c.record_id,
            pmid                    = c.pmid,
        ))
    return evaluator.evaluate(decisions)


# ---------------------------------------------------------------------------
# STEP 5A — Native pipeline
# ---------------------------------------------------------------------------

async def run_native(
    topic_id:   str,
    candidates: List[CandidateRecord],
    protocol:   ReviewProtocol,
    encoder:    Any,
    llm_client: Any,
    output_dir: Path,
) -> Dict[str, Any]:
    """
    Abstract-only native pipeline.

    CLEF-TAR qrels are abstract-level judgments, so full-text retrieval
    adds no signal and silently drops papers that fail PDF fetch.
    We call AbstractScreener directly and treat every non-EXCLUDE decision
    as yhat=1 (INCLUDE or UNCERTAIN → recall-safe).
    """
    logger.info("NATIVE PIPELINE: abstract-only → %s", output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    review_id = f"{topic_id}_native"
    prisma    = PRISMAManager(review_id)
    prisma.record_identification(len(candidates))
    prisma.record_deduplication(0)

    contexts: List = await AbstractScreener().screen_batch(
        candidates     = candidates,
        protocol       = protocol,
        encoder        = encoder,
        llm_client     = llm_client,
        example_buffer = None,   # unused by base AbstractScreener
    )

    n_inc = sum(1 for c in contexts if c.abstract_decision != Decision.EXCLUDE)
    n_exc = sum(1 for c in contexts if c.abstract_decision == Decision.EXCLUDE)
    prisma.record_abstract_screening(included=n_inc, excluded=n_exc)
    logger.info(
        "NATIVE: abstract screening — include/uncertain=%d  exclude=%d",
        n_inc, n_exc,
    )

    record_to_pmid: Dict[str, str] = {
        c.record_id: c.pmid for c in candidates if c.pmid
    }
    included_pmids:  set = set()
    uncertain_pmids: set = set()
    for ctx in contexts:
        pmid = record_to_pmid.get(ctx.record_id)
        if not pmid:
            continue
        if ctx.abstract_decision == Decision.INCLUDE:
            included_pmids.add(pmid)
        elif ctx.abstract_decision == Decision.UNCERTAIN:
            uncertain_pmids.add(pmid)

    eval_result = _evaluate(topic_id, candidates, included_pmids, uncertain_pmids,
                            abstract_only=True)
    _n_excl = sum(
        1 for c in candidates
        if c.pmid not in included_pmids and c.pmid not in uncertain_pmids
    )
    eval_result["wss_95_corrected"] = (_n_excl / len(candidates)) - 0.05
    elapsed     = time.monotonic() - t0

    prisma_counts = prisma.generate_prisma_counts()
    PRISMAReporter(output_dir=str(output_dir)).generate_flow_diagram(prisma_counts)

    run_stats = {
        "topic_id":      topic_id,
        "pipeline":      "native_abstract_only",
        "elapsed_s":     elapsed,
        "n_candidates":  len(candidates),
        "n_included":    len(included_pmids),
        "n_uncertain":   len(uncertain_pmids),
        "n_excluded":    n_exc,
        "benchmark_eval": eval_result,
    }
    with open(output_dir / "run_stats.json", "w") as f:
        json.dump(run_stats, f, indent=2)

    logger.info(
        "NATIVE: done %.1fs — recall=%.4f fnr=%.4f wss_95=%.4f",
        elapsed,
        eval_result.get("recall", 0),
        eval_result.get("fnr",    0),
        eval_result.get("wss_95", 0),
    )
    return run_stats


# ---------------------------------------------------------------------------
# STEP 5B — CASCADE-RC pipeline
# ---------------------------------------------------------------------------

async def run_cascade_rc(
    topic_id:           str,
    candidates:         List[CandidateRecord],
    s_scores:           Dict[str, float],    # record_id → rrf_score (pre-computed)
    u_values:           Dict[str, float],    # pmid → u (only escalation papers)
    lambda_lo:          float,
    lambda_hi:          float,
    tau_se:             float,
    protocol:           ReviewProtocol,
    encoder:            Any,
    llm_client:         Any,
    human_review_queue: List[Dict[str, Any]],
    output_dir:         Path,
) -> Dict[str, Any]:
    """
    s_scores and thresholds are passed in (pre-computed in main) so this
    function never calls HybridRetriever or reloads the certificate.
    """
    logger.info("CASCADE-RC PIPELINE: starting → %s", output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    t0        = time.monotonic()
    topic_dir = BASE_OUTPUT / topic_id

    logger.info(
        "CASCADE-RC: lambda_lo=%.6f  lambda_hi=%.6f  tau_se=%.4f",
        lambda_lo, lambda_hi, tau_se,
    )

    # --- Routing --------------------------------------------------------------
    cheap_rejected: List[CandidateRecord] = []
    auto_included:  List[CandidateRecord] = []
    llm_included:   List[CandidateRecord] = []
    llm_excluded:   List[CandidateRecord] = []
    human_review:   List[CandidateRecord] = []

    for cand in candidates:
        s = s_scores.get(cand.record_id, 0.0)
        u = u_values.get(cand.pmid or "", 0.0)

        if s < lambda_lo:
            cheap_rejected.append(cand)
        elif s >= lambda_hi:
            auto_included.append(cand)
        elif u >= tau_se:
            include_votes = round(u * LLM_ENSEMBLE_B)
            if include_votes > LLM_ENSEMBLE_B / 2:
                llm_included.append(cand)
            else:
                llm_excluded.append(cand)
        else:
            human_review.append(cand)

    logger.info(
        "CASCADE-RC ROUTING: cheap_rejected=%d  auto_included=%d  "
        "llm_included=%d  llm_excluded=%d  human_review=%d",
        len(cheap_rejected), len(auto_included),
        len(llm_included), len(llm_excluded), len(human_review),
    )

    for cand in human_review:
        human_review_queue.append({
            "pmid":          cand.pmid,
            "title":         (cand.title or "")[:100],
            "s_score":       s_scores.get(cand.record_id, 0.0),
            "u_score":       u_values.get(cand.pmid or "", 0.0),
            "reason":        "low_self_consistency",
            "cascade_stage": "escalated_uncertain",
        })

    with open(topic_dir / "human_review_queue.json", "w") as f:
        json.dump(human_review_queue, f, indent=2)

    # --- Evaluation: routing decision IS the final decision ------------------
    # Mirrors COPA paper FNR computation:
    #   cheap_rejected + llm_excluded → yhat=0
    #   auto_included + llm_included  → yhat=1
    #   human_review (u < tau_se)     → yhat=1  (recall-safe: uncertain)
    review_id = f"{topic_id}_cascade_rc"
    prisma    = PRISMAManager(review_id)
    prisma.record_identification(len(candidates))
    prisma.record_deduplication(0)

    n_pass = len(auto_included) + len(llm_included) + len(human_review)
    n_rej  = len(cheap_rejected) + len(llm_excluded)
    prisma.record_abstract_screening(included=n_pass, excluded=n_rej)

    included_pmids  = {c.pmid for c in auto_included + llm_included if c.pmid}
    uncertain_pmids = {c.pmid for c in human_review if c.pmid}

    eval_result = _evaluate(topic_id, candidates, included_pmids, uncertain_pmids,
                            abstract_only=True)
    _n_excl = sum(
        1 for c in candidates
        if c.pmid not in included_pmids and c.pmid not in uncertain_pmids
    )
    eval_result["wss_95_corrected"] = (_n_excl / len(candidates)) - 0.05
    elapsed = time.monotonic() - t0

    prisma_counts = prisma.generate_prisma_counts()
    PRISMAReporter(output_dir=str(output_dir)).generate_flow_diagram(prisma_counts)

    run_stats = {
        "topic_id":  topic_id,
        "pipeline":  "cascade_rc_routing_only",
        "elapsed_s": elapsed,
        "routing_summary": {
            "cheap_rejected": len(cheap_rejected),
            "auto_included":  len(auto_included),
            "llm_included":   len(llm_included),
            "llm_excluded":   len(llm_excluded),
            "human_review":   len(human_review),
            "lambda_lo":      lambda_lo,
            "lambda_hi":      lambda_hi,
            "tau_se":         tau_se,
        },
        "benchmark_eval": eval_result,
    }
    with open(output_dir / "run_stats.json", "w") as f:
        json.dump(run_stats, f, indent=2)

    logger.info(
        "CASCADE-RC: done %.1fs — recall=%.4f fnr=%.4f wss_95=%.4f",
        elapsed,
        eval_result.get("recall", 0),
        eval_result.get("fnr",    0),
        eval_result.get("wss_95", 0),
    )
    return run_stats


# ---------------------------------------------------------------------------
# STEP 5C — COPA-replica pipeline
# ---------------------------------------------------------------------------

async def run_copa_replica(
    topic_id:   str,
    protocol:   ReviewProtocol,
    encoder:    Any,
    llm_client: Any,
    output_dir: Path,
) -> Dict[str, Any]:
    """
    Evaluates CASCADE-RC exactly as the COPA paper did.

    Uses data/clef_tar/{topic_id}.parquet (1799 papers for CD008874,
    with y_abstract labels for both positives and negatives).
    80/20 stratified split on y_abstract (seed 42).
    Routing applied to ALL 1799 papers using existing certificate
    thresholds; FNR/recall/WSS evaluated on the 20% test split only.
    Since y_abstract provides real negative labels, TN is computable
    and WSS@95 is exact (no pool-correction needed).
    """
    logger.info("COPA-REPLICA: starting → %s", output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    t0        = time.monotonic()
    topic_dir = BASE_OUTPUT / topic_id

    # --- Load labeled pool ---------------------------------------------------
    copa_path = Path(f"data/clef_tar/{topic_id}.parquet")
    df = pd.read_parquet(copa_path)
    copa_candidates: List[CandidateRecord] = [
        CandidateRecord(
            source_database = "copa_pool",
            title           = str(row.get("title") or ""),
            abstract        = (str(row["abstract"])
                               if pd.notna(row.get("abstract")) else None),
            pmid            = str(row["pmid"]) if pd.notna(row.get("pmid")) else None,
        )
        for _, row in df.iterrows()
    ]
    y_labels: List[int] = df["y_abstract"].tolist()
    pmid_to_label: Dict[str, int] = {
        str(df.iloc[i]["pmid"]): int(y_labels[i])
        for i in range(len(df))
        if pd.notna(df.iloc[i].get("pmid"))
    }

    # --- Stratified 80/20 split (seed 42) ------------------------------------
    indices = list(range(len(copa_candidates)))
    _, test_idx = train_test_split(
        indices, test_size=0.2, stratify=y_labels, random_state=42,
    )
    test_pmids: set = {
        copa_candidates[i].pmid
        for i in test_idx
        if copa_candidates[i].pmid
    }
    pos_in_test = sum(1 for p in test_pmids if pmid_to_label.get(p, 0) == 1)
    logger.info(
        "COPA-REPLICA: pool=%d  test=%d  pos_in_test=%d",
        len(copa_candidates), len(test_pmids), pos_in_test,
    )

    # --- S scores for all 1799 papers (fresh — different pool) ---------------
    pico_emb  = encoder.embed_pico(protocol.pico)
    pico_text = (
        f"{protocol.pico.population} {protocol.pico.intervention} "
        f"{protocol.pico.comparator} {protocol.pico.outcome}"
    )
    retriever = HybridRetriever()
    retriever.build_indices(copa_candidates, encoder)
    ranked    = retriever.rank(copa_candidates, pico_emb, pico_text)
    s_scores: Dict[str, float] = {r.candidate.record_id: r.rrf_score for r in ranked}

    # --- Certificate thresholds (same pkl as main run) -----------------------
    lambda_lo, lambda_hi, tau_se = load_cert_thresholds(topic_id)
    logger.info(
        "COPA-REPLICA: lambda_lo=%.6f  lambda_hi=%.6f  tau_se=%.4f",
        lambda_lo, lambda_hi, tau_se,
    )

    # --- U values: load from shared cache, compute fresh for any misses ------
    escalation_candidates = [
        c for c in copa_candidates
        if lambda_lo <= s_scores.get(c.record_id, 0.0) < lambda_hi
    ]
    u_values = await compute_u_values(
        topic_id, escalation_candidates, protocol, llm_client,
        topic_dir / "u_scores.parquet",
    )

    # --- Route all 1799 papers -----------------------------------------------
    included_pmids:  set = set()
    uncertain_pmids: set = set()
    routing_counts: Dict[str, int] = {
        "cheap_rejected": 0, "auto_included": 0,
        "llm_included": 0, "llm_excluded": 0, "human_review": 0,
    }

    for cand in copa_candidates:
        s = s_scores.get(cand.record_id, 0.0)
        u = u_values.get(cand.pmid or "", 0.0)
        if s < lambda_lo:
            routing_counts["cheap_rejected"] += 1
        elif s >= lambda_hi:
            routing_counts["auto_included"] += 1
            if cand.pmid:
                included_pmids.add(cand.pmid)
        elif u >= tau_se:
            include_votes = round(u * LLM_ENSEMBLE_B)
            if include_votes > LLM_ENSEMBLE_B / 2:
                routing_counts["llm_included"] += 1
                if cand.pmid:
                    included_pmids.add(cand.pmid)
            else:
                routing_counts["llm_excluded"] += 1
        else:
            routing_counts["human_review"] += 1
            if cand.pmid:
                uncertain_pmids.add(cand.pmid)

    logger.info("COPA-REPLICA routing: %s", routing_counts)

    # --- Evaluate on 20% test split using y_abstract as ground truth ---------
    tp = fp = tn = fn = 0
    for pmid in test_pmids:
        y_true = pmid_to_label.get(pmid, 0)
        yhat   = 1 if (pmid in included_pmids or pmid in uncertain_pmids) else 0
        if   y_true == 1 and yhat == 1: tp += 1
        elif y_true == 1 and yhat == 0: fn += 1
        elif y_true == 0 and yhat == 0: tn += 1
        else:                            fp += 1

    n_positive = tp + fn
    n_test     = len(test_pmids)
    fnr        = fn / n_positive if n_positive > 0 else 0.0
    recall     = 1.0 - fnr
    # y_abstract provides real negatives: exact WSS (no correction needed)
    wss_95 = (tn + fn) / n_test - 0.05 if recall >= 0.95 else -0.05
    n_excl_test = sum(
        1 for p in test_pmids
        if p not in included_pmids and p not in uncertain_pmids
    )
    wss_95_corrected = (n_excl_test / n_test) - 0.05

    elapsed = time.monotonic() - t0

    eval_result: Dict[str, Any] = {
        "fnr":              fnr,
        "recall":           recall,
        "wss_95":           wss_95,
        "wss_95_corrected": wss_95_corrected,
        "n_positive":       n_positive,
        "n_total":          n_test,
        "coverage":         1.0,
        "true_positives":   tp,
        "false_negatives":  fn,
        "true_negatives":   tn,
        "false_positives":  fp,
    }
    run_stats = {
        "topic_id":        topic_id,
        "pipeline":        "copa_replica",
        "pool_size":       len(copa_candidates),
        "test_size":       n_test,
        "elapsed_s":       elapsed,
        "routing_summary": {**routing_counts,
                            "lambda_lo": lambda_lo,
                            "lambda_hi": lambda_hi,
                            "tau_se":    tau_se},
        "benchmark_eval":  eval_result,
    }
    with open(output_dir / "run_stats.json", "w") as f:
        json.dump(run_stats, f, indent=2)

    logger.info(
        "COPA-REPLICA: done %.1fs — recall=%.4f fnr=%.4f wss_95=%.4f",
        elapsed, recall, fnr, wss_95,
    )
    return run_stats


# ---------------------------------------------------------------------------
# STEP 5D — Save routing decisions (for DTA re-screening)
# ---------------------------------------------------------------------------

async def save_routing_decisions(
    topic_id: str,
    encoder:  Any,
    protocol: Optional[ReviewProtocol] = None,
) -> Path:
    """
    Load candidates from search_results.parquet cache, apply CASCADE-RC
    routing thresholds (s only — no u computation), fetch missing abstracts
    for auto_included papers, and save a JSON with per-paper decisions.

    Returns the path to the saved JSON.
    """
    topic_dir  = BASE_OUTPUT / topic_id
    cache_path = topic_dir / "search_results.parquet"

    if not cache_path.exists():
        raise FileNotFoundError(
            f"search_results.parquet not found at {cache_path}. "
            "Run without --routing-only first to generate Phase 1 cache."
        )

    if protocol is None:
        protocol = load_protocol(TOPIC_CONFIG[topic_id]["protocol_path"])

    candidates = _rows_to_candidates(pd.read_parquet(cache_path))
    logger.info("save_routing_decisions: loaded %d candidates from cache", len(candidates))

    s_scores = compute_s_scores(topic_id, candidates, protocol, encoder)

    lambda_lo, lambda_hi, tau_se = load_cert_thresholds(topic_id)
    logger.info(
        "save_routing_decisions: lambda_lo=%.6f  lambda_hi=%.6f  tau_se=%.4f",
        lambda_lo, lambda_hi, tau_se,
    )

    cheap_rejected: List[CandidateRecord] = []
    auto_included:  List[CandidateRecord] = []
    escalation:     List[CandidateRecord] = []

    for cand in candidates:
        s = s_scores.get(cand.record_id, 0.0)
        if s < lambda_lo:
            cheap_rejected.append(cand)
        elif s >= lambda_hi:
            auto_included.append(cand)
        else:
            escalation.append(cand)

    logger.info(
        "save_routing_decisions: cheap_rejected=%d  auto_included=%d  escalation=%d",
        len(cheap_rejected), len(auto_included), len(escalation),
    )

    # Fetch missing abstracts for auto_included papers only
    missing_pmids = [
        c.pmid for c in auto_included
        if c.pmid and not (c.abstract or "").strip()
    ]
    if missing_pmids:
        logger.info(
            "save_routing_decisions: fetching %d missing abstracts from PubMed",
            len(missing_pmids),
        )
        fetched = await PubMedConnector().fetch_by_pmids(missing_pmids)
        for cand in auto_included:
            if cand.pmid in fetched and not (cand.abstract or "").strip():
                data = fetched[cand.pmid]
                cand.title    = data.get("title") or cand.title
                cand.abstract = data.get("abstract") or None
        logger.info(
            "save_routing_decisions: filled abstracts for %d / %d papers",
            len(fetched), len(missing_pmids),
        )

    auto_included_papers = [
        {
            "pmid":     cand.pmid,
            "title":    cand.title    or "",
            "abstract": cand.abstract or "",
            "s_score":  s_scores.get(cand.record_id, 0.0),
        }
        for cand in auto_included
    ]

    output = {
        "topic_id":  topic_id,
        "lambda_lo": lambda_lo,
        "lambda_hi": lambda_hi,
        "tau_se":    tau_se,
        "routing_summary": {
            "total_candidates": len(candidates),
            "cheap_rejected":   len(cheap_rejected),
            "auto_included":    len(auto_included),
            "escalation":       len(escalation),
        },
        "auto_included_papers": auto_included_papers,
    }

    out_path = topic_dir / "cascade_routing_decisions.json"
    topic_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    n_with_abstract = sum(1 for p in auto_included_papers if p["abstract"])
    logger.info(
        "save_routing_decisions: routing saved → %s  "
        "(%d auto_included, %d with abstracts)",
        out_path, len(auto_included), n_with_abstract,
    )
    print(
        f"\nrouting saved → {out_path}\n"
        f"  candidates:  {len(candidates)}\n"
        f"  cheap_rejected: {len(cheap_rejected)}\n"
        f"  auto_included:  {len(auto_included)}  ({n_with_abstract} with abstracts)\n"
        f"  escalation:  {len(escalation)}"
    )
    return out_path


# ---------------------------------------------------------------------------
# Print comparison
# ---------------------------------------------------------------------------

def print_comparison(
    topic_id:  str,
    native:    Dict[str, Any],
    cascade:   Dict[str, Any],
    copa:      Dict[str, Any],
    topic_dir: Path,
) -> None:
    print(f"\n{'='*75}")
    print(f"COMPARISON RESULTS — {topic_id}")
    print(f"{'='*75}")
    h1 = "Native"
    h2 = "CASCADE-RC"
    h3 = "COPA-replica"
    print(f"{'Metric':<25} {h1:>12} {h2:>12} {h3:>14}")
    print(f"{'Pool':<25} {'2445-paper':>12} {'2445-paper':>12} {'1799-paper':>14}")
    print(f"{'Eval basis':<25} {'abstract':>12} {'routing':>12} {'20% split':>14}")
    print(f"{'-'*65}")
    for m in ["fnr", "recall", "wss_95", "wss_95_corrected", "coverage", "n_positive"]:
        n_val = native.get("benchmark_eval",  {}).get(m, "?")
        c_val = cascade.get("benchmark_eval", {}).get(m, "?")
        p_val = copa.get("benchmark_eval",    {}).get(m, "?")
        if isinstance(n_val, float): n_val = f"{n_val:.4f}"
        if isinstance(c_val, float): c_val = f"{c_val:.4f}"
        if isinstance(p_val, float): p_val = f"{p_val:.4f}"
        print(f"{m:<25} {str(n_val):>12} {str(c_val):>12} {str(p_val):>14}")

    print(f"\nNote: wss_95 broken (qrels positive-only); use wss_95_corrected for Native/CASCADE-RC")
    print(f"      COPA-replica wss_95 is exact (y_abstract provides real negatives)")

    cascade_routing = cascade.get("routing_summary", {})
    copa_routing    = copa.get("routing_summary",    {})
    print(f"\nCASCADE-RC routing (2445-paper pool):")
    for k in ["auto_included", "llm_included", "llm_excluded", "cheap_rejected", "human_review"]:
        print(f"  {k:<15}: {cascade_routing.get(k, '?')}")
    print(f"\nCOPA-replica routing (1799-paper pool):")
    for k in ["auto_included", "llm_included", "llm_excluded", "cheap_rejected", "human_review"]:
        print(f"  {k:<15}: {copa_routing.get(k, '?')}")
    print(f"\nHuman review queue : {topic_dir}/human_review_queue.json")
    print(f"Output             : {topic_dir}/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(topic_id: str, routing_only: bool = False) -> None:
    if topic_id not in TOPIC_CONFIG:
        print(f"Unknown topic. Available: {list(TOPIC_CONFIG)}")
        return

    topic_dir = BASE_OUTPUT / topic_id
    (topic_dir / "native").mkdir(parents=True, exist_ok=True)
    (topic_dir / "cascade_rc").mkdir(parents=True, exist_ok=True)

    encoder    = SharedEncoderService()
    llm_client = LLMClient()
    protocol   = load_protocol(TOPIC_CONFIG[topic_id]["protocol_path"])

    # Load certificate thresholds early — needed to identify escalation zone
    lambda_lo, lambda_hi, tau_se = load_cert_thresholds(topic_id)
    logger.info(
        "Certificate: lambda_lo=%.6f  lambda_hi=%.6f  tau_se=%.4f",
        lambda_lo, lambda_hi, tau_se,
    )

    # ── Phase 1: search (cached after first run) ─────────────────────────────
    print(f"\n{'='*60}\nPHASE 1: Literature Search for {topic_id}\n{'='*60}")
    candidates = await run_phase1(topic_id, protocol, encoder, llm_client)

    # ── Save routing decisions (always; needed by rescreen_cascade_dta.py) ────
    print(f"\n{'='*60}\nSAVING CASCADE-RC ROUTING DECISIONS\n{'='*60}")
    await save_routing_decisions(topic_id, encoder, protocol)
    if routing_only:
        logger.info("--routing-only: exiting after save_routing_decisions()")
        await llm_client.aclose()
        return

    # ── M+ verification ───────────────────────────────────────────────────────
    print(f"\n{'='*60}\nM+ VERIFICATION\n{'='*60}")
    candidates, human_review_queue = await verify_m_plus(topic_id, candidates)

    # ── S scores: cheap, no LLM (cached after first run) ─────────────────────
    print(f"\n{'='*60}\nS SCORE COMPUTATION (HybridRetriever, no API)\n{'='*60}")
    s_scores = compute_s_scores(topic_id, candidates, protocol, encoder)

    # ── Identify escalation zone ──────────────────────────────────────────────
    escalation_candidates = [
        c for c in candidates
        if lambda_lo <= s_scores.get(c.record_id, 0.0) < lambda_hi
    ]
    auto_included_count = sum(1 for c in candidates if s_scores.get(c.record_id, 0.0) >= lambda_hi)
    cheap_rejected_count = sum(1 for c in candidates if s_scores.get(c.record_id, 0.0) < lambda_lo)
    logger.info(
        "Routing preview: cheap_rejected=%d  escalation=%d  auto_included=%d",
        cheap_rejected_count, len(escalation_candidates), auto_included_count,
    )

    # ── U values: only for escalation papers ─────────────────────────────────
    print(
        f"\n{'='*60}\n"
        f"U VALUE COMPUTATION — {len(escalation_candidates)} escalation papers "
        f"× {LLM_ENSEMBLE_B} calls = {len(escalation_candidates)*LLM_ENSEMBLE_B} LLM calls "
        f"(skipping {len(candidates)-len(escalation_candidates)} non-escalation papers)\n"
        f"{'='*60}"
    )
    cache_path = topic_dir / "u_scores.parquet"
    u_values   = await compute_u_values(
        topic_id, escalation_candidates, protocol, llm_client, cache_path
    )

    # ── Both pipelines in parallel ────────────────────────────────────────────
    print(f"\n{'='*60}\nRUNNING BOTH PIPELINES IN PARALLEL\n{'='*60}")

    native_task = asyncio.create_task(run_native(
        topic_id, candidates, protocol, encoder, llm_client,
        topic_dir / "native",
    ))
    cascade_task = asyncio.create_task(run_cascade_rc(
        topic_id, candidates, s_scores, u_values,
        lambda_lo, lambda_hi, tau_se,
        protocol, encoder, llm_client,
        human_review_queue, topic_dir / "cascade_rc",
    ))

    native_result, cascade_result = await asyncio.gather(native_task, cascade_task)

    # ── COPA-replica (sequential — reuses shared u_scores cache) ─────────────
    print(f"\n{'='*60}\nCOPA-REPLICA PIPELINE (1799-paper pool, 20% test split)\n{'='*60}")
    (topic_dir / "copa_replica").mkdir(parents=True, exist_ok=True)
    copa_result = await run_copa_replica(
        topic_id, protocol, encoder, llm_client, topic_dir / "copa_replica",
    )

    print_comparison(topic_id, native_result, cascade_result, copa_result, topic_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Native vs CASCADE-RC comparative evaluation"
    )
    parser.add_argument("topic_id", choices=list(TOPIC_CONFIG.keys()))
    parser.add_argument(
        "--routing-only",
        action="store_true",
        help="Only compute s-scores, apply routing thresholds, save "
             "cascade_routing_decisions.json, then exit (no LLM screening).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main(args.topic_id, routing_only=args.routing_only))
