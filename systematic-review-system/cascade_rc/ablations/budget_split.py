from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from cascade_rc.config import CascadeRCConfig, LTTBudget
from cascade_rc.evaluation.metrics import (
    bootstrap_eta_upper,
    slack_ratio_diagnostic,
    wss_at_recall,
)

HEADLINE_DTA_TOPICS: list[str] = ["CD008874", "CD012080", "CD012768"]

BUDGET_SPLITS: list[tuple[float, float]] = [
    (0.01, 0.09),
    (0.03, 0.07),
    (0.05, 0.05),
    (0.07, 0.03),
    (0.09, 0.01),
]

PARQUET_SCHEMA: dict[str, str] = {
    "delta_eta": "float64",
    "delta_ltt": "float64",
    "topic_id": "object",
    "m_plus": "int64",
    "abstention": "bool",
    "wss_95": "float64",
    "wss_status": "object",
    "achieved_recall": "float64",
    "n_certified": "int64",
    "mean_eta_lcb": "float64",
    "slack_ratio": "float64",
    "theta_hat_lambda_lo": "float64",
    "theta_hat_lambda_hi": "float64",
    "theta_hat_tau_se": "float64",
    "alpha_dagger_at_theta": "float64",
}


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {col: pd.Series(dtype=dtype) for col, dtype in PARQUET_SCHEMA.items()}
    )


def _compute_wss(result: object, df_full: pd.DataFrame) -> dict:
    df_test = df_full[df_full["is_calib"] == 0]
    s = df_test["s"].to_numpy(dtype=np.float64)
    y = df_test["y_abstract"].to_numpy(dtype=np.int64)
    lam_lo = float(result.theta_hat[0])  # type: ignore[union-attr]
    auto_reject = s < lam_lo
    predictions = (~auto_reject).astype(int)
    return wss_at_recall(predictions, y, target_recall=0.95)


def _find_theta_hat_idx(result: object) -> int:
    matches = np.where(
        np.all(result.theta_grid == result.theta_hat[np.newaxis, :], axis=1)  # type: ignore[union-attr]
    )[0]
    return int(matches[0])


def _run_topic(
    topic_id: str,
    parquet_path: Path,
    delta_eta: float,
    delta_ltt: float,
    config: CascadeRCConfig,
    out_dir: Path,
) -> dict:
    from cascade_rc.calibration.main_calibrate import calibrate

    patched_ltt = LTTBudget(
        alpha=config.ltt.alpha,
        delta_total=config.ltt.delta_total,
        delta_eta=delta_eta,
        delta_LTT=delta_ltt,
        K=config.ltt.K,
        B=config.ltt.B,
        ensemble_temperature=config.ltt.ensemble_temperature,
        c_human=config.ltt.c_human,
        c_llm=config.ltt.c_llm,
        delta_bootstrap=config.ltt.delta_bootstrap,
    )
    patched_config = config.model_copy(update={"ltt": patched_ltt})

    artefact_dir = (
        out_dir / "calibration_cache"
        / f"{topic_id}_de{delta_eta:.2f}_dl{delta_ltt:.2f}"
    )
    artefact_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(parquet_path)
    if config.quantile_scale_base_scores:
        from cascade_rc.data.score_normalizer import quantile_scale_s
        df = quantile_scale_s(df)
    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())

    result = calibrate(topic_id, parquet_path, patched_config, artefact_dir=artefact_dir)

    if isinstance(result, tuple):
        return {
            "delta_eta": delta_eta,
            "delta_ltt": delta_ltt,
            "topic_id": topic_id,
            "m_plus": m_plus,
            "abstention": True,
            "wss_95": float("nan"),
            "wss_status": "abstained",
            "achieved_recall": float("nan"),
            "n_certified": 0,
            "mean_eta_lcb": float("nan"),
            "slack_ratio": float("nan"),
            "theta_hat_lambda_lo": float("nan"),
            "theta_hat_lambda_hi": float("nan"),
            "theta_hat_tau_se": float("nan"),
            "alpha_dagger_at_theta": float("nan"),
        }

    wss_dict = _compute_wss(result, df)
    theta_idx = _find_theta_hat_idx(result)

    eta_boot = bootstrap_eta_upper(
        result.slack_mat,  # type: ignore[union-attr]
        delta=patched_config.ltt.delta_bootstrap,
        B=1000,
        seed=0,
    )
    ratio = slack_ratio_diagnostic(result.eta_lcb_grid, eta_boot)  # type: ignore[union-attr]
    slack_ratio_mean = float(np.nanmean(ratio))

    return {
        "delta_eta": delta_eta,
        "delta_ltt": delta_ltt,
        "topic_id": topic_id,
        "m_plus": result.m_plus,  # type: ignore[union-attr]
        "abstention": False,
        "wss_95": wss_dict["wss"],
        "wss_status": wss_dict["status"],
        "achieved_recall": wss_dict["achieved_recall"],
        "n_certified": int(result.lambda_hat_mask.sum()),  # type: ignore[union-attr]
        "mean_eta_lcb": float(np.mean(result.eta_lcb_grid)),  # type: ignore[union-attr]
        "slack_ratio": slack_ratio_mean,
        "theta_hat_lambda_lo": float(result.theta_hat[0]),  # type: ignore[union-attr]
        "theta_hat_lambda_hi": float(result.theta_hat[1]),  # type: ignore[union-attr]
        "theta_hat_tau_se": float(result.theta_hat[2]),  # type: ignore[union-attr]
        "alpha_dagger_at_theta": float(result.alpha_dagger_grid[theta_idx]),  # type: ignore[union-attr]
    }


def _plot_pareto(df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.cm as cm
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    delta_etas = sorted(df["delta_eta"].unique())
    topics = sorted(df["topic_id"].unique())
    markers = ["o", "s", "^"]
    cmap = cm.get_cmap("plasma", len(delta_etas))

    fig, ax = plt.subplots(figsize=(8, 6))

    for t_idx, topic_id in enumerate(topics):
        df_t = df[df["topic_id"] == topic_id]
        marker = markers[t_idx % len(markers)]
        for de_idx, de in enumerate(delta_etas):
            rows = df_t[df_t["delta_eta"] == de]
            if rows.empty:
                continue
            r = rows.iloc[0]
            color = cmap(de_idx)
            if r["wss_status"] == "ok":
                ax.scatter(
                    r["n_certified"], r["wss_95"],
                    color=color, marker=marker, s=80,
                    label=f"δ_η={de:.2f}" if t_idx == 0 else "",
                )
            else:
                ax.scatter(
                    r["n_certified"], 0.0,
                    color="red", marker="x", s=120, linewidths=2,
                )

    ax.set_xlabel("|Λ̂| (certified set size)")
    ax.set_ylabel("WSS@95")
    ax.set_title("Budget Split: |Λ̂| vs WSS@95 by δ_η (Pareto Front)")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(
            dict(zip(labels, handles)).values(),
            dict(zip(labels, handles)).keys(),
            fontsize=8, loc="lower right",
        )

    # Inset: abstention heatmap (splits × topics)
    ax_ins = ax.inset_axes([0.65, 0.62, 0.33, 0.32])
    abstention_mat = np.zeros((len(delta_etas), len(topics)), dtype=float)
    for i, de in enumerate(delta_etas):
        for j, topic_id in enumerate(topics):
            rows = df[(df["delta_eta"] == de) & (df["topic_id"] == topic_id)]
            if not rows.empty:
                abstention_mat[i, j] = float(rows.iloc[0]["abstention"])
    ax_ins.imshow(abstention_mat, aspect="auto", cmap="Reds", vmin=0, vmax=1)
    ax_ins.set_xticks(range(len(topics)))
    ax_ins.set_xticklabels([t[-6:] for t in topics], fontsize=5, rotation=45)
    ax_ins.set_yticks(range(len(delta_etas)))
    ax_ins.set_yticklabels([f"{de:.2f}" for de in delta_etas], fontsize=5)
    ax_ins.set_title("abstention", fontsize=6)

    plt.tight_layout()
    fig.savefig(plot_dir / "budget_split_pareto.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
    delta_eta_values: list[float] | None = None,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "budget_split.parquet", index=False)
        return df_empty

    if delta_eta_values is not None:
        splits = [(de, round(0.10 - de, 4)) for de in sorted(delta_eta_values)]
    else:
        splits = BUDGET_SPLITS

    topics = topics_filter if topics_filter is not None else HEADLINE_DTA_TOPICS
    parquet_paths = {p.stem: p for p in sorted(data_dir.glob("*.parquet"))}
    available = [t for t in topics if t in parquet_paths]

    config = CascadeRCConfig()

    tasks = [
        (topic_id, parquet_paths[topic_id], delta_eta, delta_ltt, config, out_dir)
        for topic_id in available
        for delta_eta, delta_ltt in splits
    ]

    results: list[dict] = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(_run_topic)(*args) for args in tasks
    )

    df = pd.DataFrame(results).astype(PARQUET_SCHEMA) if results else _empty_dataframe()
    df.to_parquet(out_dir / "budget_split.parquet", index=False)

    if not df.empty:
        _plot_pareto(df, out_dir)

    return df


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Budget-split ablation sweep for CASCADE-RC",
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
        help="Output directory for parquet and plots",
    )
    parser.add_argument(
        "--topics", nargs="+", default=None,
        help="Topic IDs to include (default: 3 headline DTA topics)",
    )
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--delta-eta-values", nargs="+", type=float, default=None, metavar="DELTA_ETA",
        help="δ_η values to sweep (delta_ltt = 0.10 - delta_eta). "
             "Default: BUDGET_SPLITS constant.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Exact output path for the result parquet "
             "(overrides --out-dir / budget_split.parquet).",
    )
    args = parser.parse_args()

    effective_out_dir = args.output.parent if args.output is not None else args.out_dir

    df = run_sweep(
        data_dir=args.data_dir,
        out_dir=effective_out_dir,
        topics_filter=args.topics,
        n_jobs=args.n_jobs,
        dry_run=args.dry_run,
        delta_eta_values=args.delta_eta_values,
    )

    if args.dry_run:
        print(f"DRY-RUN: schema written to {effective_out_dir / 'budget_split.parquet'}")
    else:
        print(f"Sweep complete: {len(df)} rows, {df['topic_id'].nunique()} topics")
    sys.exit(0)


if __name__ == "__main__":
    main()
