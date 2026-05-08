"""CLEF-TAR benchmark ingestion for CASCADE-RC validation."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Topic-to-family mapping for CLEF-TAR Task 2
# CD011975 and CD011145 appear in 2019 Training DTA (not Testing Intervention)
_TOPIC_FAMILY: dict[str, str] = {
    "CD008874": "DTA",
    "CD012080": "DTA",
    "CD012768": "DTA",
    "CD011768": "Intervention",
    "CD011975": "DTA",
    "CD011145": "DTA",
}

# "Testing" for 2019 test set; "Training" for 2019 training topics
_TOPIC_SPLIT: dict[str, str] = {
    "CD008874": "Testing",
    "CD012080": "Testing",
    "CD012768": "Testing",
    "CD011768": "Testing",
    "CD011975": "Training",
    "CD011145": "Training",
}

_ALLOWED_TOPICS: frozenset[str] = frozenset(_TOPIC_FAMILY)

_REPO_URL = "https://github.com/CLEF-TAR/tar.git"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "cascade_rc" / "tar"
_SPARSE_PATHS = ["2017-TAR", "2018-TAR", "2019-TAR/Task2"]

# Per-family aggregate qrel file name (2019 testing format)
_QREL_TEST_FILE = "qrel_abs_test.txt"
# Legacy qrel filenames per family/split
_QRELS_LEGACY: dict[tuple[str, str], str] = {
    ("DTA",          "Testing"):  "full.test.dta.abs.2019.qrels",
    ("DTA",          "Training"): "full.train.dta.abs.2019.qrels",
    ("Intervention", "Testing"):  "full.test.intervention.abs.2019.qrels",
    ("Intervention", "Training"): "full.train.int.abs.2019.qrels",
}

_M_PLUS_WARN_THRESHOLD = 26


@dataclass
class Topic:
    topic_id: str
    title: str
    boolean_query: str
    candidate_pmids: list[str]
    qrels_abstract: dict[str, int]


# ---------------------------------------------------------------------------
# TREC qrel parsing
# ---------------------------------------------------------------------------

def _parse_qrels_trec(path: Path) -> list[tuple[str, str, str, int]]:
    """Parse a TREC-format qrel file into (topic_id, iter, pmid, rel) tuples.

    Raises ValueError if any line has a relevance value outside {0, 1}.
    Empty lines and comment lines starting with '#' are skipped.
    """
    records: list[tuple[str, str, str, int]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ValueError(
                f"{path}:{lineno}: expected 4 whitespace-separated fields, got {len(parts)}: {line!r}"
            )
        topic_id, iter_val, pmid, rel_str = parts
        try:
            rel = int(rel_str)
        except ValueError:
            raise ValueError(
                f"{path}:{lineno}: relevance {rel_str!r} is not an integer"
            )
        if rel not in {0, 1}:
            raise ValueError(
                f"{path}:{lineno}: relevance {rel} outside {{0, 1}}"
            )
        records.append((topic_id, iter_val, pmid, rel))
    return records


def _parse_qrels(path: Path, topic_id: str) -> dict[str, int]:
    """Return pmid → relevance for a single topic from an aggregate qrel file."""
    return {
        pmid: rel
        for t, _, pmid, rel in _parse_qrels_trec(path)
        if t == topic_id
    }


# ---------------------------------------------------------------------------
# Topic-file parsing
# ---------------------------------------------------------------------------

def _parse_topic_file(path: Path) -> tuple[str, str, list[str]]:
    title = ""
    query_lines: list[str] = []
    pids: list[str] = []
    state = "start"

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("Title:"):
            title = line[len("Title:"):].strip()
            state = "title"
        elif line.startswith("Query:"):
            state = "query"
        elif line.startswith("Pids:"):
            state = "pids"
        elif state == "query" and line:
            query_lines.append(line)
        elif state == "pids" and line.isdigit():
            pids.append(line)

    return title, "\n".join(query_lines), pids


def _parse_topic_2017(data_dir: Path, topic_id: str) -> tuple[str, str, list[str]]:
    """Parse a 2017-TAR topic from extracted_data .pids and .title files.

    The 2017 format stores candidates in a .pids file (one 'TOPIC_ID PMID' per
    line) and the title in a .title file (one 'TOPIC_ID <title text>' line).
    Searches both testing/ and training/ subdirectories.
    """
    for subdir in ("testing", "training"):
        base = data_dir / "2017-TAR" / subdir / "extracted_data"
        pids_path  = base / f"{topic_id}.pids"
        title_path = base / f"{topic_id}.title"
        if not pids_path.exists():
            continue

        pids: list[str] = []
        for line in pids_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[0] == topic_id:
                pids.append(parts[1])

        title = ""
        if title_path.exists():
            for line in title_path.read_text(encoding="utf-8").splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0] == topic_id:
                    title = parts[1]
                    break

        return title, "", pids  # 2017 format has no inline boolean query

    raise FileNotFoundError(
        f"2017-TAR topic files for {topic_id} not found under {data_dir}/2017-TAR/"
    )


# ---------------------------------------------------------------------------
# Duplication audit
# ---------------------------------------------------------------------------

def _collect_topic_ids(qrels_dir: Path) -> set[str]:
    """Return all unique topic_ids found in every qrel file under qrels_dir."""
    topic_ids: set[str] = set()
    if not qrels_dir.exists():
        return topic_ids
    for qrel_file in qrels_dir.iterdir():
        if not qrel_file.is_file():
            continue
        for line in qrel_file.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) >= 1:
                topic_ids.add(parts[0])
    return topic_ids


def detect_topic_duplications(
    data_dir: Path,
    families: list[str],
    audit_path: Path,
) -> dict[str, Any]:
    """Detect topics that appear in 2019 training and in 2018 data.

    Writes the audit dict to audit_path as JSON and returns it.
    Per Stevenson & Bin-Hezam (2023), 2019 DTA training == 2018 DTA test+train.
    """
    audit: dict[str, Any] = {
        "duplicates": {},
        "dta_2019_train_equals_2018_union": False,
    }

    for family in families:
        train_2018 = _collect_topic_ids(
            data_dir / "2018-TAR" / "Task2" / "Training" / family / "qrels"
        )
        test_2018 = _collect_topic_ids(
            data_dir / "2018-TAR" / "Task2" / "Testing" / family / "qrels"
        )
        train_2019 = _collect_topic_ids(
            data_dir / "2019-TAR" / "Task2" / "Training" / family / "qrels"
        )
        union_2018 = train_2018 | test_2018
        duplicates = train_2019 & union_2018
        audit["duplicates"][family] = sorted(duplicates)

        if family == "DTA":
            audit["dta_2019_train_equals_2018_union"] = (train_2019 == union_2018)

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Topic duplication audit written to %s", audit_path)
    return audit


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_clef_tar_2019(
    target_dir: Path | None = None,
) -> Path:
    """Sparse-clone 2017-TAR/, 2018-TAR/, 2019-TAR/Task2/ from CLEF-TAR/tar.

    Uses target_dir (default: ~/.cache/cascade_rc/tar/).
    Idempotent: returns immediately if 2019-TAR already exists.
    Returns the effective target_dir.
    """
    if target_dir is None:
        target_dir = _DEFAULT_CACHE_DIR
    if (target_dir / "2019-TAR").exists():
        return target_dir

    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "tar"

        result = subprocess.run(
            [
                "git", "clone",
                "--depth=1", "--filter=blob:none", "--sparse",
                _REPO_URL, str(clone_dir),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr}")

        result = subprocess.run(
            ["git", "sparse-checkout", "set"] + _SPARSE_PATHS,
            cwd=str(clone_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git sparse-checkout failed:\n{result.stderr}")

        for subdir in ("2017-TAR", "2018-TAR", "2019-TAR"):
            src = clone_dir / subdir
            if src.exists():
                shutil.move(str(src), str(target_dir / subdir))

    return target_dir


# ---------------------------------------------------------------------------
# load_topic
# ---------------------------------------------------------------------------

def load_topic(
    topic_id: str,
    data_dir: Path,
    family: str | None = None,
) -> Topic:
    """Parse a CLEF-TAR 2019 topic from data_dir/2019-TAR/Task2/Testing/<family>/.

    family defaults to the value in _TOPIC_FAMILY; supply it explicitly in tests
    or when using non-standard topic IDs.
    """
    if topic_id not in _ALLOWED_TOPICS and family is None:
        raise ValueError(
            f"Unknown topic_id {topic_id!r}. Allowed: {sorted(_ALLOWED_TOPICS)}"
        )

    resolved_family = family if family is not None else _TOPIC_FAMILY[topic_id]
    resolved_split  = _TOPIC_SPLIT.get(topic_id, "Testing")
    base = data_dir / "2019-TAR" / "Task2" / resolved_split / resolved_family
    if not base.exists():
        raise FileNotFoundError(
            f"CLEF-TAR data not found at {base}. Run download_clef_tar_2019() first."
        )

    # Resolve qrels: prefer canonical name, then family/split-specific legacy name.
    qrels_path = base / "qrels" / _QREL_TEST_FILE
    if not qrels_path.exists():
        legacy_name = _QRELS_LEGACY.get((resolved_family, resolved_split))
        legacy = base / "qrels" / legacy_name if legacy_name else None
        if legacy is not None and legacy.exists():
            qrels_path = legacy
        else:
            raise FileNotFoundError(
                f"Qrels file not found at {base / 'qrels'}. Re-run download."
            )

    # Resolve topic (candidate PMIDs): try 2019 path first, then 2017-TAR.
    topic_path = base / "topics" / topic_id
    if topic_path.exists():
        title, boolean_query, candidate_pmids = _parse_topic_file(topic_path)
    else:
        logger.warning(
            "Topic file not found at %s — falling back to 2017-TAR format.", topic_path
        )
        title, boolean_query, candidate_pmids = _parse_topic_2017(data_dir, topic_id)
    qrels_abstract = _parse_qrels(qrels_path, topic_id)

    m_plus = sum(v for v in qrels_abstract.values() if v == 1)
    if m_plus < _M_PLUS_WARN_THRESHOLD:
        logger.warning(
            "Topic %s has only m₊=%d positives (threshold %d) — consider excluding.",
            topic_id, m_plus, _M_PLUS_WARN_THRESHOLD,
        )

    return Topic(
        topic_id=topic_id,
        title=title,
        boolean_query=boolean_query,
        candidate_pmids=candidate_pmids,
        qrels_abstract=qrels_abstract,
    )


# ---------------------------------------------------------------------------
# Abstract fetch (sync, legacy — new async version is in pubmed_fetch.py)
# ---------------------------------------------------------------------------

def fetch_abstracts(pmids: list[str], cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Fetch title+abstract for each PMID from PubMed (MEDLINE format), caching in cache_dir."""
    import time

    _CHUNK_SIZE = 500

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "abstracts.jsonl"

    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rec = json.loads(line)
                cache[rec["pmid"]] = rec

    missing = [p for p in pmids if p not in cache]

    if missing:
        from Bio import Entrez, Medline
        from tier1_search.pubmed_connector import PubMedConnector
        PubMedConnector()

        new_records: list[dict] = []
        for start in range(0, len(missing), _CHUNK_SIZE):
            if start > 0:
                time.sleep(0.35)
            chunk = missing[start : start + _CHUNK_SIZE]
            try:
                handle = Entrez.efetch(
                    db="pubmed", id=chunk, rettype="medline", retmode="text",
                )
                try:
                    for rec in Medline.parse(handle):
                        pmid = rec.get("PMID", "").strip()
                        title = rec.get("TI", "").strip()
                        abstract = rec.get("AB", "").strip()
                        if pmid:
                            entry = {"pmid": pmid, "title": title, "abstract": abstract}
                            cache[pmid] = entry
                            new_records.append(entry)
                finally:
                    handle.close()
            except Exception as exc:
                logger.warning("fetch_abstracts: chunk at offset %d failed: %s", start, exc)

        if new_records:
            with cache_path.open("a", encoding="utf-8") as f:
                for rec in new_records:
                    f.write(json.dumps(rec) + "\n")

    return {
        p: cache[p]
        for p in pmids
        if p in cache and cache[p].get("title") and cache[p].get("abstract")
    }


# ---------------------------------------------------------------------------
# Parquet output
# ---------------------------------------------------------------------------

def _validate_parquet_schema(path: Path) -> None:
    import pyarrow.dataset as ds
    schema = ds.dataset(path).schema
    required = {"pmid", "title", "abstract", "y_abstract", "is_calib"}
    actual = set(schema.names)
    missing = required - actual
    if missing:
        raise ValueError(f"Parquet {path} is missing columns: {missing}")
    logger.info(
        "%s schema OK: %d fields — %s",
        path.name,
        len(schema),
        ", ".join(schema.names),
    )


def _write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    import pandas as pd
    df = pd.DataFrame(rows, columns=["pmid", "title", "abstract", "y_abstract", "is_calib"])
    df["y_abstract"] = df["y_abstract"].astype("int8")
    df["is_calib"] = df["is_calib"].astype("int8")
    # abstract may be None for withdrawn PMIDs — keep as object dtype (nullable string)
    df.to_parquet(path, index=False)
    _validate_parquet_schema(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import asyncio
    import sys

    parser = argparse.ArgumentParser(
        description="Ingest CLEF-TAR 2019 topics into parquet for CASCADE-RC."
    )
    parser.add_argument(
        "--topics",
        nargs="+",
        choices=sorted(_ALLOWED_TOPICS),
        metavar="TOPIC_ID",
        help=f"Topic IDs to process. Choices: {sorted(_ALLOWED_TOPICS)}. Default: all.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artefacts/cascade_rc/data"),
        help="Output directory for parquet files.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing the TAR/ trees (default: ~/.cache/cascade_rc/tar/).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download_clef_tar_2019.",
    )
    parser.add_argument(
        "--calib-frac",
        type=float,
        default=0.5,
        help="Calibration fraction for stratified split (default 0.5).",
    )
    parser.add_argument(
        "--split-seed",
        type=int,
        default=20260429,
        help="Random seed for stratified split.",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("artefacts/cascade_rc/data/topic_audit.json"),
        help="Path for the topic duplication audit JSON.",
    )
    args = parser.parse_args()

    topics: list[str] = args.topics or sorted(_ALLOWED_TOPICS)
    data_dir: Path = args.data_dir or _DEFAULT_CACHE_DIR

    if not args.skip_download:
        data_dir = download_clef_tar_2019(data_dir)

    # Emit duplication audit before processing
    detect_topic_duplications(data_dir, families=list({_TOPIC_FAMILY[t] for t in topics}), audit_path=args.audit)

    args.out.mkdir(parents=True, exist_ok=True)

    from cascade_rc.data.pubmed_fetch import fetch_abstracts as async_fetch
    from cascade_rc.data.splits import stratified_calib_test_split
    from cascade_rc.config import CascadeRCConfig

    cfg = CascadeRCConfig()

    for topic_id in topics:
        topic = load_topic(topic_id, data_dir)
        abstracts: dict[str, dict] = asyncio.run(
            async_fetch(
                list(topic.candidate_pmids),
                email=cfg.ncbi_email,
                api_key=cfg.ncbi_api_key,
                cache_dir=args.out / "pubmed",
            )
        )

        rows: list[dict] = []
        for pmid, qrel in topic.qrels_abstract.items():
            ab_rec = abstracts.get(pmid)
            rows.append(
                {
                    "pmid": pmid,
                    "title": ab_rec["title"] if ab_rec else "",
                    "abstract": ab_rec["abstract"] if ab_rec else None,
                    "y_abstract": qrel,
                    "is_calib": 0,  # placeholder; overwritten by split below
                }
            )

        import pandas as pd
        df = pd.DataFrame(rows)
        df["y_abstract"] = df["y_abstract"].astype("int8")
        df["is_calib"] = df["is_calib"].astype("int8")

        split_path = args.out / "splits" / f"{topic_id}.parquet"
        calib_df, test_df = stratified_calib_test_split(
            df,
            calib_frac=args.calib_frac,
            fallback_8020_when_m_plus_at_least=26,
            seed=args.split_seed,
            out_path=split_path,
        )

        # Merge is_calib back onto original pmid order for the final parquet
        is_calib_map: dict[str, int] = {}
        for _, row in calib_df.iterrows():
            is_calib_map[row["pmid"]] = 1
        for _, row in test_df.iterrows():
            is_calib_map[row["pmid"]] = 0

        final_rows = [
            {
                "pmid": r["pmid"],
                "title": r["title"],
                "abstract": r["abstract"],
                "y_abstract": r["y_abstract"],
                "is_calib": is_calib_map.get(r["pmid"], 0),
            }
            for r in rows
        ]

        out_path = args.out / f"{topic_id}.parquet"
        _write_parquet(final_rows, out_path)

        n_pos = sum(1 for r in rows if r["y_abstract"] == 1)
        n_neg = sum(1 for r in rows if r["y_abstract"] == 0)
        abstract_cov = sum(1 for r in rows if r["abstract"]) / len(rows) if rows else 0.0
        print(
            f"{topic_id}  total={len(rows)}  pos={n_pos}  neg={n_neg}"
            f"  prevalence={n_pos/len(rows):.4f}  abstract_cov={abstract_cov:.2%}"
        )
        if not rows:
            print(
                f"WARNING: {topic_id} produced 0 rows — check Entrez credentials and network.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
