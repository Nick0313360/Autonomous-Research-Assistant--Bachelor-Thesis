"""Assertion helpers for CASCADE-RC tests."""

import numpy as np
import pandas as pd


def assert_fnr_controlled(
    df_test: pd.DataFrame,
    theta_hat: tuple[float, float, float],
    alpha: float,
    tolerance: float = 0.0,
    msg: str = "",
) -> float:
    """
    Assert that FNR ≤ alpha + tolerance on df_test under theta_hat.
    Returns the empirical FNR for logging.
    """
    from cascade_rc.evaluation.metrics import compute_fnr
    fnr = compute_fnr(df_test, theta_hat)
    assert fnr <= alpha + tolerance, (
        f"Theorem 5 VIOLATED: FNR={fnr:.4f} > alpha={alpha:.4f}{' ' + msg if msg else ''}.\n"
        f"theta_hat={theta_hat}, n_test_pos={df_test['y_abstract'].sum()}"
    )
    return fnr


def assert_tau_SE_nonzero(theta_hat: tuple[float, float, float], topic_id: str = "") -> None:
    """Assert τ_SE is non-zero (confirms τ_SE traversal bug is fixed)."""
    tau_SE = theta_hat[2]
    assert tau_SE > 0.0, (
        f"τ_SE = 0.0 in theta_hat — τ_SE traversal bug NOT fixed."
        f"{' Topic: ' + topic_id if topic_id else ''}\n"
        f"theta_hat={theta_hat}\n"
        f"The walker is still sorting τ_SE ASC (wrong direction)."
    )


def assert_certificate_nonempty(lambda_hat_size: int, topic_id: str = "") -> None:
    """Assert |Λ̂| > 0 (non-degenerate certificate)."""
    assert lambda_hat_size > 0, (
        f"|Lambda_hat| = 0 — degenerate certificate."
        f"{' Topic: ' + topic_id if topic_id else ''}\n"
        "The walk halted immediately. Check: τ_SE direction, N_min compliance, α setting."
    )


def assert_routing_sums_to_one(routing: dict, tol: float = 1e-6) -> None:
    """Assert routing fractions sum to 1.0."""
    total = (
        routing["frac_cheap_reject"]
        + routing["frac_auto_include"]
        + routing["frac_llm_followed"]
        + routing["frac_human_review"]
    )
    assert abs(total - 1.0) < tol, (
        f"Routing fractions sum to {total:.6f} ≠ 1.0\n"
        f"  cheap_reject={routing['frac_cheap_reject']:.4f}\n"
        f"  auto_include={routing['frac_auto_include']:.4f}\n"
        f"  llm_followed={routing['frac_llm_followed']:.4f}\n"
        f"  human_review={routing['frac_human_review']:.4f}"
    )
