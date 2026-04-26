from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from sklearn.preprocessing import normalize
import logging

from module2_screening.services.EmbeddingService import EmbeddingLayer
from module1.model.Paper import Paper
from module1.model.SearchQuery import SearchQuery

log = logging.getLogger(__name__)

class EmbeddingService:
    """
    Module 2::Layer::EmbeddingService  (NEW — add to class diagram)

    L0 in the new architecture. Thin wrapper around EmbeddingLayer from the
    old architecture. All embedding logic (model loading, batching, CLS pooling,
    PICO document construction) is delegated to EmbeddingLayer unchanged.

    Adds over EmbeddingLayer:
      - Disk caching: embeddings persisted to cacheDir as .npy files so
        subsequent runs on the same paper pool skip GPU computation entirely.
      - paperId generation: a stable string ID for each paper used as dict
        key throughout the pipeline. Derived from doi if present, else
        a hash of (title + abstract).
      - Returns Dict[paperId → np.ndarray] instead of List[EmbeddedPaper],
        matching the new architecture's data flow spec.

    Attributes:
      _layer    — EmbeddingLayer; the actual transformer + tokenizer
      _cacheDir — Optional[Path]; if set, cache .npy files here
    """

    def __init__(
        self,
        modelKey:  Optional[str] = None,
        cacheDir:  Optional[str] = None,
        device:    str = "auto",
    ):
        """
        Initialise the embedding service.

        Args:
          modelKey: Force a specific model ("specter2" | "medcpt").
                    None = auto-detect from SearchQuery via selectModel().
          cacheDir: Path to directory for embedding cache files.
                    If None, caching is disabled.
          device:   "auto" uses CUDA if available, else CPU.
        """
        self._layer    = EmbeddingLayer(modelKey=modelKey, device=device)
        self._cacheDir = Path(cacheDir) if cacheDir else None
        if self._cacheDir:
            self._cacheDir.mkdir(parents=True, exist_ok=True)

    def selectModel(self, query: SearchQuery) -> str:
        """
        Delegate to EmbeddingLayer.selectModel().
        Returns "medcpt" for biomedical topics, "specter2" otherwise.
        """
        return self._layer.selectModel(query)

    def embedPapers(
        self,
        papers:   List[Paper],
        modelKey: str,
        batchSize: int = 32,
    ) -> Dict[str, np.ndarray]:
        """
        Embed all papers and return a paperId→embedding mapping.

        For each paper:
          1. Generate paperId (doi if present, else hash of title+abstract)
          2. If cacheDir is set and .npy file exists: load from disk
          3. Otherwise: delegate to EmbeddingLayer.embedPapers() in batches
          4. If cacheDir is set: persist embeddings to disk

        Args:
          papers:    List[Paper] from Module 1 deduplication output.
          modelKey:  "specter2" | "medcpt" — must match what embedQuery() uses.
          batchSize: Papers per GPU batch.

        Returns:
          Dict mapping paperId → np.ndarray (768,) float32, L2-normalised.
        """
        # Separate cached from uncached
        result:        Dict[str, np.ndarray] = {}
        uncached:      List[Paper]           = []
        uncachedIds:   List[str]             = []

        for paper in papers:
            pid = self._makePaperId(paper)
            cached = self._loadCache(pid, modelKey)
            if cached is not None:
                result[pid] = cached
            else:
                uncached.append(paper)
                uncachedIds.append(pid)

        if uncached:
            # EmbeddingLayer returns List[EmbeddedPaper] — extract embeddings
            embedded = self._layer.embedPapers(uncached, modelKey, batchSize)
            for pid, ep in zip(uncachedIds, embedded):
                vec = normalize(ep.embedding.reshape(1, -1))[0].astype(np.float32)
                result[pid] = vec
                self._saveCache(pid, modelKey, vec)

        log.info(
            "EmbeddingService: %d papers embedded (%d from cache, %d computed)",
            len(papers), len(papers) - len(uncached), len(uncached),
        )
        return result

    def embedQuery(self, query: SearchQuery, modelKey: str) -> np.ndarray:
        """
        Embed the PICO query document.
        Delegates to EmbeddingLayer.embedQuery() unchanged.
        Returns L2-normalised (768,) float32 vector.
        """
        vec = self._layer.embedQuery(query, modelKey)
        return normalize(vec.reshape(1, -1))[0].astype(np.float32)

    def makePaperIds(self, papers: List[Paper]) -> List[str]:
        """
        Generate stable paperId strings for a list of papers.
        Exposed publicly so DecisionAggregator can look up original Paper
        objects by ID without holding references to EmbeddedPaper.
        """
        return [self._makePaperId(p) for p in papers]

    # ── private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _makePaperId(paper: Paper) -> str:
        """
        Generate a stable string ID for a paper.
        Uses DOI if present (canonical, collision-free).
        Falls back to a hash of (title + abstract) for papers without DOI.
        """
        if paper.doi:
            return paper.doi.strip().lower().replace("/", "_")
        import hashlib
        raw = (paper.title + paper.abstract).encode("utf-8")
        return "hash_" + hashlib.sha256(raw).hexdigest()[:16]

    def _cachePath(self, paperId: str, modelKey: str) -> Optional[Path]:
        """Return the .npy path for this paperId + modelKey, or None if no cache."""
        if not self._cacheDir:
            return None
        safe_id = paperId.replace("/", "_").replace(":", "_")
        return self._cacheDir / f"{modelKey}_{safe_id}.npy"

    def _loadCache(self, paperId: str, modelKey: str) -> Optional[np.ndarray]:
        """Load cached embedding from disk. Returns None on cache miss."""
        path = self._cachePath(paperId, modelKey)
        if path and path.exists():
            try:
                return np.load(str(path))
            except Exception:
                return None
        return None

    def _saveCache(self, paperId: str, modelKey: str, vec: np.ndarray) -> None:
        """Persist embedding to disk. Silent failure (non-critical)."""
        path = self._cachePath(paperId, modelKey)
        if path:
            try:
                np.save(str(path), vec)
            except Exception:
                pass
