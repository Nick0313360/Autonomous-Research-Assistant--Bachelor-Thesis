"""
generate_graphs.py
==================
Generates 6 publication-quality figures for the CD008874 systematic review.
All data is hardcoded. Saves PDF + PNG at 300 DPI to:
  artefacts/graphs/   (override with GRAPHS_OUTPUT_DIR env var)
"""
from __future__ import annotations
import os
import sys
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np
from pathlib import Path

# ── Output directory ──────────────────────────────────────────────────────────
OUT_DIR = Path(os.environ.get("GRAPHS_OUTPUT_DIR", "artefacts/graphs"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Style ─────────────────────────────────────────────────────────────────────
for _style in ("seaborn-v0_8-whitegrid", "seaborn-whitegrid"):
    try:
        plt.style.use(_style)
        break
    except OSError:
        continue

matplotlib.rcParams.update({
    "font.family":      "DejaVu Sans",
    "axes.labelsize":   12,
    "axes.titlesize":   14,
    "legend.fontsize":  11,
    "xtick.labelsize":  11,
    "ytick.labelsize":  11,
    "figure.dpi":       150,
})

# ── Palette ───────────────────────────────────────────────────────────────────
NATIVE_BLUE = "#2563EB"
CASCADE_RED = "#DC2626"
COPA_PURPLE = "#7C3AED"
BEST_GREEN  = "#16A34A"
GRAY        = "#6B7280"
ORANGE      = "#EA580C"


def _save(fig: plt.Figure, name: str) -> list[str]:
    saved = []
    for ext in ("pdf", "png"):
        p = OUT_DIR / f"{name}.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        saved.append(p.name)
    plt.close(fig)
    return saved


def _clean_ax(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 1 — recall_precision_comparison
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig1_recall_precision() -> list[str]:
    methods = [
        "Abstract-only (Native)",
        "CASCADE-RC Abstract",
        "COPA CASCADE-RC",
        "Full Pipeline v5",
        "Full Pipeline + DTA",
        "CASCADE-RC + DTA ★",
    ]
    recalls    = [99.2, 94.6, 95.8, 95.4, 87.0, 94.6]
    precisions = [np.nan, 7.5, np.nan, 21.9, 48.3, 93.9]
    recall_colors = [
        NATIVE_BLUE,
        CASCADE_RED,
        COPA_PURPLE,
        ORANGE,
        ORANGE,
        BEST_GREEN,
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    y     = np.arange(len(methods))
    bar_h = 0.35

    # Highlight best row
    ax.axhspan(y[-1] - 0.48, y[-1] + 0.48, color=BEST_GREEN, alpha=0.07, zorder=0)

    # Recall bars
    bars_r = ax.barh(y + bar_h / 2, recalls, height=bar_h,
                     color=recall_colors, zorder=3, label="Recall")

    # Precision bars (only where not NaN)
    bars_p_patch = mpatches.Patch(color=GRAY, alpha=0.55, label="Precision")
    for i, (prec, col) in enumerate(zip(precisions, recall_colors)):
        if not np.isnan(prec):
            ax.barh(y[i] - bar_h / 2, prec, height=bar_h,
                    color=col, alpha=0.55, zorder=3)

    # Value labels
    for bar, val in zip(bars_r, recalls):
        ax.text(val + 1.0, bar.get_y() + bar.get_height() / 2,
                f"{val}%", va="center", ha="left", fontsize=10, color="#111")
    for i, prec in enumerate(precisions):
        if not np.isnan(prec):
            ax.text(prec + 1.0, y[i] - bar_h / 2,
                    f"{prec}%", va="center", ha="left", fontsize=10, color="#111")

    # Reference lines
    ax.axvline(95, color=NATIVE_BLUE, linestyle="--", linewidth=1.3, alpha=0.65)
    ax.text(95.3, len(methods) - 0.05, "95% recall\ntarget",
            color=NATIVE_BLUE, fontsize=9, va="top")
    ax.axvline(50, color=GRAY, linestyle="--", linewidth=1.3, alpha=0.55)
    ax.text(50.3, len(methods) - 0.05, "50% precision",
            color=GRAY, fontsize=9, va="top")

    # Best-result annotation
    ax.annotate(
        "Best: CASCADE-RC + DTA\n94.6% recall  |  93.9% precision",
        xy=(94.6, y[-1] + bar_h / 2),
        xytext=(52, y[-1] - 1.6),
        fontsize=10, color=BEST_GREEN, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=BEST_GREEN, lw=1.5),
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=BEST_GREEN, lw=1.5),
    )

    ax.set_yticks(y)
    ax.set_yticklabels(methods, fontsize=11)
    ax.set_xlabel("Percentage (%)", fontsize=12)
    ax.set_xlim(0, 110)
    ax.set_title("Recall vs Precision — CD008874 (Airway DTA)", fontsize=14, pad=12)

    legend_handles = [
        mpatches.Patch(color=GRAY, label="Recall"),
        mpatches.Patch(color=GRAY, alpha=0.55, label="Precision"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=11)
    _clean_ax(ax)
    fig.tight_layout()
    return _save(fig, "recall_precision_comparison")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 2 — precision_improvement_journey
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig2_precision_journey() -> list[str]:
    stages     = ["CASCADE-RC\nraw", "Full\npipeline", "Full pipeline\n+ DTA", "CASCADE-RC\n+ DTA ★"]
    precisions = [7.5,   21.9,  48.3,  93.9]
    recalls    = [94.6,  95.4,  87.0,  94.6]
    included   = [1639,  562,   58,    131]
    colors     = ["#86EFAC", "#4ADE80", "#22C55E", BEST_GREEN]

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()

    x    = np.arange(len(stages))
    bars = ax1.bar(x, precisions, color=colors, width=0.55, zorder=3,
                   edgecolor="white", linewidth=2)

    # Bar annotations
    for i, (bar, prec, rec, n) in enumerate(zip(bars, precisions, recalls, included)):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                 f"{prec}%", ha="center", va="bottom", fontsize=13,
                 fontweight="bold", color="#111")
        ax1.text(bar.get_x() + bar.get_width() / 2, max(bar.get_height() / 2 - 4, 2),
                 f"n = {n:,}\nrecall = {rec}%",
                 ha="center", va="center", fontsize=9,
                 color="white", fontweight="bold")

    # Arrows between bars
    for i in range(len(stages) - 1):
        ax1.annotate(
            "", xy=(x[i + 1] - 0.3, precisions[i + 1] * 0.25),
            xytext=(x[i] + 0.3, precisions[i] * 0.25),
            arrowprops=dict(arrowstyle="-|>", color=GRAY, lw=1.5, mutation_scale=14),
        )

    # Recall secondary axis
    ax2.plot(x, recalls, color=ORANGE, marker="o", linewidth=2.2,
             markersize=9, zorder=5, label="Recall (%)")
    ax2.axhline(95, color=ORANGE, linestyle=":", linewidth=1.2, alpha=0.5)
    ax2.set_ylim(78, 102)
    ax2.set_ylabel("Recall (%)", color=ORANGE, fontsize=12)
    ax2.tick_params(axis="y", labelcolor=ORANGE)
    ax2.spines["top"].set_visible(False)

    # Summary annotation
    ax1.annotate(
        "+12.5× precision\nimprovement\nrecall maintained",
        xy=(3, 93.9), xytext=(1.6, 72),
        fontsize=10, color=BEST_GREEN, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=BEST_GREEN, lw=1.5),
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=BEST_GREEN, lw=1.5),
    )

    ax1.set_xticks(x)
    ax1.set_xticklabels(stages, fontsize=11)
    ax1.set_ylabel("Precision (%)", fontsize=12)
    ax1.set_ylim(0, 110)
    ax1.set_title(
        "Precision Improvement Through Pipeline Stages\n"
        "With recall maintained above 87% throughout",
        fontsize=14, pad=10,
    )

    legend_elems = [
        mpatches.Patch(color=BEST_GREEN, label="Precision (left axis)"),
        Line2D([0], [0], color=ORANGE, marker="o", markersize=8,
               linewidth=2, label="Recall (right axis)"),
    ]
    ax1.legend(handles=legend_elems, loc="upper left", fontsize=11)
    _clean_ax(ax1)
    fig.tight_layout()
    return _save(fig, "precision_improvement_journey")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 3 — fnr_safety_diagram
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig3_fnr_safety() -> list[str]:
    # (label, alpha_val, fnr, marker, color, size)
    points = [
        ("CASCADE-RC + DTA (this work)",  0.15, 0.054, "*",  BEST_GREEN,  400),
        ("CASCADE-RC — COPA α=0.10", 0.10, 0.042, "o",  COPA_PURPLE, 150),
        ("CASCADE-RC — COPA α=0.15", 0.15, 0.042, "o",  COPA_PURPLE, 150),
        ("Native abstract-only",           0.05, 0.008, "s",  NATIVE_BLUE, 150),
        ("Full pipeline v5",               0.05, 0.046, "^",  ORANGE,      150),
        ("SCRC-T (COPA baseline)",         0.10, 0.250, "D",  GRAY,        120),
        ("RLStop (COPA baseline)",         0.10, 0.105, "v",  GRAY,        120),
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    x_diag = np.linspace(0, 0.22, 300)

    # Shaded regions
    ax.fill_between(x_diag, 0,      x_diag, color=BEST_GREEN,  alpha=0.09)
    ax.fill_between(x_diag, x_diag, 0.28,   color=CASCADE_RED, alpha=0.05)

    # Diagonal
    ax.plot(x_diag, x_diag, color=GRAY, linestyle="--", linewidth=1.5,
            label="Safety boundary  y = α", zorder=2)

    # Region labels
    ax.text(0.155, 0.015, "Certified safe region",
            color=BEST_GREEN, fontsize=10, style="italic", alpha=0.9)
    ax.text(0.02,  0.245, "Guarantee violated",
            color=CASCADE_RED, fontsize=10, style="italic", alpha=0.8)

    # Points + collect handles for legend
    handles, labels_list = [], []
    for label, av, fnr, marker, color, size in points:
        sc = ax.scatter(av, fnr, marker=marker, color=color,
                        s=size, zorder=5, edgecolors="white", linewidths=0.6)
        handles.append(sc)
        labels_list.append(label)

    # Annotation for the star point
    ax.annotate(
        "Certified\nFNR ≤ α = 0.15",
        xy=(0.15, 0.054), xytext=(0.095, 0.140),
        fontsize=10, color=BEST_GREEN, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=BEST_GREEN, lw=1.5),
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=BEST_GREEN, lw=1.5),
    )

    ax.set_xlim(0, 0.22)
    ax.set_ylim(0, 0.28)
    ax.set_xlabel("Target risk α", fontsize=12)
    ax.set_ylabel("Empirical FNR", fontsize=12)
    ax.set_title(
        "False Negative Rate vs Target Risk Level — CD008874\n"
        "FNR vs α — points below diagonal satisfy recall guarantee",
        fontsize=14, pad=10,
    )
    _clean_ax(ax)

    # Add diagonal to legend
    handles.insert(0, Line2D([0], [0], color=GRAY, linestyle="--",
                              linewidth=1.5, label="Safety boundary  y = α"))
    labels_list.insert(0, "Safety boundary  y = α")
    ax.legend(handles=handles, labels=labels_list, loc="upper left",
              fontsize=9.5, framealpha=0.93)
    ax.text(0.5, -0.12,
            "Points below y = α satisfy finite-sample recall guarantee",
            transform=ax.transAxes, ha="center", fontsize=10,
            color=GRAY, style="italic")

    fig.tight_layout()
    return _save(fig, "fnr_safety_diagram")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 4 — prisma_pipeline_funnel
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig4_prisma_funnel() -> list[str]:
    stage_data = [
        ("Records identified (search)",  408,  "#DBEAFE"),
        ("After canonical injection",   2445,  "#BFDBFE"),
        ("Screened at abstract",        2481,  "#93C5FD"),
        ("Passed abstract screening",   1530,  "#60A5FA"),
        ("Full texts sought",           2038,  "#3B82F6"),
        ("Full texts retrieved",         848,  "#2563EB"),
        ("Full texts assessed",          641,  "#1D4ED8"),
        ("Studies included (final)",     562,  "#1E3A8A"),
        ("After DTA rescreen ★",    131,  BEST_GREEN),
    ]
    dropouts = [
        None,
        "+2,037 added via canonical set",
        "+36 merged / deduplication",
        "−951 excluded at abstract",
        "+508 additional full-texts sought",
        "−1,190 not retrieved",
        "−207 retrieval failures",
        "−79 excluded at full-text",
        "−431 non-DTA papers removed",
    ]
    right_notes = {
        5: "38.8% retrieval rate\n(19× vs 2.1% baseline)",
        7: "21.9% precision",
        8: "93.9% precision ★",
    }

    n      = len(stage_data)
    labels = [s[0] for s in stage_data]
    counts = [s[1] for s in stage_data]
    colors = [s[2] for s in stage_data]
    y_pos  = np.arange(n)[::-1].astype(float)   # 8 … 0 (top → bottom)
    max_c  = max(counts)

    fig, ax = plt.subplots(figsize=(8, 12))
    bars = ax.barh(y_pos, counts, color=colors, height=0.58,
                   edgecolor="white", linewidth=1.8)

    for i, (bar, count, yp) in enumerate(zip(bars, counts, y_pos)):
        is_best = (i == n - 1)

        # Count label right of bar
        ax.text(bar.get_width() + max_c * 0.025, yp,
                f"{count:,}",
                va="center", ha="left", fontsize=11, fontweight="bold",
                color=BEST_GREEN if is_best else "#1E3A8A")

        # Right-side annotation
        if i in right_notes:
            ax.text(max_c * 1.28, yp, right_notes[i],
                    va="center", ha="left", fontsize=8.5,
                    color=BEST_GREEN if i >= 7 else NATIVE_BLUE,
                    style="italic",
                    fontweight="bold" if i >= 7 else "normal")

        # Dropout text between bars
        if i < n - 1 and dropouts[i + 1]:
            ax.text(max_c * 0.45, yp - 0.5, dropouts[i + 1],
                    va="center", ha="left", fontsize=8.2,
                    color=GRAY, style="italic")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("Number of records", fontsize=12)
    ax.set_xlim(0, max_c * 1.9)
    ax.set_title("PRISMA-Compliant Pipeline Flow — CD008874",
                 fontsize=14, pad=12)
    _clean_ax(ax)
    fig.tight_layout()
    return _save(fig, "prisma_pipeline_funnel")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 5 — cascade_routing_breakdown
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig5_routing_breakdown() -> list[str]:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 6))

    # ── Left: routing donut ──────────────────────────────────────────────────
    r_sizes  = [538, 256, 1639]
    r_colors = ["#FCA5A5", "#FDE68A", "#86EFAC"]
    r_labels = [
        "Cheap rejected\n(s < λ_lo)\n538  (22%)",
        "Escalation zone\n256  (11%)",
        "Auto-included\n(s ≥ λ_hi)\n1,639  (67%)",
    ]
    wedges1, _ = ax1.pie(
        r_sizes, colors=r_colors, startangle=90,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 2},
    )
    # Manual labels with leader lines
    ax1.annotate("Cheap rejected\n(s < λₓₒ)\n538  (22%)",
                 xy=(-0.5, 0.55), xytext=(-1.45, 0.85),
                 fontsize=9, ha="center",
                 arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.8))
    ax1.annotate("Escalation\nzone\n256  (11%)",
                 xy=(0.0, -0.6), xytext=(1.2, -1.05),
                 fontsize=9, ha="center",
                 arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.8))
    ax1.annotate("Auto-included\n(s ≥ λ_hi)\n1,639  (67%)",
                 xy=(0.55, 0.3), xytext=(1.25, 0.7),
                 fontsize=9, ha="center", color=BEST_GREEN, fontweight="bold",
                 arrowprops=dict(arrowstyle="-", color=BEST_GREEN, lw=0.8))

    ax1.text(0, 0.10, "λ_lo = 0.00129", ha="center", va="center",
             fontsize=8.5, color=GRAY, fontweight="bold")
    ax1.text(0, -0.12, "λ_hi = 0.00149", ha="center", va="center",
             fontsize=8.5, color=GRAY, fontweight="bold")
    ax1.set_title("CASCADE Routing\n(2,433 candidates)", fontsize=12, pad=10)
    ax1.text(0, -1.38, "Conformal routing thresholds",
             ha="center", fontsize=9, color=GRAY, style="italic")

    # ── Right: DTA filter donut (3 segments of 1,639 papers) ─────────────────
    # DTA-excluded: 1508, m+ confirmed: 123, false positives: 8
    d_sizes  = [1508, 123, 8]
    d_colors = ["#FCA5A5", BEST_GREEN, "#FDE68A"]
    wedges2, _ = ax2.pie(
        d_sizes, colors=d_colors, startangle=90,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 2},
    )

    ax2.annotate("DTA-excluded\n1,508  (92%)",
                 xy=(-0.45, -0.5), xytext=(-1.45, -0.85),
                 fontsize=9, ha="center", color=CASCADE_RED,
                 arrowprops=dict(arrowstyle="-", color=CASCADE_RED, lw=0.8))
    ax2.annotate("m+ confirmed\n123  (7.5%)",
                 xy=(0.55, 0.3), xytext=(1.25, 0.65),
                 fontsize=9, ha="center", color=BEST_GREEN, fontweight="bold",
                 arrowprops=dict(arrowstyle="-", color=BEST_GREEN, lw=0.8))
    ax2.annotate("False positives\n8  (0.5%)",
                 xy=(0.3, -0.55), xytext=(1.2, -1.0),
                 fontsize=9, ha="center", color=ORANGE,
                 arrowprops=dict(arrowstyle="-", color=ORANGE, lw=0.8))

    ax2.text(0, 0.10, "DTA-kept:", ha="center", va="center",
             fontsize=8.5, color=GRAY, fontweight="bold")
    ax2.text(0, -0.12, "131  (8%)", ha="center", va="center",
             fontsize=9, color=BEST_GREEN, fontweight="bold")
    ax2.set_title("DTA Post-Hoc Filter\n(1,639 auto-included)", fontsize=12, pad=10)
    ax2.text(0, -1.38, "93.9% precision  |  94.6% recall maintained",
             ha="center", fontsize=9.5, color=BEST_GREEN,
             fontweight="bold", style="italic")

    fig.suptitle("CASCADE-RC Routing Breakdown — CD008874",
                 fontsize=14, y=1.01)
    fig.tight_layout()
    return _save(fig, "cascade_routing_breakdown")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 6 — pdf_retrieval_improvement
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig6_retrieval() -> list[str]:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 6))

    # ── Left: before / after rate ────────────────────────────────────────────
    labels_l = ["Before\n(single source)\n32/1,530", "After\n(multi-source)\n848/2,038"]
    rates    = [2.1, 38.8]
    col_l    = [GRAY, NATIVE_BLUE]

    bars1 = ax1.bar(labels_l, rates, color=col_l, width=0.45,
                    edgecolor="white", linewidth=1.8, zorder=3)
    ax1.axhline(40, color=ORANGE, linestyle="--", linewidth=1.3, alpha=0.7)
    ax1.text(1.37, 41.2, "Target 40%", color=ORANGE, fontsize=9)

    for bar, rate in zip(bars1, rates):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8,
                 f"{rate}%", ha="center", va="bottom", fontsize=14,
                 fontweight="bold", color="#111")

    ax1.annotate(
        "19× improvement",
        xy=(1, 38.8), xytext=(0.48, 23),
        fontsize=11, color=BEST_GREEN, fontweight="bold", ha="center",
        arrowprops=dict(arrowstyle="->", color=BEST_GREEN, lw=1.8),
    )

    ax1.set_ylabel("Retrieval rate (%)", fontsize=12)
    ax1.set_ylim(0, 52)
    ax1.set_title("Retrieval Rate Before vs After", fontsize=12, pad=10)
    _clean_ax(ax1)

    # ── Right: by source ─────────────────────────────────────────────────────
    sources  = ["PubMed Central", "Semantic Scholar", "Unpaywall",
                "Europe PMC", "CrossRef"]
    counts   = [830, 12, 6, 0, 0]
    pcts     = ["97.9%", "1.4%", "0.7%", "0%", "0%"]
    s_colors = [NATIVE_BLUE, CASCADE_RED, COPA_PURPLE, GRAY, GRAY]

    bars2 = ax2.barh(sources[::-1], counts[::-1],
                     color=s_colors[::-1], height=0.5,
                     edgecolor="white", linewidth=1.8, zorder=3)

    for bar, pct in zip(bars2, pcts[::-1]):
        x_end = bar.get_width()
        offset = 8 if x_end < 20 else x_end + 12
        ax2.text(max(x_end + 10, 25), bar.get_y() + bar.get_height() / 2,
                 pct, va="center", ha="left", fontsize=10)

    ax2.set_xlabel("Number of papers retrieved", fontsize=12)
    ax2.set_xlim(0, 960)
    ax2.set_title("Retrieval by Source\n(v5, n = 848 total)", fontsize=12, pad=10)
    _clean_ax(ax2)
    ax2.text(0.5, -0.14,
             "New sources added this work: Europe PMC, Semantic Scholar, CrossRef",
             transform=ax2.transAxes, ha="center", fontsize=9,
             color=GRAY, style="italic")

    fig.suptitle("Full-Text Retrieval Improvement — Multi-Source Strategy",
                 fontsize=14, y=1.02)
    fig.tight_layout()
    return _save(fig, "pdf_retrieval_improvement")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIGURE 7 — cross_topic_validation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fig7_cross_topic() -> list[str]:
    # (y-label, precision, cert_status, color)
    topics = [
        ("CD012768\nXpert MTB/RIF",  31.3, "Uncalibrated",  GRAY),
        ("CD011145\nMMSE Dementia",  55.5, "Degenerate",     ORANGE),
        ("CD008874\nAirway DTA",     93.9, "Valid ★",        BEST_GREEN),
    ]

    labels     = [t[0] for t in topics]
    precisions = [t[1] for t in topics]
    statuses   = [t[2] for t in topics]
    colors     = [t[3] for t in topics]

    fig, ax = plt.subplots(figsize=(10, 6))

    bars = ax.barh(labels, precisions, color=colors, height=0.45,
                   edgecolor="white", linewidth=2, zorder=3)

    # Value + status label inside / right of each bar
    for bar, prec, status, col in zip(bars, precisions, statuses, colors):
        # Inline label at end of bar
        ax.text(
            prec + 1.2, bar.get_y() + bar.get_height() / 2,
            f"{prec}%  —  {status}",
            va="center", ha="left", fontsize=11,
            fontweight="bold", color=col,
        )

    # Publication threshold line
    ax.axvline(50, color=CASCADE_RED, linestyle="--", linewidth=1.5, alpha=0.75)
    ax.text(50.6, 2.42, "Publication\nthreshold\n(50%)",
            color=CASCADE_RED, fontsize=9, va="top", linespacing=1.4)

    # Annotation text box
    ax.text(
        0.97, 0.08,
        "Precision scales with\ncertificate quality",
        transform=ax.transAxes, ha="right", va="bottom",
        fontsize=10, style="italic", color=GRAY,
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=GRAY, lw=1.2),
    )

    # Legend for certificate status
    legend_handles = [
        mpatches.Patch(color=BEST_GREEN, label="Valid certificate"),
        mpatches.Patch(color=ORANGE,     label="Degenerate  (λ_lo = λ_hi)"),
        mpatches.Patch(color=GRAY,       label="Uncalibrated  (λ = 0)"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=10,
              framealpha=0.93)

    ax.set_xlabel("Precision after DTA rescreen (%)", fontsize=12)
    ax.set_xlim(0, 115)
    ax.set_title(
        "Cross-Topic Validation — CASCADE-RC + DTA Rescreen",
        fontsize=14, pad=12,
    )
    _clean_ax(ax)
    fig.tight_layout()
    return _save(fig, "cross_topic_validation")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    figures = [
        ("Fig 1  recall_precision_comparison",  fig1_recall_precision),
        ("Fig 2  precision_improvement_journey", fig2_precision_journey),
        ("Fig 3  fnr_safety_diagram",            fig3_fnr_safety),
        ("Fig 4  prisma_pipeline_funnel",        fig4_prisma_funnel),
        ("Fig 5  cascade_routing_breakdown",     fig5_routing_breakdown),
        ("Fig 6  pdf_retrieval_improvement",     fig6_retrieval),
        ("Fig 7  cross_topic_validation",        fig7_cross_topic),
    ]

    all_files: list[str] = []
    errors:    list[tuple[str, str]] = []

    for name, fn in figures:
        try:
            files = fn()
            all_files.extend(files)
            print(f"  ✓ {name}")
        except Exception as exc:
            errors.append((name, str(exc)))
            print(f"  ✗ {name}: {exc}", file=sys.stderr)

    n_figs = len(all_files) // 2
    print(f"\nGenerated {n_figs} figures × 2 formats = {len(all_files)} files")
    print(f"Saved to: {OUT_DIR}\n")
    for f in sorted(all_files):
        print(f"  {f}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for name, err in errors:
            print(f"  {name}: {err}")
