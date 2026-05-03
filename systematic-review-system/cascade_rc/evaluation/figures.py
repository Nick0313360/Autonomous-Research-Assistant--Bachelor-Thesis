"""Publication figures for CASCADE-RC systematic review screening.

Generates three IEEE-quality figures as both .pdf and .png.
Run:
    PYTHONHASHSEED=0 python -m cascade_rc.evaluation.figures \\
        --artefact-dir artefacts/cascade_rc
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 0
ALPHAS: list[float] = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]
METHODS: list[str] = ["CASCADE-RC", "AUTOSTOP", "RLStop", "SCRC-T", "SCRC-I"]
TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]
FIGSIZE = (3.5, 2.6)

_METHOD_COLORS: dict[str, str] = {
    "CASCADE-RC": "#1f77b4",
    "AUTOSTOP":   "#ff7f0e",
    "RLStop":     "#2ca02c",
    "SCRC-T":     "#d62728",
    "SCRC-I":     "#9467bd",
}
_METHOD_MARKERS: dict[str, str] = {
    "CASCADE-RC": "o",
    "AUTOSTOP":   "s",
    "RLStop":     "^",
    "SCRC-T":     "D",
    "SCRC-I":     "v",
}

_ROUTING_LABELS = ["cheap-reject", "auto-include", "LLM-self-evident", "human"]
_ROUTING_COLS   = ["cheap_reject", "auto_include", "llm", "human"]
_ROUTING_COLORS = ["#aec7e8", "#98df8a", "#ffbb78", "#ff9896"]

_PDF_META: dict[str, str] = {
    "Creator":      "cascade_rc.evaluation.figures",
    # blank fields suppress timestamp metadata so PDF bytes are reproducible
    "Title":        "",
    "Subject":      "",
    "Author":       "",
    "CreationDate": "",
    "ModDate":      "",
}


# ---------------------------------------------------------------------------
# Style helper
# ---------------------------------------------------------------------------

def _apply_ieee_style() -> None:
    """Apply IEEEtran-friendly matplotlib style in-place."""
    plt.rcParams.update(
        {
            "font.family":        "serif",
            "font.size":          8,
            "axes.titlesize":     8,
            "axes.labelsize":     8,
            "xtick.labelsize":    7,
            "ytick.labelsize":    7,
            "legend.fontsize":    6,
            "lines.linewidth":    1.0,
            "lines.markersize":   3.5,
            "axes.linewidth":     0.6,
            "grid.linewidth":     0.4,
            "grid.alpha":         0.4,
            "figure.dpi":         150,
            "savefig.bbox":       "tight",
            "savefig.pad_inches": 0.01,
        }
    )


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------

def _synthetic_figure1_data(rng: np.random.Generator) -> pd.DataFrame:
    """Figure 1 synthetic: FNR vs alpha per method, CASCADE-RC below diagonal."""
    rows: list[dict] = []
    for method in METHODS:
        alphas = ALPHAS if method == "CASCADE-RC" else [0.05, 0.10, 0.20]
        for alpha in alphas:
            for topic in TOPICS:
                if method == "CASCADE-RC":
                    fnr = float(alpha * rng.uniform(0.50, 0.95))  # strictly below alpha (validity guarantee)
                    wss = float(rng.uniform(0.35, 0.65))           # CASCADE-RC WSS range
                else:
                    noise = float(rng.normal(0.0, 0.025))
                    fnr = float(np.clip(alpha + noise, 0.0, 1.0))  # baselines can cross diagonal
                    wss = float(rng.uniform(0.20, 0.60))            # baseline WSS range
                rows.append(
                    {"method": method, "topic_id": topic,
                     "alpha": alpha, "fnr": fnr, "wss": wss}
                )
    return pd.DataFrame(rows)


def _synthetic_figure2_data(rng: np.random.Generator) -> pd.DataFrame:
    """Figure 2 synthetic: WSS vs target_recall per method."""
    rows: list[dict] = []
    _wss_base = {
        "CASCADE-RC": 0.60, "AUTOSTOP": 0.50,
        "RLStop": 0.45, "SCRC-T": 0.42, "SCRC-I": 0.40,
    }
    assert set(_wss_base) == set(METHODS), f"_wss_base keys out of sync with METHODS"
    for method in METHODS:
        base = _wss_base[method]
        for recall in RECALLS:
            for topic in TOPICS:
                penalty = (recall - 0.80) * 0.8  # WSS drops ~0.8 per recall unit beyond minimum
                wss = float(np.clip(base - penalty + rng.normal(0.0, 0.03), 0.0, 1.0))
                rows.append(
                    {"method": method, "topic_id": topic,
                     "target_recall": recall, "wss": wss}
                )
    return pd.DataFrame(rows)


def _synthetic_figure3_data(rng: np.random.Generator) -> pd.DataFrame:
    """Figure 3 synthetic: routing fractions vs alpha for CASCADE-RC."""
    rows: list[dict] = []
    for alpha in ALPHAS:
        tightness = 1.0 - (alpha / 0.30)
        base_reject  = 0.55 - tightness * 0.30
        base_accept  = 0.25 - tightness * 0.05
        base_llm     = 0.10 + tightness * 0.05
        base_human   = 0.10 + tightness * 0.30
        noise = rng.normal(0.0, 0.01, 4)
        fracs = np.array([base_reject, base_accept, base_llm, base_human]) + noise
        fracs = np.clip(fracs, 0.01, None)
        fracs /= fracs.sum()
        rows.append(
            {
                "alpha":        alpha,
                "cheap_reject": float(fracs[0]),
                "auto_include": float(fracs[1]),
                "llm":          float(fracs[2]),
                "human":        float(fracs[3]),
            }
        )
    return pd.DataFrame(rows)
