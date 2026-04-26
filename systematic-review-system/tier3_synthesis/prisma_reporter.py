"""
tier3_synthesis/prisma_reporter.py
=====================================
Generates PRISMA 2020 flow diagrams, full review reports, and audit trails.

generate_flow_diagram   — Markdown table + JSON snapshot.
generate_review_report  — Async; full Markdown report with LLM-generated
                          Background and Conclusion (GPT_MODEL).
generate_audit_trail    — Pulls all DecisionRecords from the logger.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REQUIRED_PRISMA_FIELDS = (
    "records_identified", "duplicates_removed", "records_after_deduplication",
    "records_screened", "records_excluded_abstract",
    "records_sought_fulltext", "records_not_retrieved",
    "records_assessed_fulltext", "records_excluded_fulltext",
    "studies_included",
)


def _counts(source: Any) -> Dict:
    """Accept either a dict (prisma_counts) or a PRISMAManager / PRISMAState."""
    if isinstance(source, dict):
        return source
    # PRISMAManager has generate_prisma_counts()
    if hasattr(source, "generate_prisma_counts"):
        return source.generate_prisma_counts()
    # PRISMAState dataclass
    if hasattr(source, "stage_counts"):
        sc = source.stage_counts
        return {
            "records_identified":          sc.get("identification_total", 0),
            "duplicates_removed":          sc.get("duplicates_removed", 0),
            "records_after_deduplication": sc.get("after_dedup", 0),
            "records_screened":            sc.get("abstracts_screened", 0),
            "records_excluded_abstract":   sc.get("abstract_excluded", 0),
            "records_sought_fulltext":     sc.get("fulltext_sought", 0),
            "records_not_retrieved":       sc.get("fulltext_not_retrieved", 0),
            "records_assessed_fulltext":   sc.get("fulltext_assessed", 0),
            "records_excluded_fulltext":   sc.get("fulltext_excluded", 0),
            "studies_included":            sc.get("studies_included", 0),
            "exclusion_reasons":           dict(getattr(source, "exclusion_reasons", {})),
        }
    return {}


class PRISMAReporter:
    """
    Parameters
    ----------
    output_dir : str | Path — base directory for saved reports.
    """

    def __init__(self, output_dir: str = "data/reports") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Flow diagram
    # ------------------------------------------------------------------

    def generate_flow_diagram(self, prisma_state: Any) -> str:
        """
        Render PRISMA 2020 flow as a Markdown table and save JSON snapshot.

        Returns the file path of the Markdown file.
        """
        c = _counts(prisma_state)

        md_lines = [
            "# PRISMA 2020 Flow Diagram",
            "",
            f"*Generated: {datetime.now().isoformat(timespec='seconds')}*",
            "",
            "## Identification",
            "",
            "| Stage | Count |",
            "|---|---:|",
            f"| Records identified | {c.get('records_identified', 0)} |",
            f"| Duplicates removed | {c.get('duplicates_removed', 0)} |",
            f"| Records after deduplication | {c.get('records_after_deduplication', 0)} |",
            "",
            "## Screening",
            "",
            "| Stage | Count |",
            "|---|---:|",
            f"| Records screened (title/abstract) | {c.get('records_screened', 0)} |",
            f"| Excluded at abstract stage | {c.get('records_excluded_abstract', 0)} |",
            f"| Full texts sought | {c.get('records_sought_fulltext', 0)} |",
            f"| Full texts not retrieved | {c.get('records_not_retrieved', 0)} |",
            f"| Full texts assessed for eligibility | {c.get('records_assessed_fulltext', 0)} |",
            f"| Excluded at full-text stage | {c.get('records_excluded_fulltext', 0)} |",
            "",
            "## Included",
            "",
            "| Stage | Count |",
            "|---|---:|",
            f"| Studies included | {c.get('studies_included', 0)} |",
            "",
        ]

        reasons = c.get("exclusion_reasons", {})
        if reasons:
            md_lines += [
                "### Full-text exclusion reasons",
                "",
                "| Reason | n |",
                "|---|---:|",
            ]
            for reason, n in sorted(reasons.items(), key=lambda x: -x[1]):
                md_lines.append(f"| {reason} | {n} |")
            md_lines.append("")

        md = "\n".join(md_lines)

        md_path = self._output_dir / "prisma_flow.md"
        md_path.write_text(md, encoding="utf-8")

        json_path = self._output_dir / "prisma_flow.json"
        json_path.write_text(json.dumps(c, indent=2, default=str), encoding="utf-8")

        logger.info("PRISMAReporter: flow diagram saved to %s", md_path)
        return str(md_path)

    # ------------------------------------------------------------------
    # 2. Review report (async — calls LLM)
    # ------------------------------------------------------------------

    async def generate_review_report(
        self,
        protocol:            Any,             # ReviewProtocol
        included_studies:    List[str],        # record_ids
        extracted_data:      List[Any],        # List[ExtractedData | dict]
        quality_assessments: List[Any],        # List[RoBAssessment | dict]
        prisma_state:        Any,
        llm_client:          Optional[Any] = None,
    ) -> str:
        """
        Generate a structured Markdown review report and save it.

        Returns the file path.
        """
        c = _counts(prisma_state)
        pico = getattr(protocol, "pico", None)

        pico_text = ""
        if pico:
            pico_text = (
                f"- **Population:** {pico.population}\n"
                f"- **Intervention:** {pico.intervention}\n"
                f"- **Comparator:** {pico.comparator}\n"
                f"- **Outcome:** {pico.outcome}\n"
                f"- **Study design:** {pico.study_design}"
            )

        # LLM-generated Background
        background = await self._llm_background(protocol, llm_client)
        # LLM-generated Conclusion
        conclusion = await self._llm_conclusion(
            protocol, c, len(included_studies), llm_client
        )

        # Included studies table
        studies_rows = "\n".join(
            f"| {i+1} | {sid} |"
            for i, sid in enumerate(included_studies)
        )
        studies_table = (
            "| # | Study ID |\n|---|---|\n" + studies_rows
            if studies_rows else "*No studies included.*"
        )

        # Quality table
        quality_rows = self._quality_table_rows(quality_assessments)
        quality_table = (
            "| Study | Tool | Overall |\n|---|---|---|\n" + "\n".join(quality_rows)
            if quality_rows else "*No quality assessments performed.*"
        )

        # Inclusion criteria list
        criteria_text = "\n".join(
            f"- {c.text}" for c in getattr(protocol, "inclusion_criteria", [])
        ) or "*(not specified)*"

        md = f"""# Systematic Review Report

*Generated: {datetime.now().isoformat(timespec='seconds')}*

## Background

{background}

### PICO Framework

{pico_text}

### Eligibility Criteria

{criteria_text}

## Methods

### Search Strategy

Searches were conducted across {", ".join(getattr(protocol, "target_databases", ["multiple databases"]))}.
A total of {c.get("records_identified", 0)} records were identified.
After removing {c.get("duplicates_removed", 0)} duplicates,
{c.get("records_after_deduplication", 0)} unique records were screened.

### Screening

| Stage | n |
|---|---:|
| Title/abstract screening | {c.get("records_screened", 0)} |
| Excluded at abstract stage | {c.get("records_excluded_abstract", 0)} |
| Full texts assessed | {c.get("records_assessed_fulltext", 0)} |
| Excluded at full-text stage | {c.get("records_excluded_fulltext", 0)} |

## Results

### Included Studies

{c.get("studies_included", 0)} studies met the eligibility criteria.

{studies_table}

### Quality Assessment

{quality_table}

## Limitations

- This review was conducted using an automated pipeline; manual verification of
  screening decisions and data extraction is recommended.
- Full-text retrieval was limited to open-access sources; paywalled articles
  may have been missed.
- Quality assessment was performed by a language model and may not fully replace
  expert judgment.

## Conclusion

{conclusion}
"""

        out_path = self._output_dir / "review_report.md"
        out_path.write_text(md, encoding="utf-8")

        # Also save machine-readable JSON
        json_path = self._output_dir / "review_report.json"
        json_path.write_text(
            json.dumps(
                {
                    "review_title":       getattr(protocol, "title", ""),
                    "research_question":  getattr(protocol, "research_question", ""),
                    "generated_at":       datetime.now().isoformat(timespec="seconds"),
                    "prisma_counts":      c,
                    "included_records":   included_studies,
                    "n_included":         len(included_studies),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        logger.info("PRISMAReporter: review report saved to %s", out_path)
        return str(out_path)

    # ------------------------------------------------------------------
    # 3. Audit trail
    # ------------------------------------------------------------------

    def generate_audit_trail(self, decision_logger: Any) -> Dict:
        """
        Pull all DecisionRecords from *decision_logger* and return a summary dict.
        """
        try:
            all_records = decision_logger.export_json()
            if isinstance(all_records, str):
                records = json.loads(all_records)
            else:
                records = all_records if isinstance(all_records, list) else []
        except Exception as exc:
            logger.warning("PRISMAReporter.generate_audit_trail: %s", exc)
            records = []

        stage_counts: Dict[str, int] = Counter(
            r.get("stage", "unknown") for r in records
        )
        model_versions = list({r.get("model_used", "") for r in records if r.get("model_used")})
        timestamps     = [r.get("timestamp", "") for r in records if r.get("timestamp")]

        trail = {
            "total_decisions":   len(records),
            "decisions_by_stage": dict(stage_counts),
            "model_versions_used": model_versions,
            "first_decision":    min(timestamps) if timestamps else None,
            "last_decision":     max(timestamps) if timestamps else None,
        }

        out_path = self._output_dir / "audit_trail.json"
        out_path.write_text(json.dumps(trail, indent=2, default=str), encoding="utf-8")
        logger.info("PRISMAReporter: audit trail saved to %s", out_path)
        return trail

    # ------------------------------------------------------------------
    # Internal LLM helpers
    # ------------------------------------------------------------------

    async def _llm_background(self, protocol: Any, llm_client: Optional[Any]) -> str:
        if llm_client is None:
            return (
                f"This systematic review addresses the research question: "
                f"{getattr(protocol, 'research_question', '')}."
            )
        pico = getattr(protocol, "pico", None)
        pico_text = (
            f"Population: {pico.population}, Intervention: {pico.intervention}, "
            f"Comparator: {pico.comparator}, Outcome: {pico.outcome}"
        ) if pico else ""
        prompt = (
            f"Write a 2–3 sentence background paragraph for a systematic review.\n"
            f"Research question: {getattr(protocol, 'research_question', '')}\n"
            f"PICO: {pico_text}\n"
            "Be concise and academic. Output only the paragraph text."
        )
        try:
            resp = await llm_client.complete(
                prompt=prompt,
                system="You are a systematic review writer.",
                model=llm_client.GPT_MODEL,
                temperature=0.3,
                max_tokens=200,
            )
            return (resp.content or "").strip()
        except Exception as exc:
            logger.warning("PRISMAReporter: background LLM call failed: %s", exc)
            return f"Research question: {getattr(protocol, 'research_question', '')}."

    async def _llm_conclusion(
        self,
        protocol:   Any,
        counts:     Dict,
        n_included: int,
        llm_client: Optional[Any],
    ) -> str:
        if llm_client is None:
            return (
                f"This review identified {n_included} eligible studies. "
                "Further research may be warranted."
            )
        prompt = (
            f"Write a 2–3 sentence conclusion for a systematic review.\n"
            f"Research question: {getattr(protocol, 'research_question', '')}\n"
            f"Number of included studies: {n_included}\n"
            f"Total records screened: {counts.get('records_screened', 0)}\n"
            "Be cautious and academic. Output only the paragraph text."
        )
        try:
            resp = await llm_client.complete(
                prompt=prompt,
                system="You are a systematic review writer.",
                model=llm_client.GPT_MODEL,
                temperature=0.3,
                max_tokens=200,
            )
            return (resp.content or "").strip()
        except Exception as exc:
            logger.warning("PRISMAReporter: conclusion LLM call failed: %s", exc)
            return (
                f"A total of {n_included} studies were included. "
                "These findings should be interpreted in the context of the review limitations."
            )

    @staticmethod
    def _quality_table_rows(quality_assessments: List[Any]) -> List[str]:
        rows: List[str] = []
        for qa in quality_assessments:
            d = qa if isinstance(qa, dict) else {}
            rows.append(
                f"| {d.get('study_id', '-')} "
                f"| {d.get('tool', '-').upper()} "
                f"| {d.get('overall_judgment', '-')} |"
            )
        return rows
