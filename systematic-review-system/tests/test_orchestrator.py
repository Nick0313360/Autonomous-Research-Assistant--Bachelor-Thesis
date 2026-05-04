"""
tests/test_orchestrator.py
===========================
Mock-heavy test suite for run_orchestrator.py.

No real subprocesses, LLM calls, or calibration runs are executed.
Every external boundary is patched:
  - subprocess.run       — prevents spawning real CLI modules
  - sqlite3.connect      — prevents accessing llm_cache.db

Real file I/O is deliberately allowed inside tmp_path:
  - Source parquet is written once per test by the `env` fixture.
  - Phase 2 writes step2/{topic}.parquet to tmp_path (real write + real read-back
    for the schema assertion).
  - Phase 5 writes cascade_rc_results.parquet to tmp_path.

This strategy makes the integration points (Phase 2 ETL, Phase 5 JSON extraction,
Phase 4 cert-file check) observable against real file state, while keeping the
pipeline fast and hermetic.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from run_orchestrator import CascadeOrchestrator, _STEP2_REQUIRED

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

TOPIC = "CD008874"

# Minimal source parquet schema (mirrors what update_parquet.py produces)
_SOURCE_DF = pd.DataFrame(
    {
        "pmid":       ["1", "2", "3"],
        "title":      ["Title A", "Title B", "Title C"],
        "abstract":   ["Abstract A", "Abstract B", "Abstract C"],
        "y_abstract": pd.array([1, 0, 1], dtype="int8"),
        "is_calib":   pd.array([1, 1, 0], dtype="int8"),
        "s":          pd.array([0.80, 0.30, 0.70], dtype="float64"),
        "u":          pd.array([0.70, 0.20, 0.60], dtype="float64"),
    }
)

# SQLite vote rows: ORDER BY pmid, seed_b already applied
# pmid "1": Include×3 + Exclude×1 + Uncertain×1  → majority=Include, u=3/5=0.6, y_hat=1
# pmid "2": Exclude×3 + Include×1 + Uncertain×1  → majority=Exclude, u=3/5=0.6, y_hat=0
# pmid "3": (no rows)                             → fallback u=0.0, y_hat=0
_SQLITE_ROWS = [
    ("1", "Include"),  ("1", "Include"), ("1", "Include"),
    ("1", "Exclude"),  ("1", "Uncertain"),
    ("2", "Exclude"),  ("2", "Exclude"), ("2", "Exclude"),
    ("2", "Include"),  ("2", "Uncertain"),
]

# Canonical metrics payload as emitted by cascade_rc.evaluation.metrics
_METRICS_PAYLOAD = {
    "topic":  TOPIC,
    "status": "certified",
    "wss95":  {"wss": 0.42, "achieved_recall": 0.96, "status": "ok"},
    "llm_volume":      {"llm": 100, "human": 50},
    "slack_ratio_mean": 1.2,
    "slack_ratio_std":  0.1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "", stderr: str = "") -> MagicMock:
    """Return a mock subprocess.CompletedProcess with returncode=0."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _fail(returncode: int = 1, stderr: str = "process error") -> MagicMock:
    """Return a mock subprocess.CompletedProcess with a non-zero returncode."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = ""
    m.stderr = stderr
    return m


def _mock_sqlite(rows=_SQLITE_ROWS) -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = list(rows)
    return conn


def _make_full_run_side_effect(cert_path: Path, metrics_payload: dict):
    """Build a subprocess.run side_effect for a complete, successful pipeline run.

    - Phase 4 (main_calibrate): creates the certificate JSON on disk.
    - Phase 5 (evaluation.metrics): returns realistic noisy stdout with embedded JSON.
    - All other phases: return plain success.
    """
    def side_effect(cmd, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        if "main_calibrate" in cmd_str:
            cert_path.parent.mkdir(parents=True, exist_ok=True)
            cert_path.write_text(
                json.dumps({"topic": TOPIC, "status": "certified"})
            )
            return _ok()
        if "evaluation.metrics" in cmd_str:
            noisy = (
                "INFO:root: loading certificate...\n"
                f"{json.dumps(metrics_payload)}\n"
                "INFO:root: done.\n"
            )
            return _ok(stdout=noisy)
        return _ok()
    return side_effect


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path):
    """
    Provision directory structure + source parquet; yield (orchestrator, paths).

    Directories created:
        {tmp_path}/artefacts/cascade_rc/data/
        {tmp_path}/artefacts/cascade_rc/baselines/

    Source parquet written at:
        {data_dir}/{TOPIC}.parquet
    """
    artefact_dir = tmp_path / "artefacts" / "cascade_rc"
    data_dir     = artefact_dir / "data"
    out_dir      = artefact_dir / "baselines"
    db_path      = artefact_dir / "llm_cache.db"

    data_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    _SOURCE_DF.to_parquet(data_dir / f"{TOPIC}.parquet", index=False)

    orc = CascadeOrchestrator(
        topic=TOPIC,
        artefact_dir=artefact_dir,
        data_dir=data_dir,
        out_dir=out_dir,
        db_path=db_path,
    )
    return orc, artefact_dir, data_dir, out_dir


# ---------------------------------------------------------------------------
# Integration tests — full pipeline
# ---------------------------------------------------------------------------

class TestFullPipelineRun:

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_all_phases_called_in_order(self, mock_run, mock_sqlite, env):
        """Full successful run: all 6 subprocess phases execute in the correct order."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        # 6 subprocess.run calls: 1a, 1b, 3, 4, 5, 6 (Phase 2 is in-process)
        assert mock_run.call_count == 6, (
            f"Expected 6 subprocess.run calls, got {mock_run.call_count}"
        )

        cmds = [" ".join(str(c) for c in call.args[0])
                for call in mock_run.call_args_list]

        # Every expected module appears exactly once
        assert sum("run_autostop"       in c for c in cmds) == 1
        assert sum("run_rlstop"         in c for c in cmds) == 1
        assert sum(".scrc"              in c for c in cmds) == 1
        assert sum("main_calibrate"     in c for c in cmds) == 1
        assert sum("evaluation.metrics" in c for c in cmds) == 1
        assert sum("evaluation.figures" in c for c in cmds) == 1

        # Strict ordering
        idx = {
            label: next(i for i, c in enumerate(cmds) if label in c)
            for label in [
                "run_autostop", "run_rlstop", ".scrc",
                "main_calibrate", "evaluation.metrics", "evaluation.figures",
            ]
        }
        assert idx["run_autostop"]      < idx["run_rlstop"]
        assert idx["run_rlstop"]        < idx[".scrc"]
        assert idx[".scrc"]             < idx["main_calibrate"]
        assert idx["main_calibrate"]    < idx["evaluation.metrics"]
        assert idx["evaluation.metrics"] < idx["evaluation.figures"]

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_step2_parquet_written_with_required_columns(self, mock_run, mock_sqlite, env):
        """Phase 2 step2 parquet contains all columns required by SCRC and calibration."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        step2_df = pd.read_parquet(data_dir / "step2" / f"{TOPIC}.parquet")
        assert _STEP2_REQUIRED.issubset(set(step2_df.columns)), (
            f"Missing: {_STEP2_REQUIRED - set(step2_df.columns)}"
        )

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_cascade_rc_results_correct_schema(self, mock_run, mock_sqlite, env):
        """Phase 5 writes cascade_rc_results.parquet with schema matching figures.py expectations."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        results = pd.read_parquet(out_dir / "cascade_rc_results.parquet")
        assert set(results.columns) == {"method", "topic_id", "alpha", "wss_95", "fnr"}

        row = results.iloc[0]
        assert row["method"]   == "CASCADE-RC"
        assert row["topic_id"] == TOPIC
        assert row["alpha"]    == pytest.approx(0.10)
        assert row["wss_95"]   == pytest.approx(0.42)
        assert row["fnr"]      == pytest.approx(1.0 - 0.96)

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_scrc_reads_from_step2_directory(self, mock_run, mock_sqlite, env):
        """Phase 3 (SCRC) is invoked with --data-dir pointing at step2/, not data/."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        scrc_call = next(
            call for call in mock_run.call_args_list
            if ".scrc" in " ".join(str(c) for c in call.args[0])
        )
        scrc_args = scrc_call.args[0]
        data_dir_idx = scrc_args.index("--data-dir")
        assert str(data_dir / "step2") == scrc_args[data_dir_idx + 1]

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_calibration_reads_from_step2_parquet(self, mock_run, mock_sqlite, env):
        """Phase 4 (calibration) is invoked with --calib-parquet pointing at step2/{topic}.parquet."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        cal_call = next(
            call for call in mock_run.call_args_list
            if "main_calibrate" in " ".join(str(c) for c in call.args[0])
        )
        cal_args = cal_call.args[0]
        parquet_idx = cal_args.index("--calib-parquet")
        expected = str(data_dir / "step2" / f"{TOPIC}.parquet")
        assert cal_args[parquet_idx + 1] == expected


# ---------------------------------------------------------------------------
# Integration tests — checkpointing / resumability
# ---------------------------------------------------------------------------

class TestCheckpointing:

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_phases_1_and_2_skipped_when_checkpoints_exist(
        self, mock_run, mock_sqlite, env
    ):
        """Orchestrator skips Phases 1a, 1b and 2 when their checkpoint files exist."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        # Pre-create Phase 1 checkpoints
        (out_dir / "autostop").mkdir(parents=True)
        (out_dir / "autostop" / "autostop_results.parquet").touch()
        (out_dir / "rlstop").mkdir(parents=True)
        (out_dir / "rlstop" / "rlstop_results.parquet").touch()

        # Pre-create Phase 2 checkpoint (step2 parquet with all required columns)
        step2_dir = data_dir / "step2"
        step2_dir.mkdir(parents=True)
        step2_df = _SOURCE_DF.copy()
        step2_df["llm_y_hat"] = pd.array([1, 0, 1], dtype="int8")
        step2_df.to_parquet(step2_dir / f"{TOPIC}.parquet", index=False)

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        # Only 4 subprocess calls: phase3, phase4, phase5, phase6
        assert mock_run.call_count == 4

        cmds = [" ".join(str(c) for c in call.args[0])
                for call in mock_run.call_args_list]
        assert not any("run_autostop" in c for c in cmds), "Phase 1a should be skipped"
        assert not any("run_rlstop"   in c for c in cmds), "Phase 1b should be skipped"

        # Phase 2 did not open the database
        mock_sqlite.assert_not_called()

        # Phases 3–6 ran
        assert any(".scrc"              in c for c in cmds)
        assert any("main_calibrate"     in c for c in cmds)
        assert any("evaluation.metrics" in c for c in cmds)
        assert any("evaluation.figures" in c for c in cmds)

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_figures_skipped_when_checkpoint_exists(self, mock_run, mock_sqlite, env):
        """Phase 6 is skipped when figures/figure1.pdf already exists."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        # Pre-create Phase 6 checkpoint
        figures_dir = artefact_dir / "figures"
        figures_dir.mkdir(parents=True)
        (figures_dir / "figure1.pdf").touch()

        mock_sqlite.return_value = _mock_sqlite()
        mock_run.side_effect = _make_full_run_side_effect(cert_path, _METRICS_PAYLOAD)

        orc.run()

        cmds = [" ".join(str(c) for c in call.args[0])
                for call in mock_run.call_args_list]
        assert not any("evaluation.figures" in c for c in cmds), (
            "Phase 6 should be skipped when figure1.pdf exists"
        )


# ---------------------------------------------------------------------------
# Integration tests — calibration abstention
# ---------------------------------------------------------------------------

class TestCalibrationAbstention:

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_pipeline_halts_gracefully_when_cert_absent(
        self, mock_run, mock_sqlite, env
    ):
        """When calibration exits 0 but writes no certificate, the pipeline halts
        after Phase 4 without executing Phases 5 or 6."""
        orc, artefact_dir, data_dir, out_dir = env

        mock_sqlite.return_value = _mock_sqlite()
        # Phase 4 subprocess succeeds but never creates the certificate
        mock_run.return_value = _ok()

        orc.run()

        # 4 subprocess calls: 1a, 1b, 3, 4  (Phase 2 in-process)
        assert mock_run.call_count == 4

        cmds = [" ".join(str(c) for c in call.args[0])
                for call in mock_run.call_args_list]
        assert not any("evaluation.metrics" in c for c in cmds), (
            "Phase 5 must not run after calibration abstention"
        )
        assert not any("evaluation.figures" in c for c in cmds), (
            "Phase 6 must not run after calibration abstention"
        )
        assert not (out_dir / "cascade_rc_results.parquet").exists(), (
            "cascade_rc_results.parquet must not be written after abstention"
        )

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_pipeline_continues_when_cert_already_exists(
        self, mock_run, mock_sqlite, env
    ):
        """When the certificate already exists (Phase 4 checkpoint), pipeline proceeds to Phase 5."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        # Pre-create Phase 2 step2 parquet and certificate (both checkpointed)
        step2_dir = data_dir / "step2"
        step2_dir.mkdir(parents=True)
        step2_df = _SOURCE_DF.copy()
        step2_df["llm_y_hat"] = pd.array([1, 0, 1], dtype="int8")
        step2_df.to_parquet(step2_dir / f"{TOPIC}.parquet", index=False)

        cert_path.parent.mkdir(parents=True, exist_ok=True)
        cert_path.write_text(json.dumps({"topic": TOPIC, "status": "certified"}))

        mock_sqlite.return_value = _mock_sqlite()
        # Phases 1a, 1b, 3 run; 4 skipped (cert exists); 5 returns JSON; 6 runs
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "evaluation.metrics" in cmd_str:
                return _ok(stdout=json.dumps(_METRICS_PAYLOAD))
            return _ok()
        mock_run.side_effect = side_effect

        orc.run()

        # Phase 4 is skipped — 4 subprocess calls: 1a, 1b, 3, 5, 6
        cmds = [" ".join(str(c) for c in call.args[0])
                for call in mock_run.call_args_list]
        assert not any("main_calibrate"     in c for c in cmds), "Phase 4 should be skipped"
        assert     any("evaluation.metrics" in c for c in cmds)
        assert     any("evaluation.figures" in c for c in cmds)


# ---------------------------------------------------------------------------
# Integration test — Phase 5 JSON extraction robustness
# ---------------------------------------------------------------------------

class TestPhase5JsonExtraction:

    @pytest.mark.parametrize("noisy_prefix,noisy_suffix", [
        ("", ""),                               # clean JSON, no noise
        ("INFO loading\n", "\nINFO done\n"),    # log lines surrounding JSON
        ("WARNING: x\nDEBUG: y\n", "\n"),       # multi-line prefix noise
        ("INFO: a\n", "\nINFO: b\nINFO: c\n"), # noise on both sides
    ])
    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_json_correctly_extracted_from_noisy_stdout(
        self, mock_run, mock_sqlite, noisy_prefix, noisy_suffix, env
    ):
        """Phase 5 correctly extracts JSON regardless of surrounding log noise in stdout."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "main_calibrate" in cmd_str:
                cert_path.parent.mkdir(parents=True, exist_ok=True)
                cert_path.write_text(json.dumps({"topic": TOPIC, "status": "certified"}))
                return _ok()
            if "evaluation.metrics" in cmd_str:
                noisy = noisy_prefix + json.dumps(_METRICS_PAYLOAD) + noisy_suffix
                return _ok(stdout=noisy)
            return _ok()

        mock_run.side_effect = side_effect
        orc.run()

        results = pd.read_parquet(out_dir / "cascade_rc_results.parquet")
        assert results["topic_id"].iloc[0] == TOPIC
        assert results["wss_95"].iloc[0]   == pytest.approx(0.42)
        assert results["fnr"].iloc[0]      == pytest.approx(1.0 - 0.96)
        assert results["alpha"].iloc[0]    == pytest.approx(0.10)
        assert results["method"].iloc[0]   == "CASCADE-RC"

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_none_fnr_when_achieved_recall_is_null(
        self, mock_run, mock_sqlite, env
    ):
        """Phase 5 sets fnr=None when achieved_recall is null (recall target missed)."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        null_payload = {
            **_METRICS_PAYLOAD,
            "wss95": {"wss": None, "achieved_recall": None, "status": "recall_target_missed"},
        }

        mock_sqlite.return_value = _mock_sqlite()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "main_calibrate" in cmd_str:
                cert_path.parent.mkdir(parents=True, exist_ok=True)
                cert_path.write_text(json.dumps({"topic": TOPIC, "status": "certified"}))
                return _ok()
            if "evaluation.metrics" in cmd_str:
                return _ok(stdout=json.dumps(null_payload))
            return _ok()

        mock_run.side_effect = side_effect
        orc.run()

        results = pd.read_parquet(out_dir / "cascade_rc_results.parquet")
        assert results["fnr"].iloc[0]   is None or pd.isna(results["fnr"].iloc[0])
        assert results["wss_95"].iloc[0] is None or pd.isna(results["wss_95"].iloc[0])


# ---------------------------------------------------------------------------
# Integration test — failure handling
# ---------------------------------------------------------------------------

class TestFailureHandling:

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_phase1a_failure_exits_with_code_1(self, mock_run, mock_sqlite, env):
        """Non-zero exit from Phase 1a causes SystemExit(1); no further phases run."""
        orc, _, _, _ = env
        mock_run.return_value = _fail(returncode=2, stderr="autostop crashed")

        with pytest.raises(SystemExit) as exc_info:
            orc.run()
        assert exc_info.value.code == 1

        # Only the one failing subprocess call was made
        assert mock_run.call_count == 1
        cmd_str = " ".join(str(c) for c in mock_run.call_args_list[0].args[0])
        assert "run_autostop" in cmd_str

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_phase3_failure_exits_with_code_1(self, mock_run, mock_sqlite, env):
        """Non-zero exit from Phase 3 (SCRC) causes SystemExit(1) after Phases 1 and 2 complete."""
        orc, artefact_dir, data_dir, out_dir = env

        mock_sqlite.return_value = _mock_sqlite()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if ".scrc" in cmd_str:
                return _fail(returncode=1, stderr="scrc error")
            return _ok()

        mock_run.side_effect = side_effect

        with pytest.raises(SystemExit) as exc_info:
            orc.run()
        assert exc_info.value.code == 1

        cmds = [" ".join(str(c) for c in call.args[0])
                for call in mock_run.call_args_list]
        # Phases 1a, 1b, and 3 ran; Phase 4+ did not
        assert any("run_autostop" in c for c in cmds)
        assert any("run_rlstop"   in c for c in cmds)
        assert any(".scrc"         in c for c in cmds)
        assert not any("main_calibrate"     in c for c in cmds)
        assert not any("evaluation.metrics" in c for c in cmds)

    @patch("sqlite3.connect")
    @patch("subprocess.run")
    def test_phase5_invalid_json_exits_with_code_1(self, mock_run, mock_sqlite, env):
        """Unparseable metrics stdout causes SystemExit(1) rather than an uncaught exception."""
        orc, artefact_dir, data_dir, out_dir = env
        cert_path = artefact_dir / "certificates" / f"{TOPIC}.json"

        mock_sqlite.return_value = _mock_sqlite()

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "main_calibrate" in cmd_str:
                cert_path.parent.mkdir(parents=True, exist_ok=True)
                cert_path.write_text(json.dumps({"topic": TOPIC, "status": "certified"}))
                return _ok()
            if "evaluation.metrics" in cmd_str:
                return _ok(stdout="INFO: no JSON here at all\n")
            return _ok()

        mock_run.side_effect = side_effect

        with pytest.raises(SystemExit) as exc_info:
            orc.run()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Unit tests — Phase 2 ETL (_majority_and_u integration)
# ---------------------------------------------------------------------------

class TestPhase2MergeLogic:
    """Verify that Phase 2 correctly computes u and llm_y_hat via _majority_and_u."""

    @patch("sqlite3.connect")
    def test_u_and_y_hat_values_match_majority_and_u(self, mock_sqlite, env):
        """u and llm_y_hat in step2 parquet match the expected _majority_and_u output."""
        orc, artefact_dir, data_dir, out_dir = env

        mock_sqlite.return_value = _mock_sqlite()
        orc.phase2_merge_llm_u()

        df = pd.read_parquet(data_dir / "step2" / f"{TOPIC}.parquet")

        row1 = df[df["pmid"] == "1"].iloc[0]
        assert row1["u"] == pytest.approx(0.6)   # include_count=3, n=5
        assert int(row1["llm_y_hat"]) == 1        # majority=Include

        row2 = df[df["pmid"] == "2"].iloc[0]
        assert row2["u"] == pytest.approx(0.6)   # exclude_count=3, n=5
        assert int(row2["llm_y_hat"]) == 0        # majority=Exclude

        row3 = df[df["pmid"] == "3"].iloc[0]
        assert row3["u"] == pytest.approx(0.0)   # no DB entries → fallback
        assert int(row3["llm_y_hat"]) == 0

    @patch("sqlite3.connect")
    def test_schema_assertion_raises_on_missing_column(self, mock_sqlite, env):
        """Phase 2 raises RuntimeError if source parquet is missing a required column."""
        orc, artefact_dir, data_dir, out_dir = env

        # Source parquet without 's' — step2 will therefore also lack 's'
        bad_df = _SOURCE_DF.drop(columns=["s"])
        bad_df.to_parquet(data_dir / f"{TOPIC}.parquet", index=False)

        mock_sqlite.return_value = _mock_sqlite()

        with pytest.raises(RuntimeError, match="schema assertion failed"):
            orc.phase2_merge_llm_u()

    @patch("sqlite3.connect")
    def test_phase2_idempotent_when_checkpoint_exists(self, mock_sqlite, env):
        """Phase 2 is a no-op when step2/{topic}.parquet already exists on disk."""
        orc, artefact_dir, data_dir, out_dir = env

        step2_dir = data_dir / "step2"
        step2_dir.mkdir(parents=True)
        (step2_dir / f"{TOPIC}.parquet").touch()

        orc.phase2_merge_llm_u()

        mock_sqlite.assert_not_called()

    @patch("sqlite3.connect")
    def test_sqlite_filtered_by_model_id_and_template_v(self, mock_sqlite, env):
        """Phase 2 passes model_id and template_v as query parameters to SQLite."""
        orc, artefact_dir, data_dir, out_dir = env

        mock_conn = _mock_sqlite()
        mock_sqlite.return_value = mock_conn

        orc.phase2_merge_llm_u()

        # Retrieve the args passed to conn.execute(...)
        execute_call_args = mock_conn.execute.call_args
        query_params = execute_call_args.args[1]  # second positional arg = (model_id, template_v)
        assert query_params == (orc.model_id, orc.template_v)
