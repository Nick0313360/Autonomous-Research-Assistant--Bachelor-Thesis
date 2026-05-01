from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

M_GRID_CANDIDATES: list[int] = [26, 35, 50, 75, 100]

PARQUET_SCHEMA: dict[str, str] = {
    "topic_id": "object",
    "m_target": "int64",
    "m_actual": "int64",
    "abstention": "bool",
    "wss_95": "float64",
    "wss_status": "object",
    "achieved_recall": "float64",
    "mean_eta_lcb": "float64",
}


def _empty_dataframe() -> pd.DataFrame:
    """Return a zero-row DataFrame matching PARQUET_SCHEMA."""
    return pd.DataFrame(
        {col: pd.Series(dtype=dtype) for col, dtype in PARQUET_SCHEMA.items()}
    )


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    seed: int = 42,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run m-sensitivity sweep over all topics in data_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "m_sensitivity.parquet", index=False)
        (out_dir / "skipped_topics.json").write_text(json.dumps([]))
        return df_empty

    raise NotImplementedError("Non-dry-run sweep not yet implemented")
