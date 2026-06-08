"""Publication figures for CASCADE-RC (IEEEtran-friendly).

Loads sweep / ablation parquets and writes PDF + PNG under artefacts/cascade_rc/figures/.

Run (deterministic bytes for PNG when hash seed fixed):
    PYTHONHASHSEED=0 python -m cascade_rc.evaluation.figures \\
        --artefact-dir artefacts/cascade_rc
"""
from __future__ import annotations

import math
import os
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

FIGSIZE_SINGLE: tuple[float, float] = (3.5, 2.6)
FIGSIZE_FIG3: tuple[float, float] = (7.0, 2.6)

_IEEE_RC: dict[str, object] = {
    "font.family": "serif",
    "font.size": 8,
    "axes.titlesize": 8,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 6,
    "lines.linewidth": 1.0,
    "axes.linewidth": 0.8,
    "figure.dpi": 150,
}

_PDF_META: dict[str, str] = {
    "Creator": "cascade_rc.evaluation.figures",
    "Title": "",
    "Subject": "",
    "Author": "",
}

_DEFAULT_TOPICS: tuple[str, ...] = (
    "CD008874",
    "CD012080",
    "CD012768",
    "CD011768",
    "CD011975",
    "CD011145",
)

_FIG1_ALPHA_GRID: tuple[float, ...] = (0.01, 0.02, 0.05, 0.10, 0.15, 0.20)
_FIG2_ALPHA_GRID: tuple[float, ...] = (0.01, 0.05, 0.10, 0.15, 0.20)


def _apply_ieee_style() -> None:
    plt.rcParams.update(_IEEE_RC)


def _certified_mask(df: pd.DataFrame) -> pd.Series:
    if "status" not in df.columns:
        return pd.Series(True, index=df.index)
    return df["status"] == "certified"


def _alpha_match(s: pd.Series, alpha: float) -> pd.Series:
    return np.isclose(s.astype(float), float(alpha), rtol=0.0, atol=1e-9)


def _alphas_from_grid_or_data(
    grid: tuple[float, ...],
    certified: pd.DataFrame,
) -> list[float]:
    present = certified["alpha"].astype(float).to_numpy()
    chosen = [a for a in grid if np.any(np.isclose(present, a, rtol=0.0, atol=1e-9))]
    if chosen:
        return chosen
    return sorted(float(x) for x in np.unique(present))


def _fnr_column_for_method(method_label: str) -> str | None:
    if method_label == "CASCADE-RC":
        return "fnr_test"
    if method_label == "SCRC-T":
        return "scrc_t_fnr"
    if method_label == "SCRC-I":
        return "scrc_i_fnr"
    if method_label == "AUTOSTOP":
        return "autostop_fnr"
    if method_label in ("Uncalibrated", "Uncalib"):
        return "uncalibrated_fnr"
    return None


def _savefig_stem(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        path = output_dir / f"{stem}.{ext}"
        save_kw: dict[str, object] = {"dpi": 200, "bbox_inches": "tight"}
        if ext == "pdf":
            save_kw["metadata"] = _PDF_META
        fig.savefig(path, format=ext, **save_kw)
        print(f"  Saved {path}")
    plt.close(fig)


def _synthetic_alpha_sweep_placeholder() -> pd.DataFrame:
    """Tiny deterministic table so module runs when sweep parquet is absent."""
    rng = np.random.default_rng(0)
    rows: list[dict[str, object]] = []
    for alpha in _FIG1_ALPHA_GRID:
        for topic_id in _DEFAULT_TOPICS:
            base = float(alpha) * rng.uniform(0.4, 0.92)
            rows.append(
                {
                    "topic_id": topic_id,
                    "alpha": alpha,
                    "status": "certified",
                    "fnr_test": base,
                    "wss_95": float(rng.uniform(0.15, 0.55)),
                    "frac_human_review": float(np.clip(0.85 - 2.5 * alpha, 0.05, 0.95)),
                    "scrc_t_fnr": float(np.clip(alpha + rng.normal(0.0, 0.02), 0.0, 1.0)),
                    "scrc_i_fnr": float(np.clip(alpha + rng.normal(0.0, 0.02), 0.0, 1.0)),
                    "autostop_fnr": float(np.clip(alpha + rng.normal(0.0, 0.03), 0.0, 1.0)),
                    "uncalibrated_fnr": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _synthetic_budget_split_placeholder() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    deltas = [0.01, 0.02, 0.03, 0.05, 0.07, 0.09]
    rows: list[dict[str, object]] = []
    for topic_id in _DEFAULT_TOPICS:
        peak = 8 + int(rng.integers(-2, 3))
        for de in deltas:
            dist = abs(de - 0.04)
            lam = max(1, int(peak - 15 * dist + rng.normal(0.0, 0.8)))
            slack_r = float(np.clip(0.75 + 0.25 * np.exp(-((de - 0.04) ** 2) / 0.0008), 0.0, 1.2))
            rows.append(
                {
                    "topic_id": topic_id,
                    "delta_eta": de,
                    "n_certified": lam,
                    "slack_ratio": slack_r,
                }
            )
    return pd.DataFrame(rows)


def _load_alpha_sweep_df(artefact_dir: Path) -> pd.DataFrame:
    path = artefact_dir / "results" / "alpha_sweep.parquet"
    if path.exists():
        return pd.read_parquet(path)
    warnings.warn(
        f"Missing {path}; using synthetic alpha-sweep placeholder for figures.",
        RuntimeWarning,
        stacklevel=2,
    )
    return _synthetic_alpha_sweep_placeholder()


def _load_budget_split_df(artefact_dir: Path) -> pd.DataFrame:
    path = artefact_dir / "ablations" / "budget_split.parquet"
    if path.exists():
        return pd.read_parquet(path)
    warnings.warn(
        f"Missing {path}; using synthetic budget-split placeholder for Figure 3.",
        RuntimeWarning,
        stacklevel=2,
    )
    return _synthetic_budget_split_placeholder()


def _resolve_autostop_parquet(artefact_dir: Path) -> Path | None:
    candidates = [
        artefact_dir / "baselines" / "autostop" / "autostop_results.parquet",
        artefact_dir / "baselines" / "autostop_results.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_autostop_wss_reference(artefact_dir: Path, recall: float = 0.95) -> float:
    """Mean WSS@95 across topics from AUTOSTOP results (target_recall == recall)."""
    path = _resolve_autostop_parquet(artefact_dir)
    if path is None:
        warnings.warn(
            "AUTOSTOP parquet not found; operational-cost reference line omitted.",
            RuntimeWarning,
            stacklevel=2,
        )
        return float("nan")
    raw = pd.read_parquet(path)
    sub = raw[np.isclose(raw["target_recall"].astype(float), recall, rtol=0.0, atol=1e-6)]
    if sub.empty:
        return float("nan")
    vals = sub["wss_95"].astype(float).replace(-999.0, np.nan).dropna()
    if vals.empty:
        return float("nan")
    return float(vals.mean())


def _autostop_wss_for_topic(artefact_dir: Path, topic_id: str, recall: float = 0.95) -> float:
    """WSS@95 for a single topic from the AUTOSTOP parquet."""
    path = _resolve_autostop_parquet(artefact_dir)
    if path is None:
        return float("nan")
    raw = pd.read_parquet(path)
    sub = raw[
        (raw["topic_id"] == topic_id)
        & np.isclose(raw["target_recall"].astype(float), recall, rtol=0.0, atol=1e-6)
    ]
    if sub.empty:
        return float("nan")
    vals = sub["wss_95"].astype(float).replace(-999.0, np.nan).dropna()
    return float(vals.mean()) if not vals.empty else float("nan")


# ---------------------------------------------------------------------------
# Figure 1 — Risk-control validity
# ---------------------------------------------------------------------------

def plot_risk_validity(alpha_sweep_df: pd.DataFrame, output_dir: Path) -> None:
    """Empirical FNR vs target α; diagonal y = α; ±1 SE band across topics."""
    _apply_ieee_style()
    certified = alpha_sweep_df[_certified_mask(alpha_sweep_df)].copy()

    methods: dict[str, dict[str, object]] = {
        "CASCADE-RC": {"color": "#1f77b4", "marker": "o", "lw": 1.5},
        "SCRC-T": {"color": "#ff7f0e", "marker": "s", "lw": 1.2},
        "SCRC-I": {"color": "#2ca02c", "marker": "^", "lw": 1.2},
        "AUTOSTOP": {"color": "#9467bd", "marker": "D", "lw": 1.0},
        "Uncalibrated": {"color": "#d62728", "marker": "x", "lw": 1.0, "ls": "--"},
    }

    alpha_values = _alphas_from_grid_or_data(_FIG1_ALPHA_GRID, certified)

    fig, ax = plt.subplots(figsize=(3.5, 3.0))
    ax.plot([0, 0.22], [0, 0.22], "k--", lw=0.8, label=r"$y=\alpha$ (bound)", zorder=1)

    for method_name, style in methods.items():
        col = _fnr_column_for_method(method_name)
        if col is None or col not in certified.columns:
            continue

        fnr_means: list[float] = []
        fnr_ses: list[float] = []
        for alpha in alpha_values:
            sub = certified[_alpha_match(certified["alpha"], alpha)]
            if sub.empty:
                fnr_means.append(float("nan"))
                fnr_ses.append(0.0)
                continue
            vals = sub[col].dropna().astype(float).to_numpy()
            if len(vals) == 0:
                fnr_means.append(float("nan"))
                fnr_ses.append(0.0)
            else:
                fnr_means.append(float(np.mean(vals)))
                fnr_ses.append(float(np.std(vals) / np.sqrt(len(vals))))

        if all(np.isnan(fnr_means)):
            continue

        alphas_plot = list(alpha_values)
        ax.plot(
            alphas_plot,
            fnr_means,
            marker=str(style["marker"]),
            markersize=4,
            lw=float(style["lw"]),
            color=str(style["color"]),
            label=method_name,
            zorder=3,
            ls=str(style.get("ls", "-")),
        )
        lo = [m - e for m, e in zip(fnr_means, fnr_ses)]
        hi = [m + e for m, e in zip(fnr_means, fnr_ses)]
        ax.fill_between(
            alphas_plot,
            lo,
            hi,
            alpha=0.15,
            color=str(style["color"]),
            zorder=2,
        )

    ax.set_xlabel("Target risk α")
    ax.set_ylabel("Empirical FNR (test)")
    ax.set_xlim(-0.005, 0.22)
    ax.set_ylim(-0.02, 0.35)
    ax.axhline(0, color="black", lw=0.4, ls="-", alpha=0.3)
    ax.annotate(
        "Valid region\n(FNR ≤ α)",
        xy=(0.14, 0.07),
        fontsize=5,
        color="gray",
        ha="center",
        style="italic",
    )
    ax.legend(loc="upper left", framealpha=0.9, edgecolor="none")
    fig.tight_layout()
    _savefig_stem(fig, output_dir, "fig1_risk_validity")


# ---------------------------------------------------------------------------
# Figure 2 — Operational cost (dual axis)
# ---------------------------------------------------------------------------

def plot_operational_cost(
    alpha_sweep_df: pd.DataFrame,
    autostop_wss: float,
    output_dir: Path,
) -> None:
    """WSS@95 (left) and human escalation rate (right) vs α for CASCADE-RC."""
    _apply_ieee_style()
    certified = alpha_sweep_df[_certified_mask(alpha_sweep_df)].copy()

    alpha_values = list(_FIG2_ALPHA_GRID)
    cascade_wss: list[float] = []
    cascade_esc: list[float] = []

    for alpha in alpha_values:
        sub = certified[_alpha_match(certified["alpha"], alpha)]
        if sub.empty:
            cascade_wss.append(float("nan"))
            cascade_esc.append(float("nan"))
            continue
        wss = sub["wss_95"].astype(float).replace(-999.0, np.nan)
        cascade_wss.append(float(wss.mean()))
        cascade_esc.append(float(sub["frac_human_review"].astype(float).mean()))

    fig, ax1 = plt.subplots(figsize=FIGSIZE_SINGLE)
    ax2 = ax1.twinx()

    (l1,) = ax1.plot(
        alpha_values,
        cascade_wss,
        "b-o",
        markersize=4,
        lw=1.5,
        label="CASCADE-RC WSS@95",
    )
    (l2,) = ax2.plot(
        alpha_values,
        cascade_esc,
        "r--s",
        markersize=4,
        lw=1.2,
        label="Human escalation rate",
    )

    if not math.isnan(autostop_wss):
        ax1.axhline(
            autostop_wss,
            color="darkorange",
            ls=":",
            lw=1.0,
            label=f"AUTOSTOP WSS@95={autostop_wss:.2f}",
        )

    ax1.axvline(0.10, color="gray", ls=":", lw=0.8, alpha=0.7)
    ax1.text(0.105, -0.07, "α=0.10", fontsize=5, color="gray")
    ax1.axhline(0, color="black", lw=0.4, alpha=0.3)

    ax1.set_ylim(-0.10, 0.60)
    ax2.set_ylim(0, 1.05)
    ax1.set_xlabel("Target risk α")
    ax1.set_ylabel("WSS@95", color="blue")
    ax2.set_ylabel("Human escalation rate", color="red")
    ax1.tick_params(axis="y", labelcolor="blue")
    ax2.tick_params(axis="y", labelcolor="red")
    ax1.legend(handles=[l1, l2], loc="upper right", fontsize=5, framealpha=0.9)

    fig.tight_layout()
    _savefig_stem(fig, output_dir, "fig2_operational_cost")


# ---------------------------------------------------------------------------
# Figure 3 — Budget-split ablation
# ---------------------------------------------------------------------------

def plot_budget_split_ablation(ablation_df: pd.DataFrame, output_dir: Path) -> None:
    """|Λ̂| and slack ratio vs δ_η (two panels)."""
    _apply_ieee_style()

    lam_col = "lambda_hat_size" if "lambda_hat_size" in ablation_df.columns else "n_certified"
    if lam_col not in ablation_df.columns:
        raise ValueError("ablation_df must contain 'n_certified' or 'lambda_hat_size'.")

    delta_eta_values = sorted(ablation_df["delta_eta"].unique())
    topic_ids = ablation_df["topic_id"].unique()

    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=FIGSIZE_FIG3)

    for i, topic_id in enumerate(sorted(topic_ids)):
        sub = ablation_df[ablation_df["topic_id"] == topic_id].sort_values("delta_eta")
        color = colors[i % len(colors)]

        ax1.plot(
            sub["delta_eta"],
            sub[lam_col],
            marker="o",
            markersize=3,
            lw=1.0,
            color=color,
            label=topic_id,
            alpha=0.85,
        )

        if "slack_ratio" in sub.columns:
            ax2.plot(
                sub["delta_eta"],
                sub["slack_ratio"],
                marker="s",
                markersize=3,
                lw=1.0,
                color=color,
                label=topic_id,
                alpha=0.85,
            )

    ax1.axvline(0.03, color="gray", ls=":", lw=0.8)
    y0, _y1 = ax1.get_ylim()
    ax1.text(
        0.032,
        y0 + 0.02 * (ax1.get_ylim()[1] - y0),
        "δ_η=0.03\n(default)",
        fontsize=5,
        color="gray",
    )
    ax1.set_xlabel("η-budget δ_η", fontsize=8)
    ax1.set_ylabel("|Λ̂| certified configurations", fontsize=8)
    ax1.legend(fontsize=5, loc="upper right")

    ax2.axhline(1.0, color="black", ls="--", lw=0.8, label="ratio=1 (exact)")
    ax2.set_xlabel("η-budget δ_η", fontsize=8)
    ax2.set_ylabel(r"Slack ratio $\hat{\eta}^{-\star} / \hat{\eta}^{+}_{\mathrm{boot}}$", fontsize=8)
    ax2.set_ylim(0, 1.25)
    ax2.legend(fontsize=5, loc="lower right")

    fig.tight_layout()
    _savefig_stem(fig, output_dir, "fig3_budget_split_ablation")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def gen_figures(artefact_dir: Path = Path("artefacts/cascade_rc")) -> None:
    """Load parquets and write fig1–fig3 (PDF + PNG) under <artefact_dir>/figures/."""
    if os.environ.get("PYTHONHASHSEED") != "0":
        warnings.warn(
            "PYTHONHASHSEED is not '0'; PNG byte-reproducibility is not guaranteed. "
            "Re-run as: PYTHONHASHSEED=0 python -m cascade_rc.evaluation.figures",
            RuntimeWarning,
            stacklevel=2,
        )

    artefact_dir = Path(artefact_dir)
    out_dir = artefact_dir / "figures"

    alpha_df = _load_alpha_sweep_df(artefact_dir)
    autostop_wss = load_autostop_wss_reference(artefact_dir)
    budget_df = _load_budget_split_df(artefact_dir)

    # Aggregate figures (all topics)
    plot_risk_validity(alpha_df, out_dir)
    plot_operational_cost(alpha_df, autostop_wss, out_dir)
    plot_budget_split_ablation(budget_df, out_dir)

    # Per-topic figures
    all_topics = sorted(
        set(alpha_df["topic_id"].unique()) | set(budget_df["topic_id"].unique())
    )
    for topic_id in all_topics:
        topic_dir = out_dir / topic_id
        topic_alpha = alpha_df[alpha_df["topic_id"] == topic_id]
        topic_budget = budget_df[budget_df["topic_id"] == topic_id]
        topic_autostop = _autostop_wss_for_topic(artefact_dir, topic_id)
        print(f"\n  [{topic_id}]")
        if not topic_alpha.empty:
            plot_risk_validity(topic_alpha, topic_dir)
            plot_operational_cost(topic_alpha, topic_autostop, topic_dir)
        if not topic_budget.empty:
            plot_budget_split_ablation(topic_budget, topic_dir)


def main(artefact_dir: Path = Path("artefacts/cascade_rc")) -> None:
    """Backward-compatible alias for :func:`gen_figures`."""
    gen_figures(artefact_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artefact-dir",
        type=Path,
        default=Path("artefacts/cascade_rc"),
        help="Root artefact directory (default: artefacts/cascade_rc)",
    )
    args = parser.parse_args()
    gen_figures(artefact_dir=args.artefact_dir)
