from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from cascade_rc.calibration.walker import safest_to_riskiest_order
from cascade_rc.config import CascadeRCConfig
from cascade_rc.evaluation.metrics import wss_at_recall

HEADLINE_DTA_TOPICS: list[str] = ["CD008874", "CD012080", "CD012768"]
RANDOM_SEEDS: list[int] = [42, 43, 44, 45, 46]


def _order_riskiest_to_safest(grid: np.ndarray) -> np.ndarray:
    return safest_to_riskiest_order(grid)[::-1]


def _order_lex_tau_se_first(grid: np.ndarray) -> np.ndarray:
    return np.lexsort((grid[:, 0], grid[:, 1], grid[:, 2]))


DETERMINISTIC_ORDERS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "safest_to_riskiest": safest_to_riskiest_order,
    "riskiest_to_safest": _order_riskiest_to_safest,
    "lex_tau_se_first": _order_lex_tau_se_first,
}


def _make_random_order_fn(seed: int) -> Callable[[np.ndarray], np.ndarray]:
    def _order(grid: np.ndarray) -> np.ndarray:
        return np.random.default_rng(seed).permutation(len(grid))
    return _order


PARQUET_SCHEMA: dict[str, str] = {
    "order_name": "object",
    "order_seed": "int64",
    "topic_id": "object",
    "m_plus": "int64",
    "abstention": "bool",
    "wss_95": "float64",
    "wss_status": "object",
    "achieved_recall": "float64",
    "n_certified": "int64",
    "mean_eta_lcb": "float64",
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
    order_name: str,
    order_seed: int,
    config: CascadeRCConfig,
    out_dir: Path,
) -> dict:
    from cascade_rc.calibration.main_calibrate import calibrate

    if order_name == "random":
        order_fn = _make_random_order_fn(order_seed)
    else:
        order_fn = DETERMINISTIC_ORDERS[order_name]

    artefact_dir = (
        out_dir / "calibration_cache"
        / f"{topic_id}_{order_name}_{order_seed}"
    )
    artefact_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(parquet_path)
    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())

    result = calibrate(
        topic_id, parquet_path, config,
        artefact_dir=artefact_dir,
        order_fn=order_fn,
    )

    if isinstance(result, tuple):
        return {
            "order_name": order_name,
            "order_seed": order_seed,
            "topic_id": topic_id,
            "m_plus": m_plus,
            "abstention": True,
            "wss_95": float("nan"),
            "wss_status": "abstained",
            "achieved_recall": float("nan"),
            "n_certified": 0,
            "mean_eta_lcb": float("nan"),
            "theta_hat_lambda_lo": float("nan"),
            "theta_hat_lambda_hi": float("nan"),
            "theta_hat_tau_se": float("nan"),
            "alpha_dagger_at_theta": float("nan"),
        }

    wss_dict = _compute_wss(result, df)
    theta_idx = _find_theta_hat_idx(result)

    return {
        "order_name": order_name,
        "order_seed": order_seed,
        "topic_id": topic_id,
        "m_plus": result.m_plus,  # type: ignore[union-attr]
        "abstention": False,
        "wss_95": wss_dict["wss"],
        "wss_status": wss_dict["status"],
        "achieved_recall": wss_dict["achieved_recall"],
        "n_certified": int(result.lambda_hat_mask.sum()),  # type: ignore[union-attr]
        "mean_eta_lcb": float(np.mean(result.eta_lcb_grid)),  # type: ignore[union-attr]
        "theta_hat_lambda_lo": float(result.theta_hat[0]),  # type: ignore[union-attr]
        "theta_hat_lambda_hi": float(result.theta_hat[1]),  # type: ignore[union-attr]
        "theta_hat_tau_se": float(result.theta_hat[2]),  # type: ignore[union-attr]
        "alpha_dagger_at_theta": float(result.alpha_dagger_grid[theta_idx]),  # type: ignore[union-attr]
    }


def _plot_n_certified(df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    topics = sorted(df["topic_id"].unique())
    det_names = list(DETERMINISTIC_ORDERS.keys())
    n_bars = len(det_names) + 1
    x = np.arange(len(topics))
    width = 0.18
    offsets = np.linspace(-(n_bars - 1) * width / 2, (n_bars - 1) * width / 2, n_bars)

    fig, ax = plt.subplots(figsize=(9, 5))

    for b_idx, order_name in enumerate(det_names):
        vals = [
            int(df[(df["topic_id"] == t) & (df["order_name"] == order_name)]["n_certified"].iloc[0])
            if not df[(df["topic_id"] == t) & (df["order_name"] == order_name)].empty
            else 0
            for t in topics
        ]
        ax.bar(x + offsets[b_idx], vals, width, label=order_name)

    rand_means = []
    rand_stds = []
    for t in topics:
        vals = df[(df["topic_id"] == t) & (df["order_name"] == "random")]["n_certified"].to_numpy(dtype=float)
        rand_means.append(float(vals.mean()) if len(vals) > 0 else 0.0)
        rand_stds.append(float(vals.std()) if len(vals) > 0 else 0.0)
    ax.bar(x + offsets[-1], rand_means, width, yerr=rand_stds, capsize=4, label="random (mean±std)")

    ax.set_xlabel("Topic")
    ax.set_ylabel("|Λ̂| (certified set size)")
    ax.set_title("Walk Ordering: Certified Set Size per Topic")
    ax.set_xticks(x)
    ax.set_xticklabels([t[-6:] for t in topics])
    ax.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(plot_dir / "walk_ordering_n_certified.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_wss_95(df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    topics = sorted(df["topic_id"].unique())
    det_names = list(DETERMINISTIC_ORDERS.keys())
    n_bars = len(det_names) + 1
    x = np.arange(len(topics))
    width = 0.18
    offsets = np.linspace(-(n_bars - 1) * width / 2, (n_bars - 1) * width / 2, n_bars)

    fig, ax = plt.subplots(figsize=(9, 5))

    for b_idx, order_name in enumerate(det_names):
        vals = []
        for t in topics:
            rows = df[(df["topic_id"] == t) & (df["order_name"] == order_name)]
            if rows.empty or rows.iloc[0]["wss_status"] != "ok":
                vals.append(0.0)
                if not rows.empty:
                    ax.text(
                        x[topics.index(t)] + offsets[b_idx], 0.02,
                        "✗", color="red", ha="center", fontsize=10,
                    )
            else:
                vals.append(float(rows.iloc[0]["wss_95"]))
        ax.bar(x + offsets[b_idx], vals, width, label=order_name)

    rand_means = []
    rand_stds = []
    for t in topics:
        ok_rows = df[
            (df["topic_id"] == t) & (df["order_name"] == "random") & (df["wss_status"] == "ok")
        ]
        vals = ok_rows["wss_95"].to_numpy(dtype=float)
        rand_means.append(float(vals.mean()) if len(vals) > 0 else 0.0)
        rand_stds.append(float(vals.std()) if len(vals) > 0 else 0.0)
    ax.bar(x + offsets[-1], rand_means, width, yerr=rand_stds, capsize=4, label="random (mean±std)")

    ax.set_xlabel("Topic")
    ax.set_ylabel("WSS@95")
    ax.set_title("Walk Ordering: WSS@95 per Topic")
    ax.set_xticks(x)
    ax.set_xticklabels([t[-6:] for t in topics])
    ax.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(plot_dir / "walk_ordering_wss_95.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "walk_ordering.parquet", index=False)
        return df_empty

    topics = topics_filter if topics_filter is not None else HEADLINE_DTA_TOPICS
    parquet_paths = {p.stem: p for p in sorted(data_dir.glob("*.parquet"))}
    available = [t for t in topics if t in parquet_paths]

    config = CascadeRCConfig()

    tasks: list[tuple] = []
    for topic_id in available:
        for order_name in DETERMINISTIC_ORDERS:
            tasks.append(
                (topic_id, parquet_paths[topic_id], order_name, -1, config, out_dir)
            )
        for seed in RANDOM_SEEDS:
            tasks.append(
                (topic_id, parquet_paths[topic_id], "random", seed, config, out_dir)
            )

    results: list[dict] = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(_run_topic)(*args) for args in tasks
    )

    df = pd.DataFrame(results).astype(PARQUET_SCHEMA) if results else _empty_dataframe()
    df.to_parquet(out_dir / "walk_ordering.parquet", index=False)

    if not df.empty:
        _plot_n_certified(df, out_dir)
        _plot_wss_95(df, out_dir)

    return df


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Walk-ordering ablation sweep for CASCADE-RC",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path("artefacts/cascade_rc/data"),
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=Path("artefacts/cascade_rc/ablations"),
    )
    parser.add_argument("--topics", nargs="+", default=None)
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    df = run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics_filter=args.topics,
        n_jobs=args.n_jobs,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"DRY-RUN: schema written to {args.out_dir / 'walk_ordering.parquet'}")
    else:
        print(f"Sweep complete: {len(df)} rows, {df['topic_id'].nunique()} topics")
    sys.exit(0)


if __name__ == "__main__":
    main()
