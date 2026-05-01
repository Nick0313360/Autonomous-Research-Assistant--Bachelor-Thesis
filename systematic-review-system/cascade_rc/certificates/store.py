"""Persistence layer for CASCADE-RC certification results."""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class CertificationResult:
    topic: str
    status: str                        # "certified" | "abstained"
    abstain_reason: str | None
    m_plus: int
    theta_hat: np.ndarray              # (3,) optimal θ̂ = (λ_lo, λ_hi, τ_SE)
    lambda_hat_mask: np.ndarray        # (G,) bool; True = certified
    theta_grid: np.ndarray             # (G, 3)
    eta_lcb_grid: np.ndarray           # (G,) η̂⁻⋆
    r_hat_grid: np.ndarray             # (G,) R̂
    p_hb_grid: np.ndarray             # (G,) p_HB
    alpha_dagger_grid: np.ndarray      # (G,) α†
    slack_mat: np.ndarray              # (G, m_plus) — pkl only, excluded from JSON
    config_snapshot: dict
    timestamp: str                     # ISO-8601


class CertificateStore:
    @staticmethod
    def _cert_dir(artefact_dir: Path) -> Path:
        d = artefact_dir / "certificates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _pkl_path(cls, topic: str, artefact_dir: Path) -> Path:
        return cls._cert_dir(artefact_dir) / f"{topic}.pkl"

    @classmethod
    def _json_path(cls, topic: str, artefact_dir: Path) -> Path:
        return cls._cert_dir(artefact_dir) / f"{topic}.json"

    @classmethod
    def _partial_path(cls, topic: str, artefact_dir: Path) -> Path:
        return cls._cert_dir(artefact_dir) / f"{topic}.partial.pkl"

    @classmethod
    def save(
        cls, topic: str, result: CertificationResult, artefact_dir: Path
    ) -> tuple[Path, Path]:
        pkl_path = cls._pkl_path(topic, artefact_dir)
        json_path = cls._json_path(topic, artefact_dir)

        with open(pkl_path, "wb") as f:
            pickle.dump(result, f)

        summary = {
            "topic": result.topic,
            "status": result.status,
            "abstain_reason": result.abstain_reason,
            "m_plus": result.m_plus,
            "timestamp": result.timestamp,
            "n_certified": int(result.lambda_hat_mask.sum()),
            "theta_hat": result.theta_hat.tolist() if result.theta_hat is not None else None,
            "config_snapshot": result.config_snapshot,
        }
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        return pkl_path, json_path

    @classmethod
    def load(cls, topic: str, artefact_dir: Path) -> CertificationResult:
        with open(cls._pkl_path(topic, artefact_dir), "rb") as f:
            return pickle.load(f)

    @classmethod
    def save_partial(cls, topic: str, state: dict, artefact_dir: Path) -> Path:
        partial_path = cls._partial_path(topic, artefact_dir)
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        with open(partial_path, "wb") as f:
            pickle.dump(state, f)
        return partial_path

    @classmethod
    def load_partial(cls, topic: str, artefact_dir: Path) -> dict | None:
        partial_path = cls._partial_path(topic, artefact_dir)
        if not partial_path.exists():
            return None
        with open(partial_path, "rb") as f:
            return pickle.load(f)

    @classmethod
    def delete_partial(cls, topic: str, artefact_dir: Path) -> None:
        partial_path = cls._partial_path(topic, artefact_dir)
        if partial_path.exists():
            partial_path.unlink()
