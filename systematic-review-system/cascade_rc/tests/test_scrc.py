"""Tests for cascade_rc.baselines.scrc — SCRC-I and SCRC-T baselines."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_synthetic(
    n: int,
    pi: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (s, u, y): relevance scores, utility scores, labels.

    Positives: s ~ Beta(8, 2); negatives: s ~ Beta(2, 8).
    u ~ Beta(5, 5) independent of label.
    """
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < pi).astype(np.int64)
    s = np.where(y == 1, rng.beta(8, 2, size=n), rng.beta(2, 8, size=n))
    u = rng.beta(5, 5, size=n)
    return s, u, y


# ---------------------------------------------------------------------------
# Category A — Unit correctness: _crc_threshold
# ---------------------------------------------------------------------------

def test_crc_threshold_pin() -> None:
    """Pin the conformal quantile formula against two known values.

    pos_scores = [0.1, 0.2, ..., 1.0], n_pos = 10.

    Correct formula: k = floor(alpha*(n_pos+1)) - 1; FNR = (k+1)/(n_pos+1).
    P(s_test < pos_scores[k]) = (k+1)/(n_pos+1) by exchangeability, so we need
    k = floor(alpha*(n_pos+1)) - 1 to achieve FNR <= alpha.

    alpha=0.10: floor(0.10*11) - 1 = 0  → pos_scores[0] = 0.1; FNR = 1/11 ≈ 0.091 ≤ 0.10
    alpha=0.05: floor(0.05*11) - 1 = -1 → k < 0, return 0.0 (accept all, FNR = 0)
    """
    from cascade_rc.baselines.scrc import _crc_threshold

    pos_scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    assert _crc_threshold(pos_scores, alpha=0.10) == pytest.approx(0.1)
    assert _crc_threshold(pos_scores, alpha=0.05) == pytest.approx(0.0)


def test_crc_threshold_no_positives() -> None:
    """Empty pos_scores → returns 0.0 (accept everything)."""
    from cascade_rc.baselines.scrc import _crc_threshold

    assert _crc_threshold(np.array([]), alpha=0.10) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Category A — Unit correctness: SCRC class interface
# ---------------------------------------------------------------------------

def test_predict_before_fit_raises() -> None:
    """predict() raises RuntimeError on an unfitted SCRC instance."""
    from cascade_rc.baselines.scrc import SCRC

    scrc = SCRC(variant="I", alpha=0.10)
    with pytest.raises(RuntimeError, match="fit"):
        scrc.predict(np.array([0.5]), np.array([0.5]))


def test_predict_schema() -> None:
    """predict() returns object array with values only in {'accept','abstain'}."""
    from cascade_rc.baselines.scrc import SCRC

    rng = np.random.default_rng(42)
    n = 50
    s = rng.random(n)
    u = rng.random(n)
    y = (rng.random(n) < 0.2).astype(np.int64)

    for variant in ("I", "T"):
        scrc = SCRC(variant=variant, alpha=0.10)
        scrc.fit(s, u, y)
        decisions = scrc.predict(s, u)
        assert decisions.dtype == object, f"variant={variant}: dtype should be object"
        assert decisions.shape == (n,), f"variant={variant}: wrong shape"
        assert set(decisions).issubset({"accept", "abstain"}), (
            f"variant={variant}: unexpected values {set(decisions)}"
        )


# ---------------------------------------------------------------------------
# Category B — Algorithm correctness
# ---------------------------------------------------------------------------

def test_scrc_i_internal_split_pins_tau() -> None:
    """SCRC-I tau_ equals np.quantile(u_C1, abstain_rate) for the known-seed split.

    Also verifies stratified split: n_pos_used_ < total positives in cal
    (C2 has strictly fewer positives than the full calibration set).
    """
    from cascade_rc.baselines.scrc import SCRC

    s_cal, u_cal, y_cal = _make_synthetic(n=300, pi=0.10, seed=0)
    n_pos_full = int((y_cal == 1).sum())

    scrc = SCRC(variant="I", alpha=0.10, abstain_rate=0.1, split_ratio=0.5, seed=0)
    scrc.fit(s_cal, u_cal, y_cal)

    # Recompute C1 indices identically to the implementation
    rng = np.random.default_rng(0)
    pos_idx = np.where(y_cal == 1)[0]
    neg_idx = np.where(y_cal == 0)[0]
    rng.shuffle(pos_idx)
    rng.shuffle(neg_idx)
    n_pos_c1 = int(math.floor(len(pos_idx) * 0.5))
    n_neg_c1 = int(math.floor(len(neg_idx) * 0.5))
    c1_idx = np.concatenate([pos_idx[:n_pos_c1], neg_idx[:n_neg_c1]])

    expected_tau = float(np.quantile(u_cal[c1_idx], 0.1))
    assert scrc.tau_ == pytest.approx(expected_tau, rel=1e-9)
    assert scrc.n_pos_used_ < n_pos_full, (
        f"SCRC-I should use fewer positives than full cal: "
        f"n_pos_used_={scrc.n_pos_used_} vs full={n_pos_full}"
    )


def test_scrc_t_uses_more_positives_than_scrc_i() -> None:
    """SCRC-T n_pos_used_ > SCRC-I n_pos_used_ on the same calibration set.

    SCRC-T uses the full cal; SCRC-I uses only the C2 half.
    """
    from cascade_rc.baselines.scrc import SCRC

    s_cal, u_cal, y_cal = _make_synthetic(n=300, pi=0.10, seed=1)

    scrc_t = SCRC(variant="T", alpha=0.10, abstain_rate=0.1).fit(s_cal, u_cal, y_cal)
    scrc_i = SCRC(variant="I", alpha=0.10, abstain_rate=0.1, split_ratio=0.5, seed=0).fit(s_cal, u_cal, y_cal)

    assert scrc_t.n_pos_used_ > scrc_i.n_pos_used_, (
        f"SCRC-T n_pos_used_={scrc_t.n_pos_used_} should exceed "
        f"SCRC-I n_pos_used_={scrc_i.n_pos_used_}"
    )


# ---------------------------------------------------------------------------
# Category C — Coverage simulation (1 000 trials)
# ---------------------------------------------------------------------------

def _run_coverage_trial(
    variant: str,
    alpha: float,
    abstain_rate: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Single trial: generate data, fit SCRC, return (recall, accept_rate).

    CRC/SCRC provides an *expected* risk control guarantee (E[FNR] <= alpha),
    not a per-trial high-probability guarantee. With ~18 selected positives per
    trial the per-trial recall is Binomial-noisy around 0.90, so P(recall >=
    0.90 in one trial) ≈ 0.45 — the test correctly checks the mean over 1 000
    trials rather than a per-trial binary.

    Denominator uses selected positives (u >= tau_) because SCRC's conformal
    guarantee is conditional: P(FNR | selected) <= alpha. When u is independent
    of y, total recall = (1-abstain_rate)*(1-alpha) < 1-alpha, making total
    recall >= 1-alpha impossible.
    """
    from cascade_rc.baselines.scrc import SCRC

    n_cal, n_test, pi = 300, 200, 0.10
    seed = int(rng.integers(0, 2**31))

    s_all, u_all, y_all = _make_synthetic(n=n_cal + n_test, pi=pi, seed=seed)
    s_cal, u_cal, y_cal = s_all[:n_cal], u_all[:n_cal], y_all[:n_cal]
    s_test, u_test, y_test = s_all[n_cal:], u_all[n_cal:], y_all[n_cal:]

    scrc = SCRC(variant=variant, alpha=alpha, abstain_rate=abstain_rate)
    scrc.fit(s_cal, u_cal, y_cal)
    decisions = scrc.predict(s_test, u_test)

    accepted = decisions == "accept"
    n_pos_selected = int(((u_test >= scrc.tau_) & (y_test == 1)).sum())
    recall = float((accepted & (y_test == 1)).sum()) / max(1, n_pos_selected)
    accept_rate = float(accepted.mean())
    return recall, accept_rate


@pytest.mark.parametrize("variant", ["I", "T"])
def test_scrc_marginal_coverage_1000(variant: str) -> None:
    """SCRC achieves expected conditional recall >= 1 - alpha over 1 000 trials.

    CRC/SCRC guarantees E[FNR(selected)] <= alpha (expected risk control), not
    P(FNR(selected) <= alpha) >= 1-alpha (per-trial probability). With ~18
    selected positives per trial P(recall >= 0.90 in a single trial) ≈ 0.45
    regardless of n_trials — the correct check is mean recall over many trials.

    Tolerance: 0.02 below 1-alpha gives comfortable margin above Monte Carlo
    noise at n_trials=1000 (SE ≈ 0.003).

    Synthetic data: n_cal=300, n_test=200, pi=0.10, positives Beta(8,2),
    negatives Beta(2,8), u ~ Beta(5,5) independent.
    """
    alpha = 0.10
    abstain_rate = 0.10
    n_trials = 1_000
    rng = np.random.default_rng(42)

    recall_list = []
    accept_rates = []
    for _ in range(n_trials):
        recall, accept_rate = _run_coverage_trial(variant, alpha, abstain_rate, rng)
        recall_list.append(recall)
        accept_rates.append(accept_rate)

    mean_recall = float(np.mean(recall_list))
    mean_accept_rate = float(np.mean(accept_rates))

    # Sanity: not degenerate (not all accept, not all abstain)
    assert 0.05 < mean_accept_rate < 0.95, (
        f"variant={variant}: degenerate accept rate {mean_accept_rate:.3f} "
        "(expected 0.05 < rate < 0.95)"
    )

    assert mean_recall >= 1.0 - alpha - 0.02, (
        f"variant={variant}: mean conditional recall {mean_recall:.4f} < "
        f"{1.0 - alpha - 0.02:.4f} (1 - alpha - 0.02 = {1.0 - alpha - 0.02:.4f})"
    )


# ---------------------------------------------------------------------------
# Category D — Driver (run_sweep)
# ---------------------------------------------------------------------------

def test_dry_run_zero_rows_correct_schema(tmp_path: Path) -> None:
    from cascade_rc.baselines.scrc import run_sweep

    df = run_sweep(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        dry_run=True,
    )
    _SCHEMA = {
        "method":          "object",
        "topic_id":        "object",
        "target_recall":   "float64",
        "examined":        "int64",
        "recall_achieved": "float64",
        "wss_95":          "float64",
        "wss_status":      "object",
        "peak_rss_kb":     "float64",
    }
    assert len(df) == 0
    for col, dtype in _SCHEMA.items():
        assert col in df.columns, f"Missing column: {col}"
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_dry_run_parquet_written(tmp_path: Path) -> None:
    from cascade_rc.baselines.scrc import run_sweep

    out_dir = tmp_path / "out"
    run_sweep(data_dir=tmp_path / "data", out_dir=out_dir, dry_run=True)
    assert (out_dir / "scrc_results.parquet").exists()


def test_no_parquets_raises(tmp_path: Path) -> None:
    from cascade_rc.baselines.scrc import run_sweep

    with pytest.raises(FileNotFoundError):
        run_sweep(data_dir=tmp_path / "empty", out_dir=tmp_path / "out")
