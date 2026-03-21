"""
report_generator.py — Automated Research Report
=================================================
Generates a structured Markdown report from pipeline outputs.
Called from pipeline.py _build_summary() after all modules complete.
"""

import json
import os
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def generate_report(
    research_question: str,
    prisma_counts: dict,
    extracted_papers: list,
    quality_summary: dict,
    rq_answers: dict,
    output_dir: str,
) -> str:
    """
    Generate a Markdown research report.
    Returns path to the saved .md file.
    """
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    p    = prisma_counts
    lines = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines += [
        "# Systematic Literature Review Report",
        f"**Generated:** {now}  ",
        f"**Research Question:** {research_question}",
        "",
        "---",
        "",
    ]

    # ── 1. Search & Identification ───────────────────────────────────────────
    lines += [
        "## 1. Search and Identification",
        "",
        f"The automated search queried **PubMed** and **Semantic Scholar** using a "
        f"PICO-structured Boolean query. "
        f"A total of **{p.get('identified', 0):,}** records were identified.",
        "",
        "| Stage | Count |",
        "|-------|------:|",
        f"| Records identified (PubMed + Semantic Scholar) | {p.get('identified', 0):,} |",
        f"| Records screened (title/abstract) | {p.get('screened', 0):,} |",
        f"| Excluded at title/abstract | {p.get('excluded_ta', 0):,} |",
        f"| Uncertain (flagged for human review) | {p.get('uncertain', 0):,} |",
        f"| Assessed for full-text eligibility | {p.get('sent_to_fulltext', 0):,} |",
        f"| No open-access PDF available | {p.get('no_pdf', 0):,} |",
        f"| Excluded at full-text | {p.get('excluded_ft', 0):,} |",
        f"| **Included in synthesis** | **{p.get('included', 0):,}** |",
        f"| Data extracted | {p.get('extracted', 0):,} |",
        "",
        "> See attached PRISMA flow diagram for a visual representation.",
        "",
        "---",
        "",
    ]

    # ── 2. Included Studies ───────────────────────────────────────────────────
    lines += [
        "## 2. Included Studies Overview",
        "",
    ]

    tools = [
        (
            p_.get("tool_name"),
            p_.get("llm_used"),
            p_.get("year"),
            p_.get("reported_kappa"),
            p_.get("reported_sensitivity"),
            p_.get("prisma_stages_covered"),
        )
        for p_ in extracted_papers
        if p_.get("tool_name")
    ]

    if tools:
        lines += [
            "| Tool | LLM / Model | Year | Sensitivity | Kappa | PRISMA Stages |",
            "|------|-------------|-----:|------------:|------:|---------------|",
        ]
        for tool, llm, year, kappa, sens, stages in tools:
            kappa_s = f"{kappa:.2f}" if kappa is not None else "NR"
            sens_s  = f"{sens:.2f}"  if sens  is not None else "NR"
            lines.append(
                f"| {tool or 'NR'} | {llm or 'NR'} | {year or 'NR'} "
                f"| {sens_s} | {kappa_s} | {stages or 'NR'} |"
            )
        lines.append("")
    else:
        lines.append("_No tool data extracted (extraction may not have run or all PDFs were unavailable)._\n")

    # Aggregate metrics
    sensitivities = [p_['reported_sensitivity'] for p_ in extracted_papers if p_.get('reported_sensitivity')]
    specificities = [p_['reported_specificity'] for p_ in extracted_papers if p_.get('reported_specificity')]
    kappas        = [p_['reported_kappa']       for p_ in extracted_papers if p_.get('reported_kappa')]
    f1s           = [p_['reported_f1']          for p_ in extracted_papers if p_.get('reported_f1')]

    if any([sensitivities, specificities, kappas, f1s]):
        lines += [
            "### Aggregate Performance Metrics",
            "",
        ]
        if sensitivities:
            lines.append(f"- **Sensitivity (recall):** mean = {sum(sensitivities)/len(sensitivities):.2f}  "
                         f"(range {min(sensitivities):.2f}–{max(sensitivities):.2f}, n={len(sensitivities)})")
        if specificities:
            lines.append(f"- **Specificity:** mean = {sum(specificities)/len(specificities):.2f}  "
                         f"(range {min(specificities):.2f}–{max(specificities):.2f}, n={len(specificities)})")
        if kappas:
            lines.append(f"- **Inter-rater agreement (κ):** mean = {sum(kappas)/len(kappas):.2f}  "
                         f"(range {min(kappas):.2f}–{max(kappas):.2f}, n={len(kappas)})")
        if f1s:
            lines.append(f"- **F1 score:** mean = {sum(f1s)/len(f1s):.2f}  "
                         f"(range {min(f1s):.2f}–{max(f1s):.2f}, n={len(f1s)})")
        lines.append("")

    lines += ["---", ""]

    # ── 3. Quality Assessment ─────────────────────────────────────────────────
    lines += [
        "## 3. Methodological Quality (CASP Assessment)",
        "",
    ]

    if quality_summary and quality_summary.get("total_assessed", 0) > 0:
        total = quality_summary["total_assessed"]
        high  = quality_summary.get("high", 0)
        mod   = quality_summary.get("moderate", 0)
        low   = quality_summary.get("low", 0)
        avg   = quality_summary.get("avg_overall_score", 0)

        lines += [
            f"Quality appraisal was performed automatically using the CASP checklist "
            f"(10 questions) plus 4 risk-of-bias items ({total} papers assessed).",
            "",
            "| Quality Grade | Count | Proportion |",
            "|---------------|------:|-----------:|",
            f"| High (score ≥ 0.70) | {high} | {high/total:.0%} |",
            f"| Moderate (0.45–0.70) | {mod} | {mod/total:.0%} |",
            f"| Low (< 0.45) | {low} | {low/total:.0%} |",
            f"| **Average score** | | **{avg:.2f}** |",
            "",
        ]
    else:
        lines.append("_Quality assessment not completed._\n")

    lines += ["---", ""]

    # ── 4. Research Questions ─────────────────────────────────────────────────
    lines += [
        "## 4. Research Questions",
        "",
    ]

    if rq_answers:
        for q, a in rq_answers.items():
            answer_text = a.get("answer", "No answer generated") if isinstance(a, dict) else str(a)
            lines += [f"### {q}", "", answer_text, ""]
    else:
        lines.append("_Research questions not answered (knowledge graph may not have run)._\n")

    lines += ["---", ""]

    # ── 5. Limitations ────────────────────────────────────────────────────────
    lines += [
        "## 5. Limitations",
        "",
        "- Search limited to PubMed and Semantic Scholar (2 of 4+ databases used in comparable reviews).",
        "- Full-text screening limited to open-access PDFs; "
        f"{p.get('no_pdf', 0)} papers were excluded due to paywall restrictions.",
        "- LLM-based screening and extraction may introduce errors; "
        f"{p.get('uncertain', 0)} papers were flagged as uncertain and require human review.",
        "- Quality assessment performed automatically using CASP criteria; "
        "human validation is recommended before final synthesis.",
        "- Results are dependent on the accuracy and availability of the BFH LLM endpoint.",
        "",
        "---",
        "",
        f"*Report generated automatically by the Autonomous Research Assistant pipeline.*  ",
        f"*Run date: {now}*",
    ]

    # ── Save ─────────────────────────────────────────────────────────────────
    md_path = os.path.join(output_dir, "research_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info("Research report saved → %s", md_path)
    return md_path