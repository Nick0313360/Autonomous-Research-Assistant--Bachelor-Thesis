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
