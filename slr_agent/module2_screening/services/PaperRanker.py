from typing import Dict, List, Optional, Tuple
import numpy as np
from module1.model.Paper import Paper
from module2_screening.model.screening_models import RankedPaper 
from your_module import _emitLog  # or define it, or use a local logging function

class PaperRanker:
    """
    Module 2::Layer::PaperRanker  (NEW — add to class diagram)

    L1 in the new architecture. Stateless.

    Ranks all papers by cosine similarity to the PICO query embedding and
    applies a lenient threshold to exclude only obviously irrelevant papers.

    The threshold θ is deliberately loose (default 0.10). The intent is to
    eliminate only papers with essentially no semantic overlap with the research
    question — not to pre-select for relevance. Any paper above the floor
    proceeds to LLM evaluation in L2.

    Stateless: no model loaded, no side effects. Pure NumPy computation.
    """

    def rank(
        self,
        paperEmbeddings: Dict[str, np.ndarray],
        picoEmbedding:   np.ndarray,
        papers:          List[Paper],
        threshold:       float = 0.10,
        emitLog:         Optional[callable] = None,
    ) -> Tuple[List[RankedPaper], List[str]]:
        """
        Rank papers by cosine similarity to PICO and split at threshold.

        Algorithm:
          1. Build matrix (N, 768) from paperEmbeddings values (L2-normalised)
          2. Compute cosine similarity as matrix @ pico_vec (dot product on
             unit sphere — equivalent to cosine similarity)
          3. Sort descending by score
          4. Split: sim >= threshold → retained; sim < threshold → excluded_ids

        Args:
          paperEmbeddings: Dict[paperId → np.ndarray (768,)] from EmbeddingService
          picoEmbedding:   np.ndarray (768,) L2-normalised PICO vector
          papers:          List[Paper] in the same order as the embedding dict
                           (needed to reconstruct RankedPaper objects)
          threshold:       Minimum cosine similarity to retain a paper.
                           Suggest 0.05–0.15; calibrate on dev set to ≥97% recall.
          emitLog:         Optional SSE emitter callable.

        Returns:
          retained:         List[RankedPaper] sorted descending by simScore
          excluded_ids:     List[str] paper IDs below threshold
        """
        if not paperEmbeddings:
            return [], []

        # Build aligned lists so indices correspond
        ids      = list(paperEmbeddings.keys())
        matrix   = np.stack([paperEmbeddings[pid] for pid in ids])  # (N, 768)
        scores   = matrix @ picoEmbedding  # (N,) — cosine sim on unit sphere

        # Build a paperId → Paper lookup for RankedPaper construction
        paperLookup: Dict[str, Paper] = {}
        for paper in papers:
            pid = _makePaperIdStatic(paper)
            paperLookup[pid] = paper

        retained:     List[RankedPaper] = []
        excludedIds:  List[str]         = []

        for i in np.argsort(scores)[::-1]:   # descending by similarity
            pid   = ids[i]
            score = float(scores[i])
            if score < threshold:
                excludedIds.append(pid)
            else:
                paper = paperLookup.get(pid)
                if paper is None:
                    continue
                retained.append(RankedPaper(
                    paper=paper,
                    embedding=matrix[i],
                    simScore=score,
                    paperId=pid,
                ))

        _emitLog(
            emitLog,
            f"L1 RankingLayer: retained={len(retained)} "
            f"excluded_low_sim={len(excludedIds)} (θ={threshold})",
        )
        return retained, excludedIds


def _makePaperIdStatic(paper: Paper) -> str:
    """
    Module-level helper mirroring EmbeddingService._makePaperId().
    Used by PaperRanker which does not hold an EmbeddingService reference.
    """
    if paper.doi:
        return paper.doi.strip().lower().replace("/", "_")
    import hashlib
    raw = (paper.title + paper.abstract).encode("utf-8")
    return "hash_" + hashlib.sha256(raw).hexdigest()[:16]
