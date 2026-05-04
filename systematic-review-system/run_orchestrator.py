"""
run_orchestrator.py — State-driven end-to-end CASCADE-RC evaluation pipeline.

Executes six phases for a single topic, skipping any phase whose checkpoint
file already exists on disk.  Re-run freely; the pipeline is fully idempotent.

Usage
-----
    python run_orchestrator.py --topic CD008874
    python run_orchestrator.py --topic CD008874 --artefact-dir artefacts/cascade_rc

Phase sequence
--------------
  1a  AUTOSTOP baseline
  1b  RLStop baseline
  2   Merge LLM ensemble → step2/{topic}.parquet  (in-process)
  3   SCRC-I / SCRC-T baselines
  4   LTT calibration  (halts pipeline gracefully on abstention)
  5   Evaluation metrics → cascade_rc_results.parquet
  6   Publication figures  (PYTHONHASHSEED=0)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# _majority_and_u: verified return type tuple[Vote, float, int]
# (cascade_rc/cache/llm_ensemble.py line 80 + return paths at lines 103, 107)
from cascade_rc.cache.llm_ensemble import _majority_and_u

logger = logging.getLogger(__name__)

# Columns that step2/{topic}.parquet must contain before Phase 3/4 may run
_STEP2_REQUIRED: frozenset[str] = frozenset({
    "pmid", "title", "abstract", "y_abstract", "is_calib",
    "s", "u", "llm_y_hat",
})


class CascadeOrchestrator:
    """State-driven pipeline orchestrator for CASCADE-RC evaluation."""

    def __init__(
        self,
        topic: str,
        artefact_dir: Path,
        data_dir: Path,
        out_dir: Path,
        db_path: Path,
        model_id: str = "gpt-oss:120b",
        template_v: str = "v1",
    ) -> None:
        self.topic = topic
        self.artefact_dir = artefact_dir
        self.data_dir = data_dir
        self.out_dir = out_dir
        self.db_path = db_path
        self.model_id = model_id
        self.template_v = template_v

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def _run(
        self,
        cmd: list[str],
        label: str,
        env: dict[str, str] | None = None,
    ) -> None:
        """Run a subprocess command, stream its output to the logger, raise on failure."""
        import subprocess

        logger.info("→ %s", label)
        result = subprocess.run(
            cmd,
            env=env,
            text=True,
            capture_output=True,
        )
        for line in result.stdout.splitlines():
            logger.debug("[stdout] %s", line)
        for line in result.stderr.splitlines():
            logger.warning("[stderr] %s", line)
        if result.returncode != 0:
            raise RuntimeError(
                f"{label} failed (exit {result.returncode})\n"
                f"stderr tail:\n{result.stderr[-800:]}"
            )
        logger.info("✓ %s complete", label)

    def _skip_if_exists(self, path: Path, label: str) -> bool:
        """Return True and log a SKIP message if the checkpoint file exists."""
        if path.exists():
            logger.info("SKIP %s — checkpoint exists: %s", label, path)
            return True
        return False

    # ------------------------------------------------------------------
    # Phase 1 — Independent baselines (AUTOSTOP + RLStop)
    # ------------------------------------------------------------------

    def phase1_independent_baselines(self) -> None:
        # 1a: AUTOSTOP
        ckpt_autostop = self.out_dir / "autostop" / "autostop_results.parquet"
        if not self._skip_if_exists(ckpt_autostop, "Phase 1a: AUTOSTOP"):
            self._run(
                [
                    sys.executable, "-m", "cascade_rc.baselines.run_autostop",
                    "--data-dir", str(self.data_dir),
                    "--out-dir",  str(self.out_dir / "autostop"),
                    "--topics",   self.topic,
                ],
                label="Phase 1a: AUTOSTOP",
            )

        # 1b: RLStop
        ckpt_rlstop = self.out_dir / "rlstop" / "rlstop_results.parquet"
        if not self._skip_if_exists(ckpt_rlstop, "Phase 1b: RLStop"):
            self._run(
                [
                    sys.executable, "-m", "cascade_rc.baselines.run_rlstop",
                    "--data-dir",  str(self.data_dir),
                    "--out-dir",   str(self.out_dir / "rlstop"),
                    "--train-dir", str(self.out_dir / "rlstop"),
                    "--topics",    self.topic,
                ],
                label="Phase 1b: RLStop",
            )

    # ------------------------------------------------------------------
    # Phase 2 — Merge LLM ensemble scores into step2 parquet (in-process)
    # ------------------------------------------------------------------

    def phase2_merge_llm_u(self) -> None:
        step2_path = self.data_dir / "step2" / f"{self.topic}.parquet"
        if self._skip_if_exists(step2_path, "Phase 2: LLM merge"):
            return

        logger.info("Phase 2: Loading source parquet %s", self.data_dir / f"{self.topic}.parquet")
        df = pd.read_parquet(self.data_dir / f"{self.topic}.parquet")

        logger.info("Phase 2: Querying SQLite cache %s (model=%s template=%s)",
                    self.db_path, self.model_id, self.template_v)
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            """
            SELECT pmid, vote_label
            FROM   llm_calls
            WHERE  model_id  = ?
               AND template_v = ?
            ORDER BY pmid, seed_b
            """,
            (self.model_id, self.template_v),
        ).fetchall()
        conn.close()
        logger.info("Phase 2: %d vote rows fetched from cache", len(rows))

        # Group votes by PMID (preserving seed_b order, already sorted above)
        votes_by_pmid: dict[str, list[str]] = {}
        for pmid_val, vote_label in rows:
            votes_by_pmid.setdefault(str(pmid_val), []).append(vote_label)

        u_vals: list[float] = []
        y_hat_vals: list[int] = []
        missing_pmids: list[str] = []

        for pmid_val in df["pmid"].astype(str):
            votes = votes_by_pmid.get(pmid_val, [])
            if not votes:
                missing_pmids.append(pmid_val)
                u_vals.append(0.0)
                y_hat_vals.append(0)
            else:
                # _majority_and_u verified to return (Vote, float, int)
                # Vote is discarded; u ∈ [0,1]; y_hat ∈ {0,1}
                _, u_val, y_hat_val = _majority_and_u(votes, n=len(votes))
                u_vals.append(float(u_val))
                y_hat_vals.append(int(y_hat_val))

        if missing_pmids:
            logger.warning(
                "Phase 2: %d/%d PMIDs have no LLM cache entries — "
                "assigned u=0.0, llm_y_hat=0  (first 5: %s)",
                len(missing_pmids), len(df), missing_pmids[:5],
            )

        df["u"] = pd.array(u_vals, dtype="float64")
        df["llm_y_hat"] = pd.array(y_hat_vals, dtype="int8")

        step2_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(step2_path, index=False)
        logger.info("Phase 2: Written %d rows to %s", len(df), step2_path)

        # Post-write schema assertion — guards Phases 3 and 4
        written_cols = set(pd.read_parquet(step2_path).columns)
        missing_cols = _STEP2_REQUIRED - written_cols
        if missing_cols:
            raise RuntimeError(
                f"Phase 2 schema assertion failed for {self.topic}: "
                f"missing columns {sorted(missing_cols)}"
            )
        logger.info(
            "Phase 2 schema OK — %d columns present in step2/%s.parquet",
            len(written_cols), self.topic,
        )

    # ------------------------------------------------------------------
    # Phase 3 — SCRC-I and SCRC-T baselines
    # ------------------------------------------------------------------

    def phase3_scrc(self) -> None:
        ckpt = self.out_dir / "scrc" / "scrc_results.parquet"
        if self._skip_if_exists(ckpt, "Phase 3: SCRC"):
            return
        # scrc.py resolves parquet as data_dir/{topic}.parquet; point it at step2/
        self._run(
            [
                sys.executable, "-m", "cascade_rc.baselines.scrc",
                "--data-dir", str(self.data_dir / "step2"),
                "--out-dir",  str(self.out_dir / "scrc"),
                "--topics",   self.topic,
            ],
            label="Phase 3: SCRC",
        )

    # ------------------------------------------------------------------
    # Phase 4 — LTT calibration
    # ------------------------------------------------------------------

    def phase4_calibration(self) -> bool:
        """Run LTT calibration.

        Returns
        -------
        bool
            True  → calibration abstained; pipeline should halt gracefully.
            False → certified or skipped (pipeline continues).
        """
        cert_path = self.artefact_dir / "certificates" / f"{self.topic}.json"
        if self._skip_if_exists(cert_path, "Phase 4: Calibration"):
            return False

        self._run(
            [
                sys.executable, "-m", "cascade_rc.calibration.main_calibrate",
                "--topic",         self.topic,
                "--calib-parquet", str(self.data_dir / "step2" / f"{self.topic}.parquet"),
                "--artefact-dir",  str(self.artefact_dir),
            ],
            label="Phase 4: Calibration",
        )

        if not cert_path.exists():
            logger.warning(
                "Calibration abstained for topic %s — certificate not written. "
                "Pipeline halting gracefully.",
                self.topic,
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Phase 5 — Evaluation metrics
    # ------------------------------------------------------------------

    def phase5_metrics(self) -> None:
        ckpt = self.out_dir / "cascade_rc_results.parquet"
        if self._skip_if_exists(ckpt, "Phase 5: Metrics"):
            return

        import subprocess

        logger.info("→ Phase 5: Metrics")
        result = subprocess.run(
            [
                sys.executable, "-m", "cascade_rc.evaluation.metrics",
                "--topic",        self.topic,
                "--artefact-dir", str(self.artefact_dir),
            ],
            capture_output=True,
            text=True,
        )
        for line in result.stderr.splitlines():
            logger.debug("[metrics stderr] %s", line)
        if result.returncode != 0:
            raise RuntimeError(
                f"Phase 5: Metrics failed (exit {result.returncode})\n"
                f"stderr:\n{result.stderr[-800:]}"
            )

        # Robust JSON extraction: the metrics module emits exactly one JSON
        # object on stdout, but other log lines may precede or follow it.
        stdout = result.stdout
        start = stdout.find("{")
        end = stdout.rfind("}") + 1
        if start == -1 or end <= 0:
            raise RuntimeError(
                f"Phase 5: No JSON object found in metrics stdout.\n"
                f"stdout was: {stdout[:300]!r}"
            )
        try:
            payload = json.loads(stdout[start:end])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Phase 5: JSON parse error: {exc}\n"
                f"Extracted block: {stdout[start:end][:300]!r}"
            ) from exc

        wss95 = payload["wss95"]
        achieved = wss95.get("achieved_recall")
        fnr: float | None = (1.0 - achieved) if achieved is not None else None

        # Schema must match what figures.py expects from cascade_rc_results.parquet:
        #   figures.py lines 208–212 read: topic_id, alpha, fnr, wss_95
        row = {
            "method":   "CASCADE-RC",
            "topic_id": payload["topic"],
            "alpha":    0.10,
            "wss_95":   wss95.get("wss"),
            "fnr":      fnr,
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([row]).to_parquet(ckpt, index=False)
        logger.info("✓ Phase 5: Metrics complete — wrote %s", ckpt)

    # ------------------------------------------------------------------
    # Phase 6 — Publication figures
    # ------------------------------------------------------------------

    def phase6_figures(self) -> None:
        ckpt = self.artefact_dir / "figures" / "figure1.pdf"
        if self._skip_if_exists(ckpt, "Phase 6: Figures"):
            return
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        self._run(
            [
                sys.executable, "-m", "cascade_rc.evaluation.figures",
                "--artefact-dir", str(self.artefact_dir),
            ],
            env=env,
            label="Phase 6: Figures",
        )

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info(
            "=== CASCADE-RC pipeline START  topic=%s  artefact_dir=%s ===",
            self.topic, self.artefact_dir,
        )
        try:
            self.phase1_independent_baselines()
            self.phase2_merge_llm_u()
            self.phase3_scrc()
            if self.phase4_calibration():
                logger.info(
                    "=== Pipeline halted after Phase 4 abstention  topic=%s ===",
                    self.topic,
                )
                return
            self.phase5_metrics()
            self.phase6_figures()
        except RuntimeError as exc:
            logger.error("Pipeline error: %s", exc)
            sys.exit(1)
        except Exception:
            logger.error("Unexpected pipeline error", exc_info=True)
            sys.exit(1)

        logger.info(
            "=== CASCADE-RC pipeline COMPLETE  topic=%s ===",
            self.topic,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="State-driven end-to-end CASCADE-RC evaluation pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--topic",
        required=True,
        help="CLEF-TAR topic ID, e.g. CD008874",
    )
    p.add_argument(
        "--artefact-dir",
        type=Path,
        default=Path("artefacts/cascade_rc"),
        help="Root artefact directory.",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing topic parquets (default: {artefact-dir}/data).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Baseline output directory (default: {artefact-dir}/baselines).",
    )
    p.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to llm_cache.db (default: {artefact-dir}/llm_cache.db).",
    )
    p.add_argument(
        "--model-id",
        default="gpt-oss:120b",
        help="LLM model_id filter for the SQLite query.",
    )
    p.add_argument(
        "--template-v",
        default="v1",
        help="Template version filter for the SQLite query.",
    )
    return p


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.INFO,
    )
    args = _build_parser().parse_args()

    artefact_dir: Path = args.artefact_dir
    data_dir: Path = args.data_dir   or artefact_dir / "data"
    out_dir:  Path = args.out_dir    or artefact_dir / "baselines"
    db_path:  Path = args.db_path    or artefact_dir / "llm_cache.db"

    CascadeOrchestrator(
        topic=args.topic,
        artefact_dir=artefact_dir,
        data_dir=data_dir,
        out_dir=out_dir,
        db_path=db_path,
        model_id=args.model_id,
        template_v=args.template_v,
    ).run()


if __name__ == "__main__":
    main()
