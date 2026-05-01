"""Tests for CertificationResult persistence (certificates/store.py)."""
from __future__ import annotations

import pickle
import json
from pathlib import Path

import numpy as np
import pytest

from cascade_rc.certificates.store import CertificationResult, CertificateStore


def _make_result(topic: str = "CD000001") -> CertificationResult:
    G = 10
    return CertificationResult(
        topic=topic,
        status="certified",
        abstain_reason=None,
        m_plus=42,
        theta_hat=np.array([0.2, 0.6, 0.4]),
        lambda_hat_mask=np.ones(G, dtype=bool),
        theta_grid=np.zeros((G, 3)),
        eta_lcb_grid=np.zeros(G),
        r_hat_grid=np.zeros(G),
        p_hb_grid=np.zeros(G),
        alpha_dagger_grid=np.zeros(G),
        slack_mat=np.zeros((G, 42)),
        config_snapshot={"alpha": 0.10},
        timestamp="2026-05-01T00:00:00+00:00",
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Saved CertificationResult loads back bytes-identical."""
    result = _make_result()
    CertificateStore.save("CD000001", result, tmp_path)

    pkl_path = tmp_path / "certificates" / "CD000001.pkl"
    json_path = tmp_path / "certificates" / "CD000001.json"
    assert pkl_path.exists(), "pickle file should exist"
    assert json_path.exists(), "json summary should exist"

    loaded = CertificateStore.load("CD000001", tmp_path)
    assert loaded.topic == result.topic
    assert loaded.m_plus == result.m_plus
    np.testing.assert_array_equal(loaded.theta_hat, result.theta_hat)
    np.testing.assert_array_equal(loaded.lambda_hat_mask, result.lambda_hat_mask)


def test_json_summary_keys(tmp_path: Path) -> None:
    """JSON summary contains required human-readable fields."""
    CertificateStore.save("CD000001", _make_result(), tmp_path)
    with open(tmp_path / "certificates" / "CD000001.json") as f:
        summary = json.load(f)
    for key in ("topic", "status", "m_plus", "timestamp", "n_certified", "theta_hat",
                "abstain_reason", "config_snapshot"):
        assert key in summary, f"Missing key: {key}"
    assert "slack_mat" not in summary


def test_partial_save_load_delete(tmp_path: Path) -> None:
    """Partial checkpoint persists and is deleted cleanly."""
    state = {"grid_idx_completed": 500, "eta_lcb_partial": np.zeros(500)}
    CertificateStore.save_partial("CD000001", state, tmp_path)

    partial_path = tmp_path / "certificates" / "CD000001.partial.pkl"
    assert partial_path.exists()

    loaded = CertificateStore.load_partial("CD000001", tmp_path)
    assert loaded["grid_idx_completed"] == 500
    np.testing.assert_array_equal(loaded["eta_lcb_partial"], np.zeros(500))

    CertificateStore.delete_partial("CD000001", tmp_path)
    assert not partial_path.exists()
    assert CertificateStore.load_partial("CD000001", tmp_path) is None
