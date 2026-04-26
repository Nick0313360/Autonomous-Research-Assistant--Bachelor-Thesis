"""
main.py
=======
CLI entry point for the Autonomous Systematic Review System.

Usage
-----
    python main.py example_protocol.json
    python main.py path/to/my_protocol.json --review-id my_review_001
    python main.py path/to/my_protocol.json --output-dir data/reports/my_review

The JSON file must represent a ReviewProtocol (see example_protocol.json).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol loading helpers
# ---------------------------------------------------------------------------

def _load_pico(raw: Dict[str, Any]):
    from models.data_classes import PICO
    return PICO(
        population  = raw["population"],
        intervention= raw["intervention"],
        comparator  = raw["comparator"],
        outcome     = raw["outcome"],
        study_design= raw.get("study_design", "randomized controlled trial or observational study"),
    )


def _load_criteria(raw_list: List[Dict[str, Any]]):
    from models.data_classes import Criterion, CriterionType
    criteria = []
    for item in raw_list:
        criterion_type_str = item.get("type", "MANDATORY").upper()
        try:
            ctype = CriterionType[criterion_type_str]
        except KeyError:
            ctype = CriterionType.MANDATORY
        criteria.append(
            Criterion(
                text         = item["text"],
                type         = ctype,
                criterion_id = item.get("criterion_id", ""),
                pico_element = item.get("pico_element"),
            )
        )
    return criteria


def load_protocol(json_path: str):
    """Deserialise a ReviewProtocol from a JSON file."""
    from models.data_classes import ReviewProtocol

    path = Path(json_path)
    if not path.exists():
        logger.error("Protocol file not found: %s", json_path)
        sys.exit(1)

    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    date_range: Optional[tuple[int, int]] = None
    if "date_range" in raw and raw["date_range"]:
        dr = raw["date_range"]
        date_range = (int(dr[0]), int(dr[1]))

    protocol = ReviewProtocol(
        title               = raw["title"],
        research_question   = raw["research_question"],
        pico                = _load_pico(raw["pico"]),
        inclusion_criteria  = _load_criteria(raw.get("inclusion_criteria", [])),
        exclusion_criteria  = _load_criteria(raw.get("exclusion_criteria", [])),
        target_databases    = raw.get("target_databases", []),
        date_range          = date_range,
        language_restrictions = raw.get("language_restrictions", []),
        max_papers_per_db   = int(raw.get("max_papers_per_db", 500)),
    )
    return protocol


# ---------------------------------------------------------------------------
# Main async driver
# ---------------------------------------------------------------------------

async def _run(
    protocol_path: str,
    review_id: str,
    output_dir: str,
) -> None:
    from infrastructure.encoder import SharedEncoderService
    from infrastructure.llm_client import LLMClient
    from orchestrators.main_orchestrator import MainOrchestrator

    logger.info("Loading protocol from: %s", protocol_path)
    protocol = load_protocol(protocol_path)

    logger.info("Protocol: '%s'", protocol.title)
    logger.info("Research question: %s", protocol.research_question)
    logger.info(
        "PICO — P: %s | I: %s | C: %s | O: %s",
        protocol.pico.population,
        protocol.pico.intervention,
        protocol.pico.comparator,
        protocol.pico.outcome,
    )
    logger.info(
        "%d inclusion / %d exclusion criteria",
        len(protocol.inclusion_criteria),
        len(protocol.exclusion_criteria),
    )

    logger.info("Initialising encoder (SPECTER2)…")
    encoder = SharedEncoderService()

    logger.info("Initialising LLM client…")
    llm_client = LLMClient()

    orchestrator = MainOrchestrator(
        encoder    = encoder,
        llm_client = llm_client,
        review_id  = review_id,
        output_dir = output_dir,
    )

    logger.info("Starting full pipeline (review_id=%s)…", review_id)
    result = await orchestrator.run(protocol)

    # Final summary already printed by MainOrchestrator._print_summary
    logger.info(
        "Pipeline complete. Included=%d, Excluded=%d, Uncertain=%d",
        len(result.included),
        len(result.excluded),
        len(result.uncertain),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="systematic-review",
        description="Autonomous Systematic Review System — full pipeline CLI",
    )
    parser.add_argument(
        "protocol",
        metavar="PROTOCOL_JSON",
        help="Path to the review protocol JSON file",
    )
    parser.add_argument(
        "--review-id",
        default=None,
        metavar="ID",
        help=(
            "Unique identifier for this review run "
            "(default: protocol title slug)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="data/reports",
        metavar="DIR",
        help="Base directory for PRISMA reports and review outputs (default: data/reports)",
    )
    return parser.parse_args(argv)


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]


def main(argv=None) -> None:
    args = _parse_args(argv)

    if args.review_id:
        review_id = args.review_id
    else:
        # derive from the protocol title after loading just the title field
        try:
            with open(args.protocol, encoding="utf-8") as fh:
                raw = json.load(fh)
            review_id = _slugify(raw.get("title", "review"))
        except Exception:
            review_id = "review"

    asyncio.run(
        _run(
            protocol_path = args.protocol,
            review_id     = review_id,
            output_dir    = args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
