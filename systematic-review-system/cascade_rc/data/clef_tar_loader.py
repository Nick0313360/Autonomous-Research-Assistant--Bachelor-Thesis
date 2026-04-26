"""CLEF-TAR 2019 benchmark ingestion for CASCADE-RC validation."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ALLOWED_TOPICS: frozenset[str] = frozenset({"CD008874", "CD012080", "CD012768"})
_DTA_BASE = Path("2019-TAR") / "Task2" / "Testing" / "DTA"
_QRELS_FILE = "full.test.dta.abs.2019.qrels"
_REPO_URL = "https://github.com/CLEF-TAR/tar.git"
_CHUNK_SIZE = 500


@dataclass
class Topic:
    topic_id: str
    title: str
    boolean_query: str
    candidate_pmids: list[str]
    qrels_abstract: dict[str, int]


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


def _parse_qrels(path: Path, topic_id: str) -> dict[str, int]:
    qrels: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == topic_id:
            qrels[parts[2]] = int(parts[3])
    return qrels


def download_clef_tar_2019(target_dir: Path) -> None:
    """Sparse-clone the 2019-TAR subtree from CLEF-TAR/tar into target_dir.

    Idempotent: exits immediately if target_dir/2019-TAR already exists.
    Raises RuntimeError if git returns a non-zero exit code.
    """
    if (target_dir / "2019-TAR").exists():
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "tar"

        result = subprocess.run(
            [
                "git", "clone",
                "--depth=1", "--filter=blob:none", "--sparse",
                _REPO_URL, str(clone_dir),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr}")

        result = subprocess.run(
            ["git", "sparse-checkout", "set", "2019-TAR"],
            cwd=str(clone_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git sparse-checkout failed:\n{result.stderr}")

        shutil.move(str(clone_dir / "2019-TAR"), str(target_dir / "2019-TAR"))


def fetch_abstracts(pmids: list[str], cache_dir: Path) -> dict[str, dict]:
    """Fetch title+abstract for each PMID from PubMed, caching results in
    cache_dir/abstracts.jsonl (one JSON object per line, keyed by 'pmid').

    Reuses PubMedConnector to configure Entrez credentials from env/.env.
    PMIDs with no title or no abstract are excluded from the returned dict.
    """
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
        PubMedConnector()  # configures Entrez.email + Entrez.api_key from env

        new_records: list[dict] = []
        for start in range(0, len(missing), _CHUNK_SIZE):
            chunk = missing[start : start + _CHUNK_SIZE]
            try:
                handle = Entrez.efetch(
                    db="pubmed",
                    id=chunk,
                    rettype="medline",
                    retmode="text",
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
            time.sleep(0.35)

        if new_records:
            with cache_path.open("a", encoding="utf-8") as f:
                for rec in new_records:
                    f.write(json.dumps(rec) + "\n")

    return {
        p: cache[p]
        for p in pmids
        if p in cache and cache[p].get("title") and cache[p].get("abstract")
    }


def load_topic(topic_id: str, data_dir: Path) -> Topic:
    """Parse a CLEF-TAR 2019 DTA topic from data_dir/2019-TAR/Task2/Testing/DTA/."""
    if topic_id not in _ALLOWED_TOPICS:
        raise ValueError(
            f"Unknown topic_id {topic_id!r}. Allowed: {sorted(_ALLOWED_TOPICS)}"
        )
    base = data_dir / _DTA_BASE
    if not base.exists():
        raise FileNotFoundError(f"CLEF-TAR data not found at {base}. Run download first.")

    topic_path = base / "topics" / topic_id
    qrels_path = base / "qrels" / _QRELS_FILE

    if not topic_path.exists():
        raise FileNotFoundError(f"Topic file not found: {topic_path}")

    title, boolean_query, candidate_pmids = _parse_topic_file(topic_path)
    qrels_abstract = _parse_qrels(qrels_path, topic_id)

    return Topic(
        topic_id=topic_id,
        title=title,
        boolean_query=boolean_query,
        candidate_pmids=candidate_pmids,
        qrels_abstract=qrels_abstract,
    )


def _write_parquet(rows: list[dict], path: Path) -> None:
    import pandas as pd
    df = pd.DataFrame(rows, columns=["pmid", "title", "abstract", "y_abstract"])
    df["y_abstract"] = df["y_abstract"].astype("int8")
    df.to_parquet(path, index=False)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest CLEF-TAR 2019 DTA topics into parquet for CASCADE-RC."
    )
    parser.add_argument(
        "--topic",
        action="append",
        dest="topics",
        choices=sorted(_ALLOWED_TOPICS),
        metavar="TOPIC_ID",
        help="Topic ID to process (repeatable). Default: all three.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for parquet files and abstract cache.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing the 2019-TAR/ tree (default: same as --out).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download_clef_tar_2019 (use when data already present).",
    )
    args = parser.parse_args()

    topics: list[str] = args.topics or sorted(_ALLOWED_TOPICS)
    data_dir: Path = args.data_dir or args.out

    if not args.skip_download:
        download_clef_tar_2019(data_dir)

    args.out.mkdir(parents=True, exist_ok=True)

    for topic_id in topics:
        topic = load_topic(topic_id, data_dir)
        abstracts = fetch_abstracts(topic.candidate_pmids, args.out / "cache")

        rows: list[dict] = []
        for pmid, qrel in topic.qrels_abstract.items():
            if pmid in abstracts:
                rows.append(
                    {
                        "pmid": pmid,
                        "title": abstracts[pmid]["title"],
                        "abstract": abstracts[pmid]["abstract"],
                        "y_abstract": qrel,
                    }
                )

        out_path = args.out / f"{topic_id}.parquet"
        _write_parquet(rows, out_path)

        n_pos = sum(1 for r in rows if r["y_abstract"] == 1)
        n_neg = sum(1 for r in rows if r["y_abstract"] == 0)
        total = len(rows)
        prevalence = n_pos / total if total else 0.0
        print(
            f"{topic_id}  total={total}  pos={n_pos}  neg={n_neg}"
            f"  prevalence={prevalence:.4f}"
        )


if __name__ == "__main__":
    main()
