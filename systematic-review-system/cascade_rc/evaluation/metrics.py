"""Evaluation metrics for CASCADE-RC systematic review screening."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


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


def main() -> None:
    import argparse
    import json
    import sys

    from cascade_rc.certificates.store import CertificateStore
    from cascade_rc.config import CascadeRCConfig

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
