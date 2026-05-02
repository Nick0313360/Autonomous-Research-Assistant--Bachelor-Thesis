from __future__ import annotations

import math

import pytest

from cascade_rc.config import LTTBudget


@pytest.mark.parametrize("delta_eta,delta_ltt", [
    (0.01, 0.09),
    (0.03, 0.07),
    (0.05, 0.05),
    (0.07, 0.03),
    (0.09, 0.01),
])
def test_ltt_budget_ablation_pairs_are_valid(delta_eta: float, delta_ltt: float) -> None:
    """All 5 (δ_η, δ_LTT) ablation pairs must construct LTTBudget without error."""
    ltt = LTTBudget(
        alpha=0.10,
        delta_total=0.10,
        delta_eta=delta_eta,
        delta_LTT=delta_ltt,
        K=20,
    )
    assert math.isclose(ltt.delta_eta + ltt.delta_LTT, ltt.delta_total, abs_tol=1e-9)


def test_ltt_budget_validator_rejects_invalid_split() -> None:
    """Validator must raise ValueError when delta_eta + delta_LTT != delta_total."""
    with pytest.raises(ValueError, match="delta_eta"):
        LTTBudget(delta_eta=0.05, delta_LTT=0.05, delta_total=0.20)
