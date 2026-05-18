"""Generate the four manuscript figures for CASCADE-RC.

Usage:
    python3 generate_figures.py                     # → paper/figures/
    python3 generate_figures.py --out-dir my/dir
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

# ── global rcParams — used by Fig 1 only ─────────────────────────────────────
plt.rcParams.update({
    "font.family":         "serif",
    "mathtext.fontset":    "cm",
    "font.size":           9,
    "axes.labelsize":      9,
    "axes.titlesize":      9,
    "legend.fontsize":     8,
    "xtick.labelsize":     8,
    "ytick.labelsize":     8,
    "lines.linewidth":     1.4,
    "lines.markersize":    5.0,
    "figure.dpi":          200,
    "axes.spines.top":     False,
    "axes.spines.right":   False,
})

# ── color palette for Figs 2–4 ────────────────────────────────────────────────
COLORS = {
    "cascade":  "#2166AC",
    "scrc_t":   "#D6604D",
    "scrc_i":   "#F4A582",
    "autostop": "#4DAC26",
    "rlstop":   "#7B3294",
}

# seaborn context overrides for Figs 2–4
_FIG_STYLE = {
    "axes.labelsize":  12,
    "axes.titlesize":  12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize":  9,
    "lines.linewidth":  1.8,
    "lines.markersize": 6.0,
    "font.family":      "sans-serif",
    "figure.dpi":       300,
}

ALPHA_SWEEP  = Path("artefacts/cascade_rc/results/alpha_sweep.parquet")
BUDGET_SPLIT = Path("artefacts/cascade_rc/ablations/budget_split.parquet")
DATA_DIR     = Path("artefacts/cascade_rc/data")
RESULTS_DIR  = Path("artefacts/cascade_rc/results")


def _save(fig, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out_dir}/{stem}.pdf/.png")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 1 — CASCADE-RC pipeline schematic
# ═══════════════════════════════════════════════════════════════════════════════
def fig1_schematic(out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(12.0, 6.0))
    ax.set_xlim(-0.5, 15.0)
    ax.set_ylim(-2.5, 7.5)
    ax.axis("off")

    def _box(cx, cy, w, h, text, fc="white", ec="#222222", fs=8.5):
        rect = mpatches.FancyBboxPatch(
            (cx - w/2, cy - h/2), w, h,
            boxstyle="square,pad=0.10", fc=fc, ec=ec, lw=1.1, zorder=3,
        )
        ax.add_patch(rect)
        ax.text(cx, cy, text, ha="center", va="center",
                fontsize=fs, zorder=4)

    def _seg(x1, y1, x2, y2, lc="#333333", lw=1.0):
        ax.plot([x1, x2], [y1, y2], color=lc, lw=lw, zorder=2)

    def _arrowhead(x1, y1, x2, y2, lc="#333333", lw=1.0):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=lc, lw=lw,
                                   mutation_scale=10), zorder=2)

    # ── main pipeline boxes ─────────────────────────────────────────────────
    #  Input → Scorer → Gate → (Accept | LLM → Human | Reject)
    _box(1.3, 3.0, 1.9, 0.90,
         r"$(X,Y)\!\sim\!\mathcal{P}$" + "\nAbstract", fs=8.5)
    _box(3.9, 3.0, 2.2, 0.90,
         r"$s = f(X)$" + "\nSPECTER2 + BM25", fs=8.0)
    _box(6.4, 3.0, 1.6, 0.90,
         "Route\n" + r"$(s,\,u)$", fc="#f6f6f6", ec="#333333", fs=8.0)

    # output boxes
    BOUT_CX = 9.5
    _box(BOUT_CX, 5.8, 2.6, 0.90,
         r"$s \geq \lambda_{\rm hi}$" + "  →  Include",
         fc="#eaf4ea", ec="#2a7d2a", fs=8.5)
    _box(BOUT_CX, 3.0, 2.6, 0.90,
         r"$\lambda_{\rm lo}\!\leq\!s\!<\!\lambda_{\rm hi}$" + "\nLLM-1 ensemble  $u$",
         fc="#fffbe6", ec="#b8860b", fs=8.0)
    _box(BOUT_CX, 0.2, 2.6, 0.90,
         r"$s < \lambda_{\rm lo}$" + "  →  Exclude",
         fc="#fdecea", ec="#c0392b", fs=8.5)
    _box(12.5, 2.1, 1.6, 0.80,
         "Human\nreview", fc="#f0e8f8", ec="#6f42c1", fs=7.5)

    # ── routing (L-shaped, no diagonals) ────────────────────────────────────
    GATE_R  = 6.4 + 0.80          # = 7.20  (gate right edge)
    ELBOW_X = 7.55                 # vertical column for branching
    BOX_L   = BOUT_CX - 1.30      # = 8.20  (output boxes left edge)

    # Input → Scorer → Gate
    _arrowhead(2.25, 3.0, 2.80, 3.0)
    _arrowhead(5.00, 3.0, 5.60, 3.0)

    # Gate → elbow
    _seg(GATE_R, 3.0, ELBOW_X, 3.0)

    # Elbow → Accept (up then right)
    _seg(ELBOW_X, 3.0, ELBOW_X, 5.8)
    _arrowhead(ELBOW_X, 5.8, BOX_L, 5.8)

    # Elbow → LLM (straight right)
    _arrowhead(ELBOW_X, 3.0, BOX_L, 3.0)

    # Elbow → Reject (down then right)
    _seg(ELBOW_X, 3.0, ELBOW_X, 0.2)
    _arrowhead(ELBOW_X, 0.2, BOX_L, 0.2)

    # LLM → Human (right then down then right)
    LLM_R        = BOUT_CX + 1.30  # = 10.80
    HUM_ELBOW_X  = 11.15
    HUM_L        = 12.5 - 0.80     # = 11.70
    _seg(LLM_R, 3.0, HUM_ELBOW_X, 3.0)
    _seg(HUM_ELBOW_X, 3.0, HUM_ELBOW_X, 2.1)
    _arrowhead(HUM_ELBOW_X, 2.1, HUM_L, 2.1)

    # ── route labels ─────────────────────────────────────────────────────────
    # place LEFT of the elbow vertical segment (x=7.55)
    ax.text(7.30, 4.75, r"$\lambda_{\rm hi}$", fontsize=8.5,
            color="#2a7d2a", ha="center", va="center")
    ax.text(7.30, 1.45, r"$\lambda_{\rm lo}$", fontsize=8.5,
            color="#c0392b", ha="center", va="center")
    # above the LLM horizontal arrow
    ax.text(7.85, 3.22, "band", fontsize=7.5, color="#b8860b",
            ha="center", va="center")
    # next to the human-route vertical segment
    ax.text(11.40, 2.55, r"$u < \tau_{\rm SE}$", fontsize=7.5,
            color="#6f42c1", ha="left", va="center")

    # ── loss annotations — all placed BELOW their box via annotate() ─────────
    # Accept (no FNR loss) — below accept box bottom (5.8 - 0.45 = 5.35)
    ax.annotate(
        r"$\tilde{\mathcal{L}}$: no FNR loss" + "\n(item included)",
        xy=(BOUT_CX, 5.35),
        xytext=(BOUT_CX, 4.40),
        fontsize=7.5, color="#2a7d2a", ha="center", va="center", style="italic",
        bbox=dict(fc="white", ec="#2a7d2a", alpha=0.92, pad=4,
                  lw=0.8, boxstyle="round,pad=0.35"),
        arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#2a7d2a", mutation_scale=9),
        zorder=6,
    )
    # LLM (coupled surrogate + η) — below LLM box bottom (3.0 - 0.45 = 2.55)
    ax.annotate(
        r"$\tilde{\mathcal{L}}$: coupled surrogate loss" + "\n"
        + r"$\eta$ = LLM coupling slack",
        xy=(BOUT_CX, 2.55),
        xytext=(BOUT_CX, 1.55),
        fontsize=7.5, color="#b8860b", ha="center", va="center", style="italic",
        bbox=dict(fc="white", ec="#b8860b", alpha=0.92, pad=4,
                  lw=0.8, boxstyle="round,pad=0.35"),
        arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#b8860b", mutation_scale=9),
        zorder=6,
    )
    # Reject (FNR incurred) — below reject box bottom (0.2 - 0.45 = -0.25)
    ax.annotate(
        r"$\tilde{\mathcal{L}}$: incurs loss if $Y\!=\!1$" + "\n(false negative)",
        xy=(BOUT_CX, -0.25),
        xytext=(BOUT_CX, -1.30),
        fontsize=7.5, color="#c0392b", ha="center", va="center", style="italic",
        bbox=dict(fc="white", ec="#c0392b", alpha=0.92, pad=4,
                  lw=0.8, boxstyle="round,pad=0.35"),
        arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#c0392b", mutation_scale=9),
        zorder=6,
    )
    # Human review (loss=0) — below human box bottom (2.1 - 0.40 = 1.70)
    # placed at x=12.5, well to the right of reject box (right edge 10.80)
    ax.annotate(
        r"$\tilde{\mathcal{L}}\!=\!0$" + "\n(ground truth\nrecovered)",
        xy=(12.5, 1.70),
        xytext=(12.5, 0.55),
        fontsize=7.5, color="#6f42c1", ha="center", va="center", style="italic",
        bbox=dict(fc="white", ec="#6f42c1", alpha=0.92, pad=4,
                  lw=0.8, boxstyle="round,pad=0.35"),
        arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#6f42c1", mutation_scale=9),
        zorder=6,
    )

    # ── score axis inset (bottom-left, in empty space) ───────────────────────
    ax_ins = fig.add_axes([0.03, 0.08, 0.115, 0.175])
    xs = np.linspace(0, 1, 300)
    ax_ins.fill_between(xs, 0, np.where(xs < 0.28, 1, 0),
                        color="#fdecea", alpha=0.85)
    ax_ins.fill_between(xs, 0, np.where((xs >= 0.28) & (xs < 0.68), 1, 0),
                        color="#fffbe6", alpha=0.85)
    ax_ins.fill_between(xs, 0, np.where(xs >= 0.68, 1, 0),
                        color="#eaf4ea", alpha=0.85)
    for xv, lbl, col in [
        (0.28, r"$\lambda_{\rm lo}$", "#c0392b"),
        (0.68, r"$\lambda_{\rm hi}$", "#2a7d2a"),
    ]:
        ax_ins.axvline(xv, color=col, lw=0.9, ls="--")
        ax_ins.text(xv, 1.14, lbl, ha="center", fontsize=7.0, color=col,
                    transform=ax_ins.get_xaxis_transform())
    ax_ins.set_xlim(0, 1)
    ax_ins.set_ylim(0, 1)
    ax_ins.set_yticks([])
    ax_ins.set_xlabel("Score $s$", fontsize=7.5)
    ax_ins.tick_params(labelsize=6.5)

    fig.tight_layout(rect=[0.14, 0, 1, 1])
    _save(fig, out_dir, "fig1_cascade_schematic")


# ═══════════════════════════════════════════════════════════════════════════════
# shared FNR-panel helper (used by Figs 2 & 3, seaborn context already active)
# ═══════════════════════════════════════════════════════════════════════════════
def _draw_fnr_panel(ax: plt.Axes, df: pd.DataFrame, tid: str,
                    ylim_top: float = 0.50) -> None:
    all_r  = df[df["topic_id"] == tid].sort_values("alpha")
    cert_r = all_r[all_r["status"] == "certified"]
    abs_r  = all_r[all_r["status"] != "certified"]

    # y = x safety boundary
    xs = np.linspace(0, 0.22, 200)
    ax.plot(xs, xs, color="black", ls="--", lw=1.3, alpha=0.65,
            label="Safety bound  y=α", zorder=1)

    # ABSTAIN shaded band — text placed low so it never clashes with annotations
    if not abs_r.empty:
        x_end = float(abs_r["alpha"].max()) + 0.007
        ax.axvspan(0, x_end, alpha=0.07, color="#888888", zorder=0)
        ax.text(x_end / 2, ylim_top * 0.30, "ABSTAIN", fontsize=8, color="#888888",
                ha="center", va="center", rotation=90, style="italic")

    # CASCADE-RC
    ax.plot(cert_r["alpha"], cert_r["fnr_test"],
            color=COLORS["cascade"], ls="-", lw=2.2, marker="o", ms=7,
            label="CASCADE-RC", zorder=4)

    # Baselines
    for key, col, lbl, ls in [
        ("scrc_t",   "scrc_t_fnr",  "SCRC-T",   "--"),
        ("scrc_i",   "scrc_i_fnr",  "SCRC-I",   ":"),
        ("autostop", "autostop_fnr","AutoStop",  "-."),
        ("rlstop",   "rlstop_fnr",  "RLStop",   (0, (5, 2, 1, 2))),
    ]:
        sub = all_r.dropna(subset=[col])
        if sub.empty:
            continue
        ax.plot(sub["alpha"], sub[col],
                color=COLORS[key], ls=ls, lw=1.8, marker=".", ms=7,
                label=lbl, alpha=0.90, zorder=2)

    ax.set_xlabel("Target risk  α", fontsize=12)
    ax.set_ylabel("Empirical FNR", fontsize=12)
    ax.set_xlim(0, 0.22)
    ax.set_ylim(-0.01, ylim_top)
    ax.tick_params(labelsize=10)
    ax.legend(fontsize=8.5, loc="upper left", framealpha=0.9)


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 2 — CD008874 two-panel
# ═══════════════════════════════════════════════════════════════════════════════
def fig2_cd008874(df: pd.DataFrame, out_dir: Path) -> None:
    with plt.style.context(["seaborn-v0_8-whitegrid", _FIG_STYLE]):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.0))

        # ── Left: FNR vs α ──────────────────────────────────────────────────
        _draw_fnr_panel(ax1, df, "CD008874", ylim_top=0.52)
        ax1.set_title("CD008874 — FNR vs α", fontsize=12, fontweight="bold")

        # SCRC-T violation annotation — placed in upper-right clear zone
        ax1.annotate(
            "SCRC-T violates\ny=α bound at all tested α",
            xy=(0.10, 0.333),
            xytext=(0.12, 0.46),
            fontsize=9, color=COLORS["scrc_t"],
            arrowprops=dict(arrowstyle="->", lw=1.0, color=COLORS["scrc_t"]),
            bbox=dict(fc="white", ec=COLORS["scrc_t"], alpha=0.92, pad=3,
                      lw=0.8, boxstyle="round,pad=0.3"),
            zorder=7,
        )

        # ── Right: WSS@95 vs α (CASCADE-RC only) ─────────────────────────────
        cert_r = df[(df["topic_id"] == "CD008874") &
                    (df["status"] == "certified")].sort_values("alpha")
        valid  = cert_r[cert_r["wss_95"] != -999.0]
        sent_r = cert_r[cert_r["wss_95"] == -999.0]

        ax2.axhline(0, color="black", ls="--", lw=1.0, alpha=0.45,
                    label="WSS = 0 reference", zorder=1)

        ax2.plot(valid["alpha"], valid["wss_95"],
                 color=COLORS["cascade"], ls="-", lw=2.2, marker="o", ms=7,
                 label="CASCADE-RC", zorder=3)

        # Peak star + annotation
        peak = valid.loc[valid["wss_95"].idxmax()]
        pa, pw = float(peak["alpha"]), float(peak["wss_95"])
        ax2.scatter([pa], [pw], marker="*", s=260,
                    color="#FFD700", edgecolors="#B8860B", lw=1.0, zorder=6)
        ax2.annotate(
            f"Peak WSS = {pw:.2%}\nα = {pa:.2f}",
            xy=(pa, pw), xytext=(pa + 0.028, pw - 0.095),
            fontsize=9, color="#333333",
            arrowprops=dict(arrowstyle="->", lw=0.8, color="#666666"),
            bbox=dict(fc="white", ec="#aaaaaa", alpha=0.92, pad=3,
                      lw=0.7, boxstyle="round,pad=0.3"),
            zorder=7,
        )

        # Undefined WSS (recall < 95%)
        if not sent_r.empty:
            ax2.scatter(sent_r["alpha"], np.zeros(len(sent_r)),
                        marker="x", s=90, lw=2.2, color="#c0392b", zorder=5,
                        label="WSS undefined  (recall < 95%)")

        ax2.set_xlabel("Target risk  α", fontsize=12)
        ax2.set_ylabel("WSS@95", fontsize=12)
        ax2.set_xlim(0, 0.22)
        ax2.set_ylim(-0.07, 0.52)
        ax2.tick_params(labelsize=10)
        ax2.set_title("CD008874 — WSS@95 vs α", fontsize=12, fontweight="bold")
        ax2.legend(fontsize=8.5, loc="upper left", framealpha=0.9)

        fig.tight_layout()
        _save(fig, out_dir, "fig2_cd008874")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 3 — CD011975 two-panel (FNR sweep + score histogram)
# ═══════════════════════════════════════════════════════════════════════════════
def fig3_cd011975(df: pd.DataFrame, out_dir: Path) -> None:
    # escalation rate from eval JSON
    esc_rate = 0.4225
    eval_p = RESULTS_DIR / "CD011975_eval.json"
    if eval_p.exists():
        ev = json.load(open(eval_p))
        esc_rate = ev.get("frac_escalated", esc_rate)

    with plt.style.context(["seaborn-v0_8-whitegrid", _FIG_STYLE]):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.0))

        # ── Left: FNR vs α ──────────────────────────────────────────────────
        # CD011975 max certified FNR ≈ 0.149; baseline ceiling ≈ 0.207
        # Tighter ylim spreads the lines out; banner placed via transAxes
        _draw_fnr_panel(ax1, df, "CD011975", ylim_top=0.30)
        ax1.set_title("CD011975 — FNR vs α", fontsize=12, fontweight="bold")

        # Shaded region + banner: α ≥ 0.10 → recall < 95%, WSS undefined
        ax1.axvspan(0.097, 0.215, alpha=0.10, color="#c0392b", zorder=0)
        ax1.axvline(0.10, color="#c0392b", ls="--", lw=1.3, alpha=0.55, zorder=2)
        ax1.text(
            0.97, 0.97,
            "Recall < 95% for α ≥ 0.10\nWSS@95 undefined",
            fontsize=8.5, color="#8b0000", ha="right", va="top",
            transform=ax1.transAxes,
            bbox=dict(fc="mistyrose", ec="#c0392b", alpha=0.92, pad=4,
                      lw=0.8, boxstyle="round,pad=0.3"),
            zorder=6,
        )

        # ── Right: Score histogram [0, 0.025] ────────────────────────────────
        data_path = DATA_DIR / "CD011975.parquet"
        if data_path.exists():
            d   = pd.read_parquet(data_path)
            neg = d[d["y_abstract"] == 0]["s"].dropna().values
            pos = d[d["y_abstract"] == 1]["s"].dropna().values

            bins = np.linspace(0.0, 0.025, 65)
            ax2.hist(neg, bins=bins, density=True,
                     color=COLORS["scrc_t"], alpha=0.50,
                     label=f"Negatives  (n={len(neg):,})")
            ax2.hist(pos, bins=bins, density=True,
                     color=COLORS["cascade"], alpha=0.55,
                     label=f"Positives  (n={len(pos):,})")

            ax2.set_xlim(0.0, 0.025)
            ax2.xaxis.set_major_formatter(
                plt.matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.3f}")
            )
            ax2.set_xlabel("Base-ranker score  s(X)", fontsize=12)
            ax2.set_ylabel("Density", fontsize=12)
            ax2.tick_params(labelsize=10)
            ax2.set_title("CD011975 — Score distribution", fontsize=12,
                          fontweight="bold")
            ax2.legend(fontsize=9, loc="upper right", framealpha=0.9)

            # Poor separability text box
            ax2.text(
                0.97, 0.63,
                f"Poor class separability:\ncascade collapses to full\n"
                f"LLM escalation ({esc_rate:.1%})",
                transform=ax2.transAxes, fontsize=9, color="#333333",
                ha="right", va="center",
                bbox=dict(fc="lightyellow", ec="#b8860b", alpha=0.92, pad=5,
                          lw=0.8, boxstyle="round,pad=0.4"),
            )

        fig.tight_layout()
        _save(fig, out_dir, "fig3_cd011975")


# ═══════════════════════════════════════════════════════════════════════════════
# FIG 4 — Budget-split ablation (two panels, one per topic)
# ═══════════════════════════════════════════════════════════════════════════════
def fig4_budget_split(budget: pd.DataFrame, out_dir: Path) -> None:
    b = budget.copy()
    # η̂⁺_boot = mean_eta_lcb / slack_ratio  (bootstrap UCB on mean slack)
    b["eta_boot_upper"] = np.where(
        b["slack_ratio"] > 0,
        b["mean_eta_lcb"] / b["slack_ratio"],
        np.nan,
    )

    with plt.style.context(["seaborn-v0_8-whitegrid", _FIG_STYLE]):
        fig, axes = plt.subplots(1, 2, figsize=(12, 5.0))

        for ax, tid in zip(axes, ["CD008874", "CD011975"]):
            sub = b[b["topic_id"] == tid].sort_values("delta_eta")
            xv  = sub["delta_eta"].values

            ucb_vals = sub["eta_boot_upper"].values
            lcb_vals = sub["mean_eta_lcb"].values

            # θ̂⁺ Bootstrap UCB (dashed red)
            ax.plot(xv, ucb_vals,
                    color=COLORS["scrc_t"], ls="--", lw=2.2, marker="s", ms=8,
                    label=r"$\hat{\theta}^{+}$ Bootstrap UCB", zorder=3)

            # Mean η̂⁻ WSR LCB (solid blue)
            ax.plot(xv, lcb_vals,
                    color=COLORS["cascade"], ls="-", lw=2.2, marker="o", ms=8,
                    label=r"Mean $\hat{\eta}^{-}$  (WSR LCB)", zorder=3)

            # Shaded gap
            ax.fill_between(xv, lcb_vals, ucb_vals,
                             alpha=0.12, color="#888888", zorder=1)

            ax.set_xlabel(r"$\delta_\eta$ budget", fontsize=12)
            ax.set_ylabel(r"Slack estimate  $\hat{\eta}$", fontsize=12)
            ax.set_title(f"{tid} — Budget-split ablation", fontsize=12,
                         fontweight="bold")
            ax.set_xlim(xv.min() - 0.005, xv.max() + 0.005)
            # Explicit top gives 30 % headroom above Bootstrap UCB
            y_top = float(np.nanmax(ucb_vals)) * 1.30
            ax.set_ylim(-0.005, y_top)
            ax.tick_params(labelsize=10)
            ax.legend(fontsize=9, loc="upper left", framealpha=0.9)

            # Slack ratio annotation (right side)
            sr_lo = sub["slack_ratio"].min()
            sr_hi = sub["slack_ratio"].max()
            ax.text(
                0.97, 0.32,
                f"Slack ratio\n{sr_lo:.3f} – {sr_hi:.3f}",
                transform=ax.transAxes, fontsize=9, ha="right", va="center",
                color="#444444",
                bbox=dict(fc="white", ec="#888888", alpha=0.92, pad=4,
                          lw=0.7, boxstyle="round,pad=0.35"),
            )

        # Lipschitz note in second panel (more room there)
        axes[1].text(
            0.50, 0.28,
            "Lipschitz covering (§11.1) would raise\nper-point δ by ×40, making LCB informative",
            transform=axes[1].transAxes, fontsize=8.5, ha="center", va="center",
            color="#555555", style="italic",
            bbox=dict(fc="lightyellow", ec="#b8860b", alpha=0.92, pad=4,
                      lw=0.7, boxstyle="round,pad=0.4"),
        )

        fig.tight_layout()
        _save(fig, out_dir, "fig4_budget_split_ablation")


# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("paper/figures"))
    args = parser.parse_args()

    sweep  = pd.read_parquet(ALPHA_SWEEP)
    budget = pd.read_parquet(BUDGET_SPLIT)

    print(f"alpha_sweep : {len(sweep)} rows")
    print(f"budget_split: {len(budget)} rows")
    print(f"output dir  : {args.out_dir}\n")

    print("Fig 1 — pipeline schematic (unchanged)...")
    fig1_schematic(args.out_dir)

    print("Fig 2 — CD008874 (seaborn, new palette)...")
    fig2_cd008874(sweep, args.out_dir)

    print("Fig 3 — CD011975 + score histogram...")
    fig3_cd011975(sweep, args.out_dir)

    print("Fig 4 — budget-split ablation...")
    fig4_budget_split(budget, args.out_dir)

    print(f"\nDone. All figures in {args.out_dir}/")


if __name__ == "__main__":
    main()
