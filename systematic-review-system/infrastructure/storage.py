"""
infrastructure/storage.py
=========================
Simple versioned JSON artifact store backed by the local filesystem.

Directory layout
----------------
data/reviews/{review_id}/
    queries/
        {artifact_type}_v{version}.json
    documents/
    results/
    reports/

Artifact types that don't map to one of the four known subfolders are
stored under a ``misc/`` subfolder so nothing is silently dropped.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subfolder routing
# ---------------------------------------------------------------------------

_SUBFOLDER: dict[str, str] = {
    "query":    "queries",
    "queries":  "queries",
    "document": "documents",
    "documents":"documents",
    "result":   "results",
    "results":  "results",
    "report":   "reports",
    "reports":  "reports",
}


def _subfolder_for(artifact_type: str) -> str:
    return _SUBFOLDER.get(artifact_type.lower(), "misc")


# ---------------------------------------------------------------------------
# VersionedStorage
# ---------------------------------------------------------------------------

class VersionedStorage:
    """
    Versioned JSON artifact store for one review run.

    Parameters
    ----------
    review_id : str
        Identifies the review; used as the leaf directory name.
    base_dir : Path, optional
        Root for all review data.  Defaults to ``data/reviews/``.
    """

    def __init__(
        self,
        review_id: str,
        base_dir: Optional[Path] = None,
    ) -> None:
        self._review_id = review_id
        root = (base_dir or Path("data") / "reviews") / review_id
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("VersionedStorage initialised at %s", self._root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, artifact_type: str, content: Any, version: str) -> Path:
        """
        Serialise *content* to JSON and save it under the appropriate subfolder.

        Parameters
        ----------
        artifact_type : str
            Logical type (e.g. "query", "result").  Determines the subfolder.
        content : Any
            Any JSON-serialisable value (dict, list, dataclass-dict, …).
        version : str
            Arbitrary version tag, e.g. ``"v1"``, ``"2024-01-15"``.

        Returns
        -------
        Path
            Absolute path of the written file.
        """
        dest = self._path_for(artifact_type, version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as fh:
            json.dump(content, fh, indent=2, default=str, ensure_ascii=False)
        logger.debug("Stored %s v%s → %s", artifact_type, version, dest)
        return dest

    def retrieve(self, artifact_type: str, version: str) -> Any:
        """
        Load and deserialise a previously stored artifact.

        Raises
        ------
        FileNotFoundError
            If the requested artifact/version does not exist.
        """
        src = self._path_for(artifact_type, version)
        if not src.exists():
            raise FileNotFoundError(
                f"No artifact '{artifact_type}' version '{version}' "
                f"found at {src}"
            )
        with src.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        logger.debug("Retrieved %s v%s from %s", artifact_type, version, src)
        return data

    def list_versions(self, artifact_type: str) -> List[str]:
        """
        Return a sorted list of available version tags for *artifact_type*.

        The version tag is extracted from the filename:
        ``{artifact_type}_v{version}.json``  →  ``v{version}``.
        """
        subfolder = _subfolder_for(artifact_type)
        folder = self._root / subfolder
        if not folder.exists():
            return []

        prefix = f"{artifact_type}_"
        versions: List[str] = []
        for p in sorted(folder.glob(f"{artifact_type}_*.json")):
            stem = p.stem  # e.g. "query_v3"
            version_tag = stem[len(prefix):]  # e.g. "v3"
            versions.append(version_tag)
        return versions

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _path_for(self, artifact_type: str, version: str) -> Path:
        subfolder = _subfolder_for(artifact_type)
        filename  = f"{artifact_type}_{version}.json"
        return self._root / subfolder / filename
