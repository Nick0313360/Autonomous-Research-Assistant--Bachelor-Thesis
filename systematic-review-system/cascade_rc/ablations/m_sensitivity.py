from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from cascade_rc.certificates.store import CertificationResult
from cascade_rc.config import CascadeRCConfig
from cascade_rc.evaluation.metrics import wss_at_recall

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


def _topic_seed(topic_id: str, global_seed: int) -> int:
    """Derive a deterministic seed from (topic_id, global_seed).

    Uses hashlib.sha256 instead of hash() so output is stable across
    processes regardless of PYTHONHASHSEED — required for joblib loky workers.
    """
    digest = hashlib.sha256(f"{topic_id}:{global_seed}".encode()).digest()
    return int.from_bytes(digest[:8], "little")


def _empty_dataframe() -> pd.DataFrame:
    """Return a zero-row DataFrame matching PARQUET_SCHEMA."""
    return pd.DataFrame(
        {col: pd.Series(dtype=dtype) for col, dtype in PARQUET_SCHEMA.items()}
    )


def _compute_m_grid(m_plus_full: int, n_min: int) -> list[int]:
    """Return sorted unique m values to sweep, all <= m_plus_full.

    Always includes m_plus_full itself ("full" entry). Excludes candidates
    outside [n_min, m_plus_full]. Deduplicates in case m_plus_full equals a candidate.
    """
    grid = [m for m in M_GRID_CANDIDATES if n_min <= m <= m_plus_full]
    if m_plus_full not in grid:
        grid.append(m_plus_full)
    return sorted(set(grid))


def _subsample_to_m(
    df: pd.DataFrame,
    m: int,
    topic_id: str,
    global_seed: int,
) -> pd.DataFrame:
    """Return df with calibration positives subsampled to exactly m rows.

    Seed is derived from (topic_id, global_seed) only — NOT m — so that
    smaller m values are strict prefixes of larger ones (nested subsets).
    Unsampled calibration positives are dropped entirely; test rows
    (is_calib==0) are untouched, keeping the test split constant.
    """
    cal_pos_mask = (df["is_calib"] == 1) & (df["y_abstract"] == 1)
    cal_pos_indices = df.index[cal_pos_mask].to_numpy()

    if len(cal_pos_indices) <= m:
        return df.copy()

    rng = np.random.default_rng(_topic_seed(topic_id, global_seed))
    permuted = rng.permutation(cal_pos_indices)
    drop_indices = permuted[m:]
    return df.drop(index=drop_indices).copy()


def _compute_wss(result: CertificationResult, df_full: pd.DataFrame) -> dict:
    """Compute WSS@95 on the test split (is_calib==0) under certified theta_hat.

    Routing: documents with s < lambda_lo are auto-rejected (predictions=0).
    Everything else reaches the working set (predictions=1), which includes
    auto-accepted, SE-escalated, and uncertain-but-no-SE documents.
    Auto-rejected positives are false negatives — wss_at_recall captures
    this as status='recall_target_missed' when achieved recall < 0.95.
    """
    df_test = df_full[df_full["is_calib"] == 0]
    s = df_test["s"].to_numpy(dtype=np.float64)
    y = df_test["y_abstract"].to_numpy(dtype=np.int64)

    lam_lo = float(result.theta_hat[0])
    auto_reject = s < lam_lo
    predictions = (~auto_reject).astype(int)

    return wss_at_recall(predictions, y, target_recall=0.95)


def _run_topic(
    topic_id: str,
    parquet_path: Path,
    config: CascadeRCConfig,
    global_seed: int,
    out_dir: Path,
) -> tuple[list[dict], bool]:
    """Run m-sensitivity sweep for one topic.

    Returns:
        (rows, skipped): rows is a list of result-row dicts (one per m-cell);
        skipped=True if the topic was skipped due to m_plus_full < N_min.
    """
    # Compute N_min locally to avoid importing calibration module before skip check
    n_min = math.ceil(math.log(1 / config.ltt.delta_LTT) / (-math.log(1 - config.ltt.alpha)))

    df = pd.read_parquet(parquet_path)
    m_plus_full = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())

    if m_plus_full < n_min:
        return [], True

    # Only import calibrate if we're not skipping
    from cascade_rc.calibration.main_calibrate import calibrate

    m_grid = _compute_m_grid(m_plus_full, n_min)
    rows: list[dict] = []
    cache_dir = out_dir / "calibration_cache"

    for m in m_grid:
        artefact_dir = cache_dir / f"{topic_id}_m{m}"
        artefact_dir.mkdir(parents=True, exist_ok=True)

        tmp_parquet: Path | None = None
        if m == m_plus_full:
            calib_path = parquet_path
        else:
            df_sub = _subsample_to_m(df, m, topic_id, global_seed)
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
                tmp_parquet = Path(f.name)
            df_sub.to_parquet(tmp_parquet, index=False)
            calib_path = tmp_parquet

        try:
            result = calibrate(
                topic_id, calib_path, config, artefact_dir=artefact_dir
            )
        finally:
            if tmp_parquet is not None and tmp_parquet.exists():
                tmp_parquet.unlink(missing_ok=True)

        if isinstance(result, tuple):
            rows.append({
                "topic_id": topic_id,
                "m_target": m,
                "m_actual": m,
                "abstention": True,
                "wss_95": float("nan"),
                "wss_status": "abstained",
                "achieved_recall": float("nan"),
                "mean_eta_lcb": float("nan"),
            })
        else:
            wss_dict = _compute_wss(result, df)
            rows.append({
                "topic_id": topic_id,
                "m_target": m,
                "m_actual": m,
                "abstention": False,
                "wss_95": wss_dict["wss"],
                "wss_status": wss_dict["status"],
                "achieved_recall": wss_dict["achieved_recall"],
                "mean_eta_lcb": float(np.mean(result.eta_lcb_grid)),
            })

    return rows, False


def _plot_topic(df_topic: pd.DataFrame, out_dir: Path, topic_id: str) -> None:
    """Save 3-panel figure for one topic: WSS@95 / mean η̂⁻⋆ / abstention."""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    m = df_topic["m_actual"].to_numpy()
    wss = df_topic["wss_95"].to_numpy(dtype=float)
    eta = df_topic["mean_eta_lcb"].to_numpy(dtype=float)
    abstention = df_topic["abstention"].to_numpy().astype(int)
    status = df_topic["wss_status"].to_numpy()

    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(6, 8))

    ok_mask = status == "ok"
    missed_mask = status == "recall_target_missed"
    if ok_mask.any():
        axes[0].plot(m[ok_mask], wss[ok_mask], "bo-", label="ok")
    if missed_mask.any():
        axes[0].plot(m[missed_mask], np.zeros(missed_mask.sum()), "rx",
                     markersize=10, label="recall missed")
    axes[0].set_ylabel("WSS@95")
    axes[0].set_title(topic_id)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        axes[0].legend(fontsize=8)

    non_abstained = ~abstention.astype(bool)
    if non_abstained.any():
        axes[1].plot(m[non_abstained], eta[non_abstained], "go-")
    axes[1].set_ylabel("mean η̂⁻⋆")

    axes[2].step(m, abstention, where="mid", color="red")
    axes[2].set_ylabel("abstention")
    axes[2].set_yticks([0, 1])
    axes[2].set_xlabel("m_actual (positives in calibration)")

    plt.tight_layout()
    fig.savefig(
        plot_dir / f"m_sensitivity_{topic_id}.png", dpi=150, bbox_inches="tight"
    )
    plt.close(fig)


def _plot_overview(df: pd.DataFrame, out_dir: Path) -> None:
    """Save combined 3-panel figure: all topics faded + bold median lines."""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(8, 10))

    for topic_id in df["topic_id"].unique():
        df_t = df[df["topic_id"] == topic_id]
        m = df_t["m_actual"].to_numpy()
        axes[0].plot(m, df_t["wss_95"].to_numpy(dtype=float), "b-",
                     alpha=0.3, linewidth=1)
        axes[1].plot(m, df_t["mean_eta_lcb"].to_numpy(dtype=float), "g-",
                     alpha=0.3, linewidth=1)
        axes[2].step(m, df_t["abstention"].to_numpy().astype(int),
                     where="mid", alpha=0.3, linewidth=1)

    for ax, col in zip(axes[:2], ["wss_95", "mean_eta_lcb"]):
        pivot = df.groupby("m_actual")[col].median()
        ax.plot(pivot.index, pivot.values, "k-", linewidth=2.5, label="median")
        ax.legend(fontsize=8)

    axes[0].set_ylabel("WSS@95")
    axes[1].set_ylabel("mean η̂⁻⋆")
    axes[2].set_ylabel("abstention indicator")
    axes[2].set_xlabel("m_actual (positives in calibration)")

    plt.tight_layout()
    fig.savefig(
        plot_dir / "m_sensitivity_overview.png", dpi=150, bbox_inches="tight"
    )
    plt.close(fig)


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    seed: int = 42,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run m-sensitivity sweep over all topics in data_dir."""
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "m_sensitivity.parquet", index=False)
        (out_dir / "skipped_topics.json").write_text(json.dumps([]))
        return df_empty

    from joblib import Parallel, delayed

    config = CascadeRCConfig()
    parquet_paths = sorted(Path(data_dir).glob("*.parquet"))
    if topics_filter:
        parquet_paths = [p for p in parquet_paths if p.stem in topics_filter]

    results: list[tuple[list[dict], bool]] = Parallel(
        n_jobs=n_jobs, backend="loky"
    )(
        delayed(_run_topic)(p.stem, p, config, seed, out_dir)
        for p in parquet_paths
    )

    all_rows: list[dict] = []
    skipped_topics: list[str] = []
    for (rows, skipped), p in zip(results, parquet_paths):
        all_rows.extend(rows)
        if skipped:
            skipped_topics.append(p.stem)

    if all_rows:
        df = pd.DataFrame(all_rows).astype(PARQUET_SCHEMA)
    else:
        df = _empty_dataframe()

    df.to_parquet(out_dir / "m_sensitivity.parquet", index=False)
    (out_dir / "skipped_topics.json").write_text(json.dumps(sorted(skipped_topics)))

    if not df.empty:
        for tid in df["topic_id"].unique():
            _plot_topic(df[df["topic_id"] == tid], out_dir, tid)
        if df["topic_id"].nunique() > 1:
            _plot_overview(df, out_dir)

    return df


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="m₊ sensitivity sweep for CASCADE-RC",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path("artefacts/cascade_rc/data"),
        help="Directory containing enriched topic parquets",
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=Path("artefacts/cascade_rc/ablations"),
        help="Output directory for parquet, JSON, and plots",
    )
    parser.add_argument("--seed", type=int, default=42, help="Global RNG seed")
    parser.add_argument(
        "--topics", nargs="+", default=None,
        help="Restrict sweep to these topic IDs (space-separated)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Write schema-only parquet without running calibration",
    )
    parser.add_argument(
        "--n-jobs", type=int, default=1,
        help="Parallel topic workers (loky backend)",
    )
    args = parser.parse_args()

    df = run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        seed=args.seed,
        topics_filter=args.topics,
        n_jobs=args.n_jobs,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(
            f"DRY-RUN: schema written to {args.out_dir / 'm_sensitivity.parquet'}"
        )
    else:
        print(
            f"Sweep complete: {len(df)} rows, "
            f"{df['topic_id'].nunique()} topics"
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
