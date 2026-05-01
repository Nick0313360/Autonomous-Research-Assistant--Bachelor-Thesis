"""Subprocess wrapper for the vendored CLEF TAR evaluation script.

Output format: each line is {topic_id}\t{metric_name}\t{value} (3 decimal float).
The script requires two positional args: <qrel_file> <results_file>.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_VENDOR_SCRIPT: Path = (
    Path(__file__).parent.parent / "baselines" / "tar_eval_vendor" / "tar_eval.py"
)

# Keys confirmed by running the vendored script (Step 3 of Task 5).
# Observed output from: python tar_eval.py <qrel> <results>
# Recall appears as "r" (not "recall") in tar_eval output.
REQUIRED_KEYS: frozenset[str] = frozenset({"wss_100", "wss_95", "r", "norm_area"})


def run_tar_eval(
    qrels_file: Path,
    results_file: Path,
    timeout: int = 300,
) -> dict[str, float]:
    """Run vendored CLEF tar_eval.py and return parsed metric dict.

    Captures both stdout and stderr. Logs stderr lines at WARNING level.
    Parses stdout by splitting on tab (3 fields per line: topic, metric, value).
    Returns aggregated metrics (last occurrence of each metric key wins,
    which corresponds to the overall aggregate printed last by TarAggRuler).

    Args:
        qrels_file:   Path to TREC-format qrel file.
        results_file: Path to TREC-format results file.
        timeout:      Max subprocess runtime in seconds.

    Returns:
        dict mapping metric_name -> float.

    Raises:
        subprocess.TimeoutExpired: script exceeded timeout.
        RuntimeError: script exited non-zero.
        ValueError: REQUIRED_KEYS missing from parsed output.
    """
    proc = subprocess.run(
        ["python3", str(_VENDOR_SCRIPT), str(qrels_file), str(results_file)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    for line in proc.stderr.splitlines():
        logger.warning("tar_eval stderr: %s", line)

    if proc.returncode != 0:
        raise RuntimeError(
            f"tar_eval.py exited {proc.returncode}:\n{proc.stderr[:500]}"
        )

    parsed: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 3:
            continue
        _topic_id, metric, value_str = parts
        try:
            parsed[metric] = float(value_str)
        except ValueError:
            continue

    missing = REQUIRED_KEYS - set(parsed)
    if missing:
        raise ValueError(
            f"tar_eval output missing required keys: {missing!r}\n"
            f"Got keys: {sorted(parsed)!r}\n"
            f"Raw stdout (first 500 chars):\n{proc.stdout[:500]}"
        )

    return parsed
