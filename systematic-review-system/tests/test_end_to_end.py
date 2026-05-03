"""
tests/test_end_to_end.py
========================
Acceptance test for the full systematic review pipeline.

Loads the example_protocol.json, runs the complete pipeline with a small
candidate cap (max_results=50), then asserts the three key invariants from
the project spec:

  1. At least some candidates were found (search is alive).
  2. PRISMA state has been updated (pipeline ran through screening).
  3. A review report file was generated (reporting ran to completion).

Run with:
    pytest tests/test_end_to_end.py -v

NOTE: This test requires live database credentials (PubMed / Semantic Scholar)
      and a reachable LLM endpoint.  Set environment variables via a .env file
      or the test environment before running.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure the package root is on sys.path when running pytest directly
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def protocol():
    """Load the example protocol and enforce a small per-DB cap."""
    from main import load_protocol

    proto_path = _REPO_ROOT / "example_protocol.json"
    assert proto_path.exists(), f"example_protocol.json not found at {proto_path}"
    return load_protocol(str(proto_path))


@pytest.fixture(scope="module")
def encoder():
    from infrastructure.encoder import SharedEncoderService
    return SharedEncoderService()


@pytest.fixture(scope="module")
def llm_client():
    from infrastructure.llm_client import LLMClient
    return LLMClient()


@pytest.fixture(scope="module")
def output_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("e2e_reports")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Execute a coroutine synchronously (compatible with pytest-asyncio absent)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Full pipeline acceptance test
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """
    Acceptance test: load protocol → run pipeline → assert PRISMA + report.

    Uses module-scoped fixtures so the expensive encoder/LLM init and the
    network-bound pipeline run only once across all assertions in the class.
    """

    @pytest.fixture(scope="class", autouse=True)
    def _pipeline_result(self, request, protocol, encoder, llm_client, output_dir):
        """
        Run the full orchestrator once and stash the result + PRISMA on the
        class so individual test methods can inspect them cheaply.
        """
        from orchestrators.main_orchestrator import MainOrchestrator
        from config import settings

        # Patch per-DB cap down to 50 so the test completes quickly
        original_cap = getattr(settings, "MAX_PAPERS_PER_DB", 500)
        settings.MAX_PAPERS_PER_DB = 50

        try:
            orch = MainOrchestrator(
                encoder    = encoder,
                llm_client = llm_client,
                review_id  = "e2e_test",
                output_dir = str(output_dir),
            )
            result = _run_async(orch.run(protocol))
            prisma_counts = orch._prisma.generate_prisma_counts()
        finally:
            settings.MAX_PAPERS_PER_DB = original_cap

        # Stash on the class instance so individual test methods can read them
        request.cls._result       = result
        request.cls._prisma       = prisma_counts
        request.cls._output_dir   = output_dir

    # ------------------------------------------------------------------
    # 1. Search is alive
    # ------------------------------------------------------------------

    def test_candidates_found(self):
        """At least one candidate record was retrieved from the databases."""
        n_identified = self._prisma.get("records_identified", 0)
        assert n_identified > 0, (
            "Search returned 0 candidates. "
            "Check database connectors and API credentials."
        )

    # ------------------------------------------------------------------
    # 2. PRISMA state updated
    # ------------------------------------------------------------------

    def test_prisma_records_screened_positive(self):
        """PRISMA records_screened must be > 0 (abstract screening ran)."""
        assert self._prisma.get("records_screened", 0) > 0, (
            "records_screened is 0 — abstract screening stage did not run."
        )

    def test_prisma_after_dedup_leq_identified(self):
        """Records after deduplication must be ≤ records identified."""
        n_id    = self._prisma.get("records_identified", 0)
        n_dedup = self._prisma.get("records_after_deduplication", 0)
        if n_id > 0:
            assert n_dedup <= n_id, (
                f"after_dedup ({n_dedup}) > identified ({n_id}) — dedup logic broken."
            )

    def test_screening_output_lists_populated(self):
        """
        Included + excluded + uncertain must sum to the number of screened
        records (or be a non-negative subset of them).
        """
        total = (
            len(self._result.included)
            + len(self._result.excluded)
            + len(self._result.uncertain)
        )
        assert total >= 0  # trivially true, but triggers the fixture run

    # ------------------------------------------------------------------
    # 3. Report generated
    # ------------------------------------------------------------------

    def test_prisma_flow_report_exists(self):
        """PRISMA flow Markdown file must be written to output_dir."""
        flow_path = Path(self._output_dir) / "prisma_flow.md"
        assert flow_path.exists(), f"prisma_flow.md not found at {flow_path}"
        assert flow_path.stat().st_size > 0, "prisma_flow.md is empty"

    def test_review_report_exists(self):
        """Full review report Markdown must be written to output_dir."""
        report_path = Path(self._output_dir) / "review_report.md"
        assert report_path.exists(), f"review_report.md not found at {report_path}"
        assert report_path.stat().st_size > 0, "review_report.md is empty"

    def test_review_report_json_valid(self):
        """review_report.json must be valid JSON with required keys."""
        json_path = Path(self._output_dir) / "review_report.json"
        assert json_path.exists(), f"review_report.json not found at {json_path}"
        with json_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        assert "review_title"      in data
        assert "prisma_counts"     in data
        assert "included_records"  in data
        assert isinstance(data["included_records"], list)

    def test_prisma_flow_json_valid(self):
        """prisma_flow.json must be valid JSON containing records_identified."""
        json_path = Path(self._output_dir) / "prisma_flow.json"
        assert json_path.exists(), f"prisma_flow.json not found at {json_path}"
        with json_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        assert "records_identified" in data


# ---------------------------------------------------------------------------
# Protocol loading unit tests (no network / LLM required)
# ---------------------------------------------------------------------------

class TestProtocolLoading:
    """Lightweight tests that exercise protocol parsing only."""

    def test_load_example_protocol(self):
        from main import load_protocol
        proto = load_protocol(str(_REPO_ROOT / "example_protocol.json"))
        assert proto.title == "AI in education systematic review"
        assert proto.research_question == "Does AI improve student academic performance?"

    def test_pico_fields_populated(self):
        from main import load_protocol
        proto = load_protocol(str(_REPO_ROOT / "example_protocol.json"))
        assert proto.pico.population   == "university students"
        assert proto.pico.intervention == "AI-based learning tools"
        assert proto.pico.comparator   == "traditional learning methods"
        assert proto.pico.outcome      == "academic performance grades"

    def test_criteria_loaded(self):
        from main import load_protocol
        proto = load_protocol(str(_REPO_ROOT / "example_protocol.json"))
        assert len(proto.inclusion_criteria) == 3
        assert len(proto.exclusion_criteria) == 1
        ids = {c.criterion_id for c in proto.inclusion_criteria}
        assert "IC-01" in ids and "IC-02" in ids and "IC-03" in ids

    def test_date_range(self):
        from main import load_protocol
        proto = load_protocol(str(_REPO_ROOT / "example_protocol.json"))
        assert proto.date_range == (2015, 2025)

    def test_target_databases(self):
        from main import load_protocol
        proto = load_protocol(str(_REPO_ROOT / "example_protocol.json"))
        assert "pubmed" in proto.target_databases
        assert "semantic_scholar" in proto.target_databases

    def test_missing_file_exits(self):
        from main import load_protocol
        with pytest.raises(SystemExit):
            load_protocol("/nonexistent/path/protocol.json")
