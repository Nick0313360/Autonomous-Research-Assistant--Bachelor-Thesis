"""Algorithm 1 orchestrator for CASCADE-RC calibration (paper §5.4).

Entry point:
    python -m cascade_rc.calibration.main_calibrate --topic CD008874 --calib-parquet path/to/file.parquet
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from cascade_rc.certificates.store import CertificationResult, CertificateStore
from cascade_rc.config import CascadeRCConfig


def _compute_n_min(alpha: float, delta_ltt: float) -> int:
    """N_min = ceil(ln(1/δ_LTT) / (-ln(1-α))) — minimum calibration positives required."""
    return math.ceil(math.log(1.0 / delta_ltt) / (-math.log(1.0 - alpha)))


def calibrate(
    topic_id: str,
    calib_parquet: Path,
    config: CascadeRCConfig,
    artefact_dir: Path | None = None,
    chunk_size: int = 500,
) -> "CertificationResult | tuple[None, None, str]":
    """Run Algorithm 1: certify operating point θ̂ for topic_id.

    Args:
        topic_id:       Topic identifier used for artefact naming.
        calib_parquet:  Parquet with columns: pmid, s, u, y_abstract, llm_y_hat, is_calib.
        config:         CascadeRCConfig with LTT budget and artefact paths.
        artefact_dir:   Override for config.artefact_dir.
        chunk_size:     Number of grid points per WSR checkpoint batch.

    Returns:
        CertificationResult on success, or (None, None, reason_str) on abstention.
    """
    if artefact_dir is None:
        artefact_dir = config.artefact_dir

    ltt = config.ltt
    alpha = ltt.alpha
    delta_eta = ltt.delta_eta
    delta_ltt = ltt.delta_LTT
    K = ltt.K
    c_human = ltt.c_human
    c_llm = ltt.c_llm

    # Step 1: Filter calibration positives
    df = pd.read_parquet(calib_parquet)
    df_pos = df[(df["is_calib"] == 1) & (df["y_abstract"] == 1)]
    m_plus = len(df_pos)

    # Step 2: Abstention check
    N_min = _compute_n_min(alpha, delta_ltt)
    if m_plus < N_min:
        return (None, None, f"abstained:m_plus={m_plus}<{N_min}")

    # Deferred imports — only needed for the full calibration path (Task 5)
    from cascade_rc.calibration.hb_pvalue import hb_pvalues  # noqa: F401
    from cascade_rc.calibration.surrogate_loss import grid as _theta_grid, loss_tensor, slack_tensor  # noqa: F401
    from cascade_rc.calibration.walker import safest_to_riskiest_order, walk_reject  # noqa: F401
    from cascade_rc.calibration.wsr_lcb import wsr_lcb_one_sided  # noqa: F401

    raise NotImplementedError("Full calibration not yet implemented — Task 5")
