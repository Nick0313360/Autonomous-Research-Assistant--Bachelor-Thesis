from __future__ import annotations

from pathlib import Path
from typing import Any, List


def load_canonical_pmids(topic_path: Path) -> List[str]:
    """Return canonical PMIDs from a CLEF-TAR topic file or parquet.

    Parquet: reads the 'pmid' column, casts to str, drops nulls.
    Text: handles 'Pids:' header (one PMID per line) or plain PMID list.
    """
    if topic_path.suffix == ".parquet":
        import pandas as pd
        df = pd.read_parquet(topic_path, columns=["pmid"])
        return df["pmid"].dropna().astype(str).tolist()

    pmids: List[str] = []
    in_pids_section = False
    has_pids_header = False

    with topic_path.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.lower().startswith("pids:"):
                has_pids_header = True
                in_pids_section = True
                rest = stripped[5:].strip()
                if rest:
                    pmids.extend(p for p in rest.split() if p.isdigit())
                continue
            if in_pids_section:
                if not stripped:
                    in_pids_section = False
                    continue
                pmids.extend(p for p in stripped.split() if p.isdigit())
            elif not has_pids_header and stripped.isdigit():
                pmids.append(stripped)

    return pmids


def merge_with_canonical(
    fetched: list,
    canonical_pmids: List[str],
) -> list:
    """Return list covering ALL canonical PMIDs.

    PMIDs already in *fetched* keep their full CandidateRecord.
    Missing PMIDs get a minimal stub (empty title/abstract) so they
    are screened on empty content and correctly penalise recall.
    """
    from models.data_classes import CandidateRecord

    fetched_by_pmid: dict[str, Any] = {
        r.pmid: r for r in fetched if getattr(r, "pmid", None)
    }

    result = list(fetched)
    for pmid in canonical_pmids:
        if pmid not in fetched_by_pmid:
            result.append(
                CandidateRecord(
                    source_database="canonical",
                    title="",
                    pmid=pmid,
                    abstract="",
                )
            )
    return result


class QrelsLoader:
    @staticmethod
    def load(qrels_path: Path, topic_id: str = None) -> dict[str, int]:
        result: dict[str, int] = {}
        with qrels_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                if topic_id is not None and parts[0] != topic_id:
                    continue
                pmid = parts[2].strip()
                relevance = 1 if parts[3].strip() == "1" else 0
                result[pmid] = relevance
        return result


class BenchmarkEvaluator:
    def __init__(self, qrels: dict[str, int], alpha: float = 0.15) -> None:
        self._qrels = qrels
        self._alpha = alpha

    def evaluate(self, decisions: list) -> dict:
        true_positives = 0
        false_negatives = 0
        true_negatives = 0
        false_positives = 0

        qrels_positive_pmids: set[str] = {
            pmid for pmid, rel in self._qrels.items() if rel == 1
        }
        covered_positives: set[str] = set()

        for d in decisions:
            pmid: str = d.pmid
            val = (d.decision.value if hasattr(d.decision, "value") else str(d.decision)).lower()
            yhat = 0 if val == "exclude" else 1

            y = self._qrels.get(pmid)
            if y is None:
                continue

            if pmid in qrels_positive_pmids:
                covered_positives.add(pmid)

            if y == 1 and yhat == 1:
                true_positives += 1
            elif y == 1 and yhat == 0:
                false_negatives += 1
            elif y == 0 and yhat == 0:
                true_negatives += 1
            else:
                false_positives += 1

        n_positive = true_positives + false_negatives
        if n_positive == 0:
            return {"error": "no positives in qrels"}

        fnr = false_negatives / n_positive
        recall = 1.0 - fnr
        n_total = len(decisions)

        if recall >= 0.95:
            wss_95 = (true_negatives + false_negatives) / n_total - 0.05
        else:
            wss_95 = -0.05

        total_qrels_positives = len(qrels_positive_pmids)
        coverage = (
            len(covered_positives) / total_qrels_positives
            if total_qrels_positives > 0
            else 0.0
        )

        k = false_negatives
        n = n_positive
        ci_lo = 0.0
        ci_hi = 1.0
        try:
            from scipy.stats import beta
            ci_lo = float(beta.ppf(0.025, k, n - k + 1)) if k > 0 else 0.0
            ci_hi = float(beta.ppf(0.975, k + 1, n - k)) if k < n else 1.0
        except ImportError:
            pass

        return {
            "fnr": fnr,
            "recall": recall,
            "wss_95": wss_95,
            "n_positive": n_positive,
            "n_total": n_total,
            "coverage": coverage,
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "true_negatives": true_negatives,
            "false_positives": false_positives,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
        }
