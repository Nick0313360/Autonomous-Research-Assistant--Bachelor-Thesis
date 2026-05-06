"""LaTeX table generation for CASCADE-RC manuscript (Phase 13.1).

Run:
    python -m cascade_rc.evaluation.tables \\
        --headline    paper/tables/headline_results.tex \\
        --nmin        paper/tables/nmin_compliance.tex \\
        --budget      paper/tables/budget_split.tex \\
        --walk        paper/tables/walk_ordering.tex \\
        --msensitivity paper/tables/m_sensitivity.tex
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Topic metadata
# ---------------------------------------------------------------------------

_TOPIC_FAMILY: dict[str, str] = {
    "CD008874": "DTA",
    "CD012080": "DTA",
    "CD012768": "DTA",
    "CD011768": "Intervention",
    "CD011975": "Intervention",
    "CD011145": "Prognosis",
}


def _enrich_sweep_row(row: pd.Series) -> dict[str, object]:
    """Derive columns not stored in the parquet."""
    topic_id = str(row["topic_id"])
    m_plus = int(row["m_plus"]) if "m_plus" in row.index else 0
    nmin = int(row["nmin"]) if "nmin" in row.index else 0
    return {
        "family": _TOPIC_FAMILY.get(topic_id, "Unknown"),
        "m_plus_conformal": m_plus,
        "nmin_status": r"\checkmark" if m_plus >= nmin else r"\texttimes",
    }


# ---------------------------------------------------------------------------
# Table 1 — Headline results at α=0.10
# ---------------------------------------------------------------------------

def generate_headline_results_table(
    summary_df: pd.DataFrame,
    output_path: Path,
    alpha: float = 0.10,
) -> None:
    """Per-topic results at α=0.10 for CASCADE-RC (Table 3 in paper)."""
    df = summary_df.copy()

    # Derive columns that may not be in the parquet
    if "family" not in df.columns:
        df["family"] = df["topic_id"].map(_TOPIC_FAMILY).fillna("Unknown")
    if "m_plus_conformal" not in df.columns and "m_plus" in df.columns:
        df["m_plus_conformal"] = df["m_plus"]
    if "nmin_status" not in df.columns and "m_plus" in df.columns and "nmin" in df.columns:
        df["nmin_status"] = df.apply(
            lambda r: r"\checkmark" if r["m_plus"] >= r["nmin"] else r"\texttimes",
            axis=1,
        )

    cols_display = {
        "topic_id": "Topic",
        "family": "Family",
        "m_plus_conformal": r"$m_+$",
        "fnr_test": r"FNR$_\text{test}$",
        "wss_95": r"WSS@95",
        "frac_human_review": r"Esc.\ Rate",
        "lambda_hat_size": r"$|\hat{\Lambda}|$",
        "nmin_status": r"$N_\text{min}$ OK",
    }

    available = {k: v for k, v in cols_display.items() if k in df.columns}
    out = df[list(available.keys())].rename(columns=available).copy()

    fnr_col = r"FNR$_\text{test}$"
    wss_col = r"WSS@95"
    esc_col = r"Esc.\ Rate"
    lam_col = r"$|\hat{\Lambda}|$"

    if fnr_col in out.columns:
        out[fnr_col] = out[fnr_col].map("{:.4f}".format)
    if wss_col in out.columns:
        out[wss_col] = out[wss_col].apply(
            lambda x: "---" if pd.isna(x) or x == -999.0 else f"{x:.4f}"
        )
    if esc_col in out.columns:
        out[esc_col] = out[esc_col].map("{:.3f}".format)
    if lam_col in out.columns:
        out[lam_col] = out[lam_col].apply(
            lambda x: "---" if pd.isna(x) else f"{int(x)}"
        )

    n_cols = len(out.columns)
    col_fmt = "l l " + " ".join(["r"] * (n_cols - 2))

    latex = out.to_latex(
        index=False,
        escape=False,
        column_format=col_fmt,
        caption=(
            rf"CASCADE-RC results at $\alpha={alpha}$, $\delta=0.10$ across all six "
            r"CLEF-TAR 2019 topics. "
            r"FNR$_\text{test} \leq \alpha$ confirms Theorem~5. "
            r"WSS@95 = `---' indicates recall target was not achieved on the test split."
        ),
        label="tab:headline_results",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(latex)
    print(f"  Saved {output_path}")


# ---------------------------------------------------------------------------
# Table 2 — N_min compliance
# ---------------------------------------------------------------------------

def generate_nmin_table(
    compliance_records: list[dict[str, object]],
    output_path: Path,
) -> None:
    """N_min compliance per topic (Table 2 in paper)."""
    df = pd.DataFrame(compliance_records)

    rename_map = {
        "topic_id": "Topic",
        "N_conformal": r"$N_\text{calib}$",
        "m_plus_conformal": r"$m_+$",
        "prevalence_conformal": r"$\pi$",
        "N_min": r"$N_\text{min}$",
        "margin": r"$m_+ - N_\text{min}$",
        "status": "Status",
    }
    available = {k: v for k, v in rename_map.items() if k in df.columns}
    out = df[list(available.keys())].rename(columns=available).copy()

    if r"$\pi$" in out.columns:
        out[r"$\pi$"] = out[r"$\pi$"].map("{:.4f}".format)

    n_cols = len(out.columns)
    col_fmt = "l " + " ".join(["r"] * (n_cols - 1))

    latex = out.to_latex(
        index=False,
        escape=False,
        column_format=col_fmt,
        caption=(
            r"$N_\text{min}$ compliance check for all six topics at "
            r"$\alpha=0.10$, $\delta_\text{LTT}=0.07$. "
            r"$N_\text{min}=26$. CD012768 is retained as a stress case for the "
            r"$m$-sensitivity sweep."
        ),
        label="tab:nmin_compliance",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(latex)
    print(f"  Saved {output_path}")


# ---------------------------------------------------------------------------
# Table 3 — Budget-split sensitivity
# ---------------------------------------------------------------------------

def generate_budget_split_table(
    ablation_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """Budget-split δ_η sensitivity table."""
    required = {"delta_eta", "wss_95", "fnr_test"}
    if not required.issubset(ablation_df.columns):
        missing = required - set(ablation_df.columns)
        warnings.warn(
            f"budget_split_table: missing columns {missing}; skipping.",
            RuntimeWarning,
            stacklevel=2,
        )
        return

    agg_map: dict[str, object] = {
        "mean_wss_95": ("wss_95", "mean"),
        "std_wss_95": ("wss_95", "std"),
        "mean_fnr": ("fnr_test", "mean"),
    }
    if "certificate_valid" in ablation_df.columns:
        agg_map["violations"] = ("certificate_valid", lambda x: (~x).sum())

    summary = ablation_df.groupby("delta_eta").agg(**agg_map).reset_index()
    summary["delta_ltt"] = (0.10 - summary["delta_eta"]).round(3)

    if "violations" in summary.columns:
        summary["Guarantee Violated?"] = summary["violations"].map(
            lambda v: r"\textbf{Yes}" if v > 0 else "No"
        )

    latex = summary.to_latex(
        index=False,
        escape=False,
        float_format="%.4f",
        caption=(
            r"Budget-split sensitivity. "
            r"$\delta_\eta + \delta_\text{LTT} = 0.10$ throughout."
        ),
        label="tab:budget_split",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(latex)
    print(f"  Saved {output_path}")


# ---------------------------------------------------------------------------
# Stub tables (walk_ordering, m_sensitivity) — populated by future sweeps
# ---------------------------------------------------------------------------

def _write_stub_table(output_path: Path, label: str, caption: str) -> None:
    latex = (
        r"\begin{table}[t]" + "\n"
        r"\centering" + "\n"
        rf"\caption{{{caption}}}" + "\n"
        rf"\label{{{label}}}" + "\n"
        r"\begin{tabular}{l}" + "\n"
        r"\toprule" + "\n"
        r"(data not yet available) \\" + "\n"
        r"\bottomrule" + "\n"
        r"\end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(latex)
    print(f"  Saved {output_path} (stub)")


def generate_walk_ordering_table(output_path: Path) -> None:
    _write_stub_table(
        output_path,
        label="tab:walk_ordering",
        caption=r"Safest-to-Riskiest walk ordering sensitivity.",
    )


def generate_m_sensitivity_table(output_path: Path) -> None:
    _write_stub_table(
        output_path,
        label="tab:m_sensitivity",
        caption=r"$m_+$ sensitivity sweep for CD012768.",
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_alpha_sweep_at(artefact_dir: Path, alpha: float = 0.10) -> pd.DataFrame:
    path = artefact_dir / "results" / "alpha_sweep.parquet"
    if not path.exists():
        raise FileNotFoundError(f"alpha_sweep.parquet not found at {path}")
    df = pd.read_parquet(path)
    certified = df[df["status"] == "certified"] if "status" in df.columns else df
    mask = np.isclose(certified["alpha"].astype(float), alpha, rtol=0.0, atol=1e-9)
    return certified[mask].reset_index(drop=True)


def _build_nmin_records(df_at_alpha: pd.DataFrame) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for _, row in df_at_alpha.iterrows():
        m_plus = int(row["m_plus"]) if "m_plus" in row.index else 0
        nmin = int(row["nmin"]) if "nmin" in row.index else 26
        records.append(
            {
                "topic_id": str(row["topic_id"]),
                "N_conformal": "—",  # not stored in parquet; populated post-split
                "m_plus_conformal": m_plus,
                "prevalence_conformal": float("nan"),  # idem
                "N_min": nmin,
                "margin": m_plus - nmin,
                "status": r"\checkmark" if m_plus >= nmin else r"\texttimes",
            }
        )
    return records


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artefact-dir", type=Path, default=Path("artefacts/cascade_rc"))
    parser.add_argument("--alpha", type=float, default=0.10)
    parser.add_argument("--headline", type=Path, help="Output path for headline results table")
    parser.add_argument("--nmin", type=Path, help="Output path for N_min compliance table")
    parser.add_argument("--budget", type=Path, help="Output path for budget-split table")
    parser.add_argument("--walk", type=Path, help="Output path for walk-ordering table")
    parser.add_argument("--msensitivity", type=Path, help="Output path for m-sensitivity table")
    args = parser.parse_args(argv)

    artefact_dir = args.artefact_dir

    df_at_alpha = _load_alpha_sweep_at(artefact_dir, alpha=args.alpha)

    if args.headline:
        generate_headline_results_table(df_at_alpha, args.headline, alpha=args.alpha)

    if args.nmin:
        records = _build_nmin_records(df_at_alpha)
        generate_nmin_table(records, args.nmin)

    if args.budget:
        budget_path = artefact_dir / "ablations" / "budget_split.parquet"
        if budget_path.exists():
            budget_df = pd.read_parquet(budget_path)
            generate_budget_split_table(budget_df, args.budget)
        else:
            warnings.warn(
                f"{budget_path} not found; budget-split table skipped.",
                RuntimeWarning,
                stacklevel=1,
            )

    if args.walk:
        generate_walk_ordering_table(args.walk)

    if args.msensitivity:
        generate_m_sensitivity_table(args.msensitivity)


if __name__ == "__main__":
    _main()
