from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np


class SACMetric:
    def __init__(self, encoder: Any, cochrane_conclusions_path: Path) -> None:
        self._encoder = encoder
        with cochrane_conclusions_path.open(encoding="utf-8") as fh:
            self._conclusions: dict = json.load(fh)

    async def compute(
        self,
        topic_id: str,
        agent_conclusion: str,
        n_permutations: int = 500,
    ) -> dict:
        if topic_id not in self._conclusions:
            return {"error": f"no ground truth for {topic_id}"}

        cochrane_text = self._conclusions[topic_id]["conclusion"]
        rephrasings = self._conclusions[topic_id].get("rephrasings", [])

        # embed_section is synchronous and returns L2-normalised vectors
        emb_agent    = self._encoder.embed_section(agent_conclusion, "conclusion")
        emb_cochrane = self._encoder.embed_section(cochrane_text,    "conclusion")

        sac_main = float(np.dot(emb_agent, emb_cochrane))

        # Permutation null: shuffle words in agent conclusion, re-embed
        words = agent_conclusion.split()
        null_sacs: list[float] = []
        for _ in range(n_permutations):
            shuffled = " ".join(random.sample(words, len(words)))
            emb_shuffled = self._encoder.embed_section(shuffled, "conclusion")
            null_sacs.append(float(np.dot(emb_shuffled, emb_cochrane)))

        null_array = np.array(null_sacs)
        ci_lo   = float(np.percentile(null_array, 2.5))
        ci_hi   = float(np.percentile(null_array, 97.5))
        p_value = float(np.mean(null_array >= sac_main))

        # SAC across rephrasings
        rephrasing_sacs: list[float] = []
        for r in rephrasings:
            emb_r = self._encoder.embed_section(r, "conclusion")
            rephrasing_sacs.append(float(np.dot(emb_agent, emb_r)))

        return {
            "topic_id":               topic_id,
            "sac":                    sac_main,
            "ci_lo":                  ci_lo,
            "ci_hi":                  ci_hi,
            "p_value":                p_value,
            "above_null":             sac_main > ci_hi,
            "sac_rephrasings":        rephrasing_sacs,
            "sac_rephrasings_mean":   float(np.mean(rephrasing_sacs)) if rephrasing_sacs else None,
        }

    def extract_conclusion_from_report(self, report_md_path: Path) -> str:
        text = report_md_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Find "## Conclusion" or "## Conclusions" header (case-insensitive)
        header_re = re.compile(r"^##\s+conclusions?", re.IGNORECASE)
        section_start: Optional[int] = None
        for i, line in enumerate(lines):
            if header_re.match(line.strip()):
                section_start = i + 1
                break

        if section_start is not None:
            # Collect lines until the next ## header
            body_lines: list[str] = []
            for line in lines[section_start:]:
                if re.match(r"^##", line):
                    break
                body_lines.append(line)

            # Return the first non-empty paragraph
            paragraph = _first_paragraph(body_lines)
            if paragraph:
                return paragraph

        # Fallback: last non-empty paragraph of the whole file
        return _last_paragraph(lines)


def _first_paragraph(lines: list[str]) -> str:
    """Return the first non-blank paragraph from a list of lines."""
    collecting = False
    para: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            collecting = True
            para.append(stripped)
        elif collecting:
            break
    return " ".join(para)


def _last_paragraph(lines: list[str]) -> str:
    """Return the last non-blank paragraph from a list of lines."""
    para: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            para.append(stripped)
        elif para:
            break
    return " ".join(reversed(para))
