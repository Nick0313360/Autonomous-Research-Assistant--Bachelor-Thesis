from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

import pickle

from cascade_rc.evaluation.metrics import _derive_routing
from tier2_screening.abstract_screener import _TEMPLATE

logger = logging.getLogger(__name__)


class CascadeRCRouter:
    def __init__(
        self,
        cert_path: Path,
        topic_parquet_path: Path,
    ) -> None:
        # STEP 1 — Load certificate directly from .pkl path
        with open(cert_path, "rb") as _f:
            cert = pickle.load(_f)
        if cert.status == "abstained":
            raise RuntimeError(
                f"Topic {cert.topic} abstained: {cert.abstain_reason}"
            )
        self.theta_hat: np.ndarray = cert.theta_hat
        self.lambda_lo: float = float(cert.theta_hat[0])
        self.lambda_hi: float = float(cert.theta_hat[1])
        self.tau_se: float = float(cert.theta_hat[2])

        # STEP 2 — SHA check on _TEMPLATE
        current_sha = hashlib.sha256(_TEMPLATE.encode()).hexdigest()
        stored_sha = cert.config_snapshot.get("template_sha", None)
        if stored_sha and current_sha != stored_sha:
            raise RuntimeError(
                f"Template SHA mismatch. Stored={stored_sha[:8]} "
                f"Current={current_sha[:8]}. Re-run cascade_rc step_score_u."
            )
        if not stored_sha:
            logger.warning(
                "CascadeRCRouter: no template_sha in config_snapshot, "
                "skipping SHA check"
            )

        # STEP 3 — Load s and u from parquet
        df = pd.read_parquet(topic_parquet_path)
        self._su_lookup: dict[str, tuple[float, float]] = {
            str(row["pmid"]): (float(row["s"]), float(row["u"]))
            for _, row in df.iterrows()
        }

    async def route(self, pmid: str) -> dict:
        s, u = self._su_lookup.get(str(pmid), (0.0, 0.0))

        row_df = pd.DataFrame([{"s": s, "u": u}])
        result_df = _derive_routing(row_df, self.theta_hat)
        route = result_df["decision"].iloc[0]

        if route == "auto_reject":
            decision = "EXCLUDE"
        else:
            decision = "INCLUDE"

        return {"pmid": pmid, "s": s, "u": u, "route": route, "decision": decision}

    async def route_batch(self, pmids: list[str]) -> list[dict]:
        return [await self.route(pmid) for pmid in pmids]
