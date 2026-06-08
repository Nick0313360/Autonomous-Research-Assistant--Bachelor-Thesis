"""Evaluation metrics for CASCADE-RC systematic review screening."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

_DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]


def wss_at_recall(
    predictions: np.ndarray,
    y_true: np.ndarray,
    target_recall: float = 0.95,
) -> dict:
    """Work Saved over Sampling at target recall (CLEF / Cohen 2006 formula).

    WSS@r = (TN + FN) / N - (1 - r), evaluated at the certified θ̂ routing.

    Returns:
        dict with keys:
            wss (float | nan): WSS value, or nan if recall target was missed.
            achieved_recall (float): recall of the given predictions.
            status (str): "ok" | "recall_target_missed" | "no_relevant_docs".
    """
    n_relevant = int(np.sum(y_true == 1))
    if n_relevant == 0:
        return {
            "wss": float("nan"),
            "achieved_recall": float("nan"),
            "status": "no_relevant_docs",
        }
    achieved = float(np.sum((predictions == 1) & (y_true == 1)) / n_relevant)
    if achieved < target_recall:
        return {
            "wss": float("nan"),
            "achieved_recall": achieved,
            "status": "recall_target_missed",
        }
    tn = int(np.sum((predictions == 0) & (y_true == 0)))
    fn = int(np.sum((predictions == 0) & (y_true == 1)))
    n = len(y_true)
    wss = (tn + fn) / n - (1.0 - target_recall)
    return {"wss": wss, "achieved_recall": achieved, "status": "ok"}


def abstention_rate(certified: dict[str, dict]) -> float:
    """Fraction of topics that abstained. Returns nan for empty input.

    Args:
        certified: mapping topic_id → {status: "certified"|"abstained", ...}.

    Returns:
        Float in [0, 1], or nan if certified is empty.
    """
    if not certified:
        return float("nan")
    n_abstained = sum(1 for v in certified.values() if v.get("status") == "abstained")
    return float(n_abstained / len(certified))


_VALID_DECISIONS: frozenset[str] = frozenset(
    {"auto_accept", "auto_reject", "llm_escalate", "human_review"}
)


def llm_query_volume(routing: pd.DataFrame) -> dict:
    """Aggregate routing decisions into a volume breakdown dict.

    Args:
        routing: DataFrame with columns {pmid: str, decision: str} where
                 decision ∈ {auto_accept, auto_reject, llm_escalate, human_review}.

    Returns:
        dict with keys auto_accept, auto_reject, llm_escalate, human_review,
        total (int), llm_fraction (float).

    Raises:
        ValueError: if any decision value is not in _VALID_DECISIONS.
    """
    unknown = set(routing["decision"].unique()) - _VALID_DECISIONS
    if unknown:
        raise ValueError(f"Unexpected decision values: {unknown!r}")
    counts = routing["decision"].value_counts().to_dict()
    total = int(len(routing))
    llm_escalate = counts.get("llm_escalate", 0)
    return {
        "auto_accept":  int(counts.get("auto_accept", 0)),
        "auto_reject":  int(counts.get("auto_reject", 0)),
        "llm_escalate": int(llm_escalate),
        "human_review": int(counts.get("human_review", 0)),
        "total": total,
        "llm_fraction": llm_escalate / total if total > 0 else 0.0,
    }


def bootstrap_eta_upper(
    slack_mat: np.ndarray,
    delta: float,
    B: int = 1000,
    seed: int = 0,
) -> np.ndarray:
    """Bootstrap (1−delta) upper confidence bound on mean slack per grid point.

    Args:
        slack_mat: (G, m_plus) float64 from CertificationResult.slack_mat.
        delta:     Confidence level — use config.ltt.delta_bootstrap.
        B:         Number of bootstrap resamples (default 1000).
        seed:      RNG seed for reproducibility.

    Returns:
        (G,) array: for each grid point, the (1−delta)-quantile of B bootstrap means.
    """
    G, m_plus = slack_mat.shape
    rng = np.random.default_rng(seed)
    boot_means = np.empty((G, B), dtype=np.float64)
    for b in range(B):
        idx = rng.integers(0, m_plus, size=(G, m_plus))         # (G, m_plus)
        boot_means[:, b] = slack_mat[np.arange(G)[:, None], idx].mean(axis=1)
    return np.quantile(boot_means, 1.0 - delta, axis=1)         # (G,)


def slack_ratio_diagnostic(
    eta_lcb: np.ndarray,
    eta_boot_upper: np.ndarray,
) -> np.ndarray:
    """Element-wise tightness ratio η̂⁻⋆ / η̂⁺_boot (paper §9.4).

    Values ≈ 1: WSR LCB is tight relative to bootstrap estimate.
    Values << 1: bound is conservative.
    Returns nan where eta_boot_upper == 0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(eta_boot_upper > 0.0, eta_lcb / eta_boot_upper, np.nan)


_SCREENED_DECISIONS: frozenset[str] = frozenset(
    {"auto_accept", "llm_escalate", "human_review"}
)


def _derive_routing(df: pd.DataFrame, theta_hat: np.ndarray) -> pd.DataFrame:
    """Apply certified threshold θ̂ = (λ_lo, λ_hi, τ_SE) to produce a decision column.

    Args:
        df:        DataFrame with columns s (float) and u (float).
        theta_hat: (3,) array [λ_lo, λ_hi, τ_SE].

    Returns:
        Copy of df with column 'decision' ∈
        {auto_accept, auto_reject, llm_escalate, human_review}.
    """
    lam_lo = float(theta_hat[0])
    lam_hi = float(theta_hat[1])
    tau_se = float(theta_hat[2])

    s = df["s"].to_numpy(dtype=np.float64)
    u = df["u"].to_numpy(dtype=np.float64)

    decision = np.empty(len(df), dtype=object)
    decision[s < lam_lo] = "auto_reject"
    decision[s >= lam_hi] = "auto_accept"
    uncertain = (s >= lam_lo) & (s < lam_hi)
    decision[uncertain & (u >= tau_se)] = "llm_escalate"
    decision[uncertain & (u < tau_se)] = "human_review"

    out = df.copy()
    out["decision"] = decision
    return out


def _predictions_from_routing(routing: pd.DataFrame) -> np.ndarray:
    """Convert decision column to binary predictions: 1=screened, 0=skipped."""
    return routing["decision"].isin(_SCREENED_DECISIONS).to_numpy(dtype=np.int8)


def _ensure_is_split(df: pd.DataFrame, seed: int = 20260429) -> pd.DataFrame:
    """Ensure df has a valid is_split column with both calib (1) and test (2) rows.

    Resolution order:
      1. is_split present and non-degenerate (both split=1 and split=2 exist) → return as-is.
      2. is_split has boolean dtype (legacy True/False format) → remap to int8 {1, 2}.
      3. is_calib present → map 1→1 (conformal_calib), 0→2 (test); validate non-degenerate.
      4. Otherwise (no split info, or degenerate after steps 2/3) → apply a stratified
         50/50 random split so that calib and test are strictly disjoint, preventing
         data-leakage violations of the exchangeability assumption.
    """
    import warnings
    from sklearn.model_selection import train_test_split

    if "is_split" in df.columns:
        col = df["is_split"]
        # Handle boolean dtype (True → calib=1, False → test=2)
        if col.dtype == bool or str(col.dtype) == "bool":
            df = df.copy()
            df["is_split"] = col.map({True: 1, False: 2}).astype("int8")
            col = df["is_split"]
        has_calib = bool((col == 1).any())
        has_test = bool((col == 2).any())
        if has_calib and has_test:
            return df
        warnings.warn(
            f"is_split column is degenerate (has_calib={has_calib}, has_test={has_test}). "
            "Applying stratified 50/50 random split to prevent data-leakage.",
            UserWarning, stacklevel=2,
        )
        # Fall through to random split below.

    elif "is_calib" in df.columns:
        df = df.copy()
        df["is_split"] = df["is_calib"].map({1: 1, 0: 2}).astype("int8")
        has_calib = bool((df["is_split"] == 1).any())
        has_test = bool((df["is_split"] == 2).any())
        if has_calib and has_test:
            return df
        warnings.warn(
            f"is_calib mapping produced a degenerate split (has_calib={has_calib}, "
            f"has_test={has_test}). Applying stratified 50/50 random split.",
            UserWarning, stacklevel=2,
        )

    # Stratified 50/50 fallback: guarantees disjoint calib and test sets.
    df = df.copy()
    stratify = df["y_abstract"] if "y_abstract" in df.columns else None
    calib_idx, test_idx = train_test_split(
        df.index,
        test_size=0.5,
        stratify=stratify,
        random_state=seed,
    )
    df["is_split"] = np.int8(2)
    df.loc[calib_idx, "is_split"] = np.int8(1)
    return df


def compute_nmin(alpha: float, delta_ltt: float) -> int:
    """Minimum positive-stratum size for Theorem 5 validity.

    N_min = ceil(ln(1/delta_LTT) / (-ln(1-alpha)))
    """
    return math.ceil(math.log(1.0 / delta_ltt) / (-math.log(1.0 - alpha)))


def report_nmin_compliance(
    df: pd.DataFrame,
    topic_id: str,
    alpha: float = 0.10,
    delta_ltt: float = 0.07,
) -> dict:
    """Check and report N_min compliance for a topic.

    Returns a dict with keys:
      topic_id, N, m_plus_conformal, m_plus_test, prevalence_conformal,
      N_min, margin, status (PASS / ABSTAIN), alpha, delta_ltt
    """
    df = _ensure_is_split(df)
    nmin = compute_nmin(alpha, delta_ltt)

    conf_pos = df[(df.is_split == 1) & (df.y_abstract == 1)]
    test_pos = df[(df.is_split == 2) & (df.y_abstract == 1)]
    conf_all = df[df.is_split == 1]

    m_plus_conf = len(conf_pos)
    m_plus_test = len(test_pos)
    n_conf = len(conf_all)
    prevalence = m_plus_conf / n_conf if n_conf > 0 else 0.0

    status = "PASS" if m_plus_conf >= nmin else "ABSTAIN"

    return {
        "topic_id": topic_id,
        "N_total": len(df),
        "N_conformal": n_conf,
        "m_plus_conformal": m_plus_conf,
        "m_plus_test": m_plus_test,
        "prevalence_conformal": round(prevalence, 4),
        "N_min": nmin,
        "margin": m_plus_conf - nmin,
        "status": status,
        "alpha": alpha,
        "delta_ltt": delta_ltt,
    }


def build_nmin_compliance_table(
    topic_results: list[dict],
) -> pd.DataFrame:
    """Build a DataFrame suitable for paper Table 2.

    topic_results: list of dicts from report_nmin_compliance().
    """
    df = pd.DataFrame(topic_results)
    df = df.sort_values("topic_id")
    df["status_symbol"] = df["status"].map({"PASS": "✓", "ABSTAIN": "✗"})
    cols = [
        "topic_id", "N_conformal", "m_plus_conformal", "prevalence_conformal",
        "N_min", "margin", "status_symbol",
    ]
    return df[cols].rename(columns={
        "topic_id": "Topic",
        "N_conformal": "N (calib)",
        "m_plus_conformal": "m+",
        "prevalence_conformal": "π",
        "N_min": "N_min",
        "margin": "m+ - N_min",
        "status_symbol": "Status",
    })


def _to_latex_booktabs(table: pd.DataFrame) -> str:
    """Render compliance DataFrame as a booktabs LaTeX table."""
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{$N_{\min}$ compliance across all six topics "
        r"(Theorem~5, $\alpha=0.10$, $\delta_{\text{LTT}}=0.07$).}",
        r"\label{tab:nmin_compliance}",
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r"Topic & $N$ (calib) & $m^+$ & $\pi$ & $N_{\min}$"
        r" & $m^+ - N_{\min}$ & Status \\",
        r"\midrule",
    ]
    for _, row in table.iterrows():
        status_tex = r"\checkmark" if row["Status"] == "✓" else r"\texttimes"
        margin = int(row["m+ - N_min"])
        lines.append(
            f"{row['Topic']} & {int(row['N (calib)'])} & {int(row['m+'])} & "
            f"{float(row['π']):.3f} & {int(row['N_min'])} & "
            f"{margin:+d} & {status_tex} \\\\"
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(lines)


def _print_compliance_table(table: pd.DataFrame) -> None:
    """Print compliance table in pipe-delimited format to stdout."""
    display = table.copy()
    if "m+ - N_min" in display.columns:
        display["m+ - N_min"] = display["m+ - N_min"].apply(lambda x: f"{x:+d}")
    if "π" in display.columns:
        display["π"] = display["π"].apply(lambda x: f"{float(x):.3f}")

    cols = display.columns.tolist()
    widths = {
        c: max(len(str(c)), max(len(str(v)) for v in display[c]))
        for c in cols
    }

    def _row(vals: list) -> str:
        return "  | ".join(str(v).ljust(widths[c]) for c, v in zip(cols, vals))

    print(_row(cols))
    print("  | ".join("-" * widths[c] for c in cols))
    for _, row in display.iterrows():
        print(_row(list(row.values)))


def compute_routing_fractions(
    df_test: pd.DataFrame,
    theta_hat: tuple[float, float, float],
) -> dict[str, float]:
    """Compute cascade routing fractions on the full test corpus.

    Returns:
      frac_cheap_reject:  P(s < λ_lo)
      frac_auto_include:  P(s >= λ_hi)
      frac_llm_followed:  P(λ_lo <= s < λ_hi AND u >= τ_SE)
      frac_human_review:  P(λ_lo <= s < λ_hi AND u < τ_SE)
      frac_escalated:     frac_llm_followed + frac_human_review
      llm_abstention_rate: frac_human_review / frac_escalated (0 if frac_escalated=0)
    """
    lam_lo, lam_hi, tau_SE = theta_hat
    s = df_test["s"].values
    u = df_test["u"].values

    cheap_reject = s < lam_lo
    auto_include = s >= lam_hi
    escalated = (s >= lam_lo) & (s < lam_hi)
    llm_followed = escalated & (u >= tau_SE)
    human_review = escalated & (u < tau_SE)

    frac_escl = float(escalated.mean())
    return {
        "frac_cheap_reject": float(cheap_reject.mean()),
        "frac_auto_include": float(auto_include.mean()),
        "frac_llm_followed": float(llm_followed.mean()),
        "frac_human_review": float(human_review.mean()),
        "frac_escalated": frac_escl,
        "llm_abstention_rate": float(
            human_review.mean() / frac_escl if frac_escl > 0 else 0.0
        ),
    }


def compute_fnr(
    df_test: pd.DataFrame,
    theta_hat: tuple[float, float, float],
) -> float:
    """Empirical FNR on test positives under certified θ̂.

    FNR = FN / (TP + FN) — fraction of true positives missed by the cascade.
    A positive is missed when cheap-rejected, or when escalated and LLM-followed
    but the LLM was wrong (pessimistic: all LLM-followed positives when llm_y_hat absent).
    """
    lam_lo, lam_hi, tau_SE = theta_hat
    pos = df_test[df_test["y_abstract"] == 1].copy()
    if len(pos) == 0:
        return 0.0

    s = pos["s"].values
    u = pos["u"].values

    cheap_rejected = s < lam_lo
    escalated = (s >= lam_lo) & (s < lam_hi)
    llm_followed = escalated & (u >= tau_SE)

    if "llm_y_hat" in pos.columns:
        llm_miss = llm_followed & (pos["llm_y_hat"].values == 0)
    else:
        llm_miss = llm_followed

    missed = cheap_rejected | llm_miss
    return float(missed.mean())


def compute_wss(
    df_test: pd.DataFrame,
    theta_hat: tuple[float, float, float],
    recall_target: float = 0.95,
) -> float:
    """Workload Saved over Sampling at recall_target.

    WSS@r = (TN + FN) / N - (1 - r).
    Returns NaN if recall_target is not achieved.
    """
    lam_lo, lam_hi, tau_SE = theta_hat
    s = df_test["s"].values
    u = df_test["u"].values
    y = df_test["y_abstract"].values

    cheap_rejected = s < lam_lo
    escalated = (s >= lam_lo) & (s < lam_hi)
    llm_followed = escalated & (u >= tau_SE)

    if "llm_y_hat" in df_test.columns:
        llm_y = df_test["llm_y_hat"].values
        include = (s >= lam_hi) | (llm_followed & (llm_y == 1)) | (escalated & (u < tau_SE))
    else:
        include = ~cheap_rejected

    tp = (y == 1) & include
    fn = (y == 1) & ~include
    tn = (y == 0) & ~include

    n = len(df_test)
    n_pos = int(y.sum())
    recall = float(tp.sum() / n_pos) if n_pos > 0 else 0.0

    if recall < recall_target:
        return float("nan")

    return float((tn.sum() + fn.sum()) / n - (1.0 - recall_target))


def compute_slack_ratio(
    eta_lcb_star: float,
    eta_boot_upper: float,
) -> float:
    """Tightness diagnostic: η̂⁻⋆ / η̂⁺_boot.

    Values near 1.0 → WSR bound is tight relative to bootstrap.
    """
    if eta_boot_upper <= 0:
        return float("nan")
    return float(eta_lcb_star / eta_boot_upper)


def evaluate_certificate(
    df: pd.DataFrame,
    theta_hat: tuple[float, float, float],
    alpha: float,
    B: int = 5,
) -> dict:
    """Full evaluation of a certified θ̂ on the test split (is_split==2).

    Returns all required metrics for the paper's Table 3.
    """
    df = _ensure_is_split(df)
    df_test = df[df["is_split"] == 2].copy()

    routing = compute_routing_fractions(df_test, theta_hat)
    fnr = compute_fnr(df_test, theta_hat)
    wss = compute_wss(df_test, theta_hat, recall_target=0.95)
    n_pos_test = int((df_test["y_abstract"] == 1).sum())

    return {
        "fnr_test": fnr,
        "wss_95": wss if not math.isnan(wss) else -999.0,
        "recall_achieved": 1.0 - fnr,
        "alpha": alpha,
        "certificate_valid": bool(fnr <= alpha),
        "n_test": len(df_test),
        "n_test_positives": n_pos_test,
        "llm_calls_per_abstract": float(B * routing["frac_escalated"]),
        **routing,
    }


def aggregate_cross_topic(eval_results: list[dict]) -> dict:
    """Mean ± SE across topics for the paper's headline numbers."""
    metrics = ["fnr_test", "wss_95", "frac_human_review", "llm_abstention_rate"]
    out: dict = {}
    for m in metrics:
        vals = [r[m] for r in eval_results if r.get(m) is not None and r[m] != -999.0]
        if vals:
            out[f"{m}_mean"] = float(np.mean(vals))
            out[f"{m}_se"] = float(np.std(vals) / np.sqrt(len(vals)))
            out[f"{m}_n"] = len(vals)
    return out


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="CASCADE-RC per-topic evaluation metrics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", default=None,
                        help="Topic ID, e.g. CD008874 (omit when --nmin-table is set)")
    parser.add_argument(
        "--artefact-dir", type=Path, default=Path("artefacts/cascade_rc"),
        help="Root artefact directory (contains certificates/ and data/)",
    )
    parser.add_argument(
        "--calib-parquet", type=Path, default=None,
        help="Scored parquet (columns: pmid, s, u, y_abstract, llm_y_hat, is_calib). "
             "Default: <artefact-dir>/data/<topic>.parquet",
    )
    parser.add_argument(
        "--nmin-table", action="store_true",
        help="Generate N_min compliance table for all default topics and exit",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write LaTeX compliance table to this .tex file (use with --nmin-table)",
    )
    args = parser.parse_args()

    if args.nmin_table:
        artefact_dir: Path = args.artefact_dir
        results = []
        for topic_id in _DEFAULT_TOPICS:
            parquet_path = artefact_dir / "data" / f"{topic_id}.parquet"
            if not parquet_path.exists():
                print(f"WARNING: {parquet_path} not found — skipping {topic_id}",
                      file=sys.stderr)
                continue
            df_topic = pd.read_parquet(parquet_path)
            results.append(report_nmin_compliance(df_topic, topic_id))

        if not results:
            print("No topic parquets found. Run ingest first.", file=sys.stderr)
            sys.exit(1)

        table = build_nmin_compliance_table(results)
        _print_compliance_table(table)

        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(_to_latex_booktabs(table))
            print(f"\nLaTeX table written to {args.output}")
        return

    if not args.topic:
        parser.error("--topic is required unless --nmin-table is specified")

    import json
    from cascade_rc.certificates.store import CertificateStore
    from cascade_rc.config import CascadeRCConfig

    artefact_dir = args.artefact_dir
    calib_parquet: Path = (
        args.calib_parquet or artefact_dir / "data" / f"{args.topic}.parquet"
    )

    cfg = CascadeRCConfig()
    try:
        cert = CertificateStore.load(args.topic, artefact_dir)
    except FileNotFoundError:
        print(
            f"No certificate found for topic {args.topic!r} in {artefact_dir}. "
            "Run calibration first (or the topic may have abstained).",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_parquet(calib_parquet)
    df_test = df[df["is_calib"] == 0].reset_index(drop=True)

    routing_df = _derive_routing(df_test, cert.theta_hat)
    routing_dir = artefact_dir / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    routing_df[["pmid", "decision"]].to_parquet(
        routing_dir / f"{args.topic}.parquet", index=False
    )

    llm_vol = llm_query_volume(routing_df[["pmid", "decision"]])

    predictions = _predictions_from_routing(routing_df)
    y_true = df_test["y_abstract"].to_numpy(dtype=np.int8)
    wss_result = wss_at_recall(predictions, y_true, target_recall=0.95)

    eta_boot = bootstrap_eta_upper(
        cert.slack_mat, delta=cfg.ltt.delta_bootstrap, B=1000, seed=0
    )
    ratio = slack_ratio_diagnostic(cert.eta_lcb_grid, eta_boot)

    def _nan_to_null(obj: object) -> object:
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, dict):
            return {k: _nan_to_null(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_nan_to_null(v) for v in obj]
        return obj

    output = {
        "topic": args.topic,
        "status": cert.status,
        "wss95": wss_result,
        "llm_volume": llm_vol,
        "slack_ratio_mean": float(np.nanmean(ratio)),
        "slack_ratio_std": float(np.nanstd(ratio)),
    }
    print(json.dumps(_nan_to_null(output)))

    parser = argparse.ArgumentParser(
        description="CASCADE-RC per-topic evaluation metrics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", required=True, help="Topic ID, e.g. CD008874")
    parser.add_argument(
        "--artefact-dir", type=Path, default=Path("artefacts/cascade_rc"),
        help="Root artefact directory (contains certificates/ and data/)",
    )
    parser.add_argument(
        "--calib-parquet", type=Path, default=None,
        help="Scored parquet (columns: pmid, s, u, y_abstract, llm_y_hat, is_calib). "
             "Default: <artefact-dir>/data/<topic>.parquet",
    )
    args = parser.parse_args()

    artefact_dir: Path = args.artefact_dir
    calib_parquet: Path = (
        args.calib_parquet or artefact_dir / "data" / f"{args.topic}.parquet"
    )

    cfg = CascadeRCConfig()
    try:
        cert = CertificateStore.load(args.topic, artefact_dir)
    except FileNotFoundError:
        import sys
        print(
            f"No certificate found for topic {args.topic!r} in {artefact_dir}. "
            "Run calibration first (or the topic may have abstained).",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_parquet(calib_parquet)
    df_test = df[df["is_calib"] == 0].reset_index(drop=True)

    routing_df = _derive_routing(df_test, cert.theta_hat)
    routing_dir = artefact_dir / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    routing_df[["pmid", "decision"]].to_parquet(
        routing_dir / f"{args.topic}.parquet", index=False
    )

    llm_vol = llm_query_volume(routing_df[["pmid", "decision"]])

    predictions = _predictions_from_routing(routing_df)
    y_true = df_test["y_abstract"].to_numpy(dtype=np.int8)
    wss_result = wss_at_recall(predictions, y_true, target_recall=0.95)

    eta_boot = bootstrap_eta_upper(
        cert.slack_mat, delta=cfg.ltt.delta_bootstrap, B=1000, seed=0
    )
    ratio = slack_ratio_diagnostic(cert.eta_lcb_grid, eta_boot)

    import math

    def _nan_to_null(obj: object) -> object:
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, dict):
            return {k: _nan_to_null(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_nan_to_null(v) for v in obj]
        return obj

    output = {
        "topic": args.topic,
        "status": cert.status,
        "wss95": wss_result,
        "llm_volume": llm_vol,
        "slack_ratio_mean": float(np.nanmean(ratio)),
        "slack_ratio_std": float(np.nanstd(ratio)),
    }
    print(json.dumps(_nan_to_null(output)))


if __name__ == "__main__":
    main()
