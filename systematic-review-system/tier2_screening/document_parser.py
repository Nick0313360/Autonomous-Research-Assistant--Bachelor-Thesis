"""
tier2_screening/document_parser.py
=====================================
Parses a retrieved full-text document into a StructuredDocument.

Supports two input formats
--------------------------
PDF   — pdfminer.six extracts raw text; section boundaries are detected
        with a regex over common academic section headers.
XML   — lxml parses JATS-format XML (Europe PMC / PubMed Central);
        sections are extracted by <abstract>, <sec sec-type="...">, and
        child <title> elements.

Parsing quality score
---------------------
1.0   METHODS and RESULTS sections both found
0.5   only one of them found
0.2   neither found (flagged as low quality)

Section embeddings are computed (via encoder.embed_section) for
METHODS, RESULTS, and DISCUSSION sections when present.

Token count is approximated as word_count / 0.75.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from models.data_classes import RetrievalResult, SectionLabel, StructuredDocument

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section header → SectionLabel mapping
# ---------------------------------------------------------------------------

_LABEL_MAP: Dict[str, SectionLabel] = {
    "abstract":                SectionLabel.ABSTRACT,
    "introduction":            SectionLabel.INTRODUCTION,
    "background":              SectionLabel.INTRODUCTION,
    "method":                  SectionLabel.METHODS,
    "methods":                 SectionLabel.METHODS,
    "methodology":             SectionLabel.METHODS,
    "materials and method":    SectionLabel.METHODS,
    "materials and methods":   SectionLabel.METHODS,
    "material and methods":    SectionLabel.METHODS,
    "result":                  SectionLabel.RESULTS,
    "results":                 SectionLabel.RESULTS,
    "finding":                 SectionLabel.RESULTS,
    "findings":                SectionLabel.RESULTS,
    "discussion":              SectionLabel.DISCUSSION,
    "conclusion":              SectionLabel.CONCLUSION,
    "conclusions":             SectionLabel.CONCLUSION,
    "references":              SectionLabel.REFERENCES,
    "bibliography":            SectionLabel.REFERENCES,
}

# Regex that matches common section-header lines in extracted PDF text.
# Captured group 1 is the header text (possibly multi-word).
_SECTION_RE = re.compile(
    r"(?:^|\n)[ \t]*"
    r"(Abstract|Introduction|Background|"
    r"Methods?|Materials?\s+and\s+Methods?|Methodology|"
    r"Results?|Findings?|"
    r"Discussion|"
    r"Conclusions?|"
    r"References?|Bibliography)"
    r"[ \t]*(?:\n|$)",
    re.IGNORECASE,
)

# XML sec-type values → SectionLabel
_XML_SECTYPE_MAP: Dict[str, SectionLabel] = {
    "abstract":      SectionLabel.ABSTRACT,
    "intro":         SectionLabel.INTRODUCTION,
    "introduction":  SectionLabel.INTRODUCTION,
    "methods":       SectionLabel.METHODS,
    "method":        SectionLabel.METHODS,
    "materials":     SectionLabel.METHODS,
    "results":       SectionLabel.RESULTS,
    "result":        SectionLabel.RESULTS,
    "discussion":    SectionLabel.DISCUSSION,
    "conclusions":   SectionLabel.CONCLUSION,
    "conclusion":    SectionLabel.CONCLUSION,
    "references":    SectionLabel.REFERENCES,
    "ref-list":      SectionLabel.REFERENCES,
}

# Sections for which embeddings are computed
_EMBED_SECTIONS = (SectionLabel.METHODS, SectionLabel.RESULTS, SectionLabel.DISCUSSION)


class DocumentParser:
    """
    Parses a retrieved document into a StructuredDocument.

    Usage
    -----
    parser = DocumentParser()
    doc    = parser.parse(retrieval_result, encoder)
    """

    def parse(
        self,
        retrieval_result: RetrievalResult,
        encoder,           # SharedEncoderService
    ) -> StructuredDocument:
        """
        Parse the document referenced by *retrieval_result*.

        Parameters
        ----------
        retrieval_result : RetrievalResult
            Must have either xml_path or pdf_path set.
        encoder :
            SharedEncoderService with embed_section(text, label) → np.ndarray.

        Returns
        -------
        StructuredDocument
        """
        if retrieval_result.xml_path:
            sections = self._parse_xml(retrieval_result.xml_path)
            fmt = "xml"
        elif retrieval_result.pdf_path:
            sections = self._parse_pdf(retrieval_result.pdf_path)
            fmt = "pdf"
        else:
            raise ValueError(
                f"RetrievalResult for {retrieval_result.record_id} "
                "has no pdf_path or xml_path"
            )

        return self._build_document(
            record_id = retrieval_result.record_id,
            sections  = sections,
            encoder   = encoder,
            fmt       = fmt,
        )

    # ------------------------------------------------------------------
    # PDF parsing
    # ------------------------------------------------------------------

    def _parse_pdf(self, pdf_path: str) -> Dict[SectionLabel, str]:
        from pdfminer.high_level import extract_text  # deferred: not needed for XML path

        try:
            raw_text = extract_text(pdf_path)
        except Exception as exc:
            logger.warning("DocumentParser: pdfminer failed on %s: %s", pdf_path, exc)
            return {}

        return self._split_text_sections(raw_text)

    def _split_text_sections(self, text: str) -> Dict[SectionLabel, str]:
        """
        Split raw text into sections using header-regex matching.

        The text before the first recognised header is labelled OTHER.
        Consecutive matches for the same SectionLabel are concatenated.
        """
        matches: List[Tuple[int, int, SectionLabel]] = []
        for m in _SECTION_RE.finditer(text):
            header_raw = m.group(1).strip().lower()
            # Normalise "materials  and  methods" etc.
            header_norm = re.sub(r"\s+", " ", header_raw)
            label = _LABEL_MAP.get(header_norm, SectionLabel.OTHER)
            matches.append((m.start(), m.end(), label))

        sections: Dict[SectionLabel, str] = {}

        if not matches:
            # No headers found — treat everything as OTHER
            if text.strip():
                sections[SectionLabel.OTHER] = text.strip()
            return sections

        # Text before first header → OTHER
        pre = text[: matches[0][0]].strip()
        if pre:
            sections[SectionLabel.OTHER] = pre

        for i, (start, end, label) in enumerate(matches):
            # Content runs from end-of-header to start-of-next-header (or EOF)
            next_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)
            chunk = text[end:next_start].strip()
            if chunk:
                existing = sections.get(label, "")
                sections[label] = (existing + "\n\n" + chunk).strip() if existing else chunk

        return sections

    # ------------------------------------------------------------------
    # XML parsing (JATS format — Europe PMC / PubMed Central)
    # ------------------------------------------------------------------

    def _parse_xml(self, xml_path: str) -> Dict[SectionLabel, str]:
        try:
            from lxml import etree
        except ImportError:
            logger.error("DocumentParser: lxml is required for XML parsing")
            return {}

        try:
            tree = etree.parse(xml_path)
        except Exception as exc:
            logger.warning("DocumentParser: lxml failed on %s: %s", xml_path, exc)
            return {}

        root = tree.getroot()
        sections: Dict[SectionLabel, str] = {}

        # --- Abstract ----------------------------------------------------
        abstract_text = self._xml_abstract_text(root)
        if abstract_text:
            sections[SectionLabel.ABSTRACT] = abstract_text

        # --- Body sections -----------------------------------------------
        for sec in root.iter("{*}sec"):
            label = self._classify_xml_sec(sec)
            if label is None:
                continue
            content = self._xml_element_text(sec)
            if not content:
                continue
            existing = sections.get(label, "")
            sections[label] = (existing + "\n\n" + content).strip() if existing else content

        return sections

    @staticmethod
    def _xml_abstract_text(root) -> Optional[str]:
        """Extract text from <abstract> elements."""
        texts: List[str] = []
        for elem in root.iter("{*}abstract"):
            t = DocumentParser._xml_element_text(elem)
            if t:
                texts.append(t)
        return "\n\n".join(texts).strip() or None

    @staticmethod
    def _classify_xml_sec(sec_elem) -> Optional[SectionLabel]:
        """Map a <sec> element to a SectionLabel."""
        # 1. sec-type attribute
        sec_type = sec_elem.get("sec-type", "").lower().strip()
        if sec_type in _XML_SECTYPE_MAP:
            return _XML_SECTYPE_MAP[sec_type]

        # 2. First <title> child text
        for child in sec_elem:
            local = child.tag.split("}")[-1].lower() if "}" in child.tag else child.tag.lower()
            if local == "title" and child.text:
                title_norm = re.sub(r"\s+", " ", child.text.strip().lower())
                label = _LABEL_MAP.get(title_norm)
                if label:
                    return label
                # Partial match: check if any key is a prefix/suffix
                for key, lbl in _LABEL_MAP.items():
                    if key in title_norm:
                        return lbl
            break  # only inspect the first child

        return None

    @staticmethod
    def _xml_element_text(elem) -> str:
        """Recursively concatenate all text content of an element."""
        parts: List[str] = []
        if elem.text:
            parts.append(elem.text.strip())
        for child in elem:
            t = DocumentParser._xml_element_text(child)
            if t:
                parts.append(t)
            if child.tail:
                parts.append(child.tail.strip())
        return " ".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Build StructuredDocument
    # ------------------------------------------------------------------

    @staticmethod
    def _build_document(
        record_id: str,
        sections:  Dict[SectionLabel, str],
        encoder,
        fmt:       str,
    ) -> StructuredDocument:
        has_methods = SectionLabel.METHODS  in sections
        has_results = SectionLabel.RESULTS  in sections

        if has_methods and has_results:
            quality = 1.0
        elif has_methods or has_results:
            quality = 0.5
        else:
            quality = 0.2
            logger.warning(
                "DocumentParser: low parsing quality for %s "
                "(no METHODS or RESULTS section found, format=%s)",
                record_id, fmt,
            )

        # Approximate token count
        total_words = sum(len(text.split()) for text in sections.values())
        token_count = int(total_words / 0.75)

        # Embeddings for key sections
        section_embeddings: Dict[str, List[float]] = {}
        for label in _EMBED_SECTIONS:
            if label in sections:
                try:
                    emb = encoder.embed_section(sections[label], label)
                    section_embeddings[label.value] = emb.tolist()
                except Exception as exc:
                    logger.warning(
                        "DocumentParser: embed_section failed for %s/%s: %s",
                        record_id, label.value, exc,
                    )

        return StructuredDocument(
            record_id              = record_id,
            sections               = {k.value: v for k, v in sections.items()},
            section_embeddings     = section_embeddings,
            parsing_quality_score  = quality,
            token_count            = token_count,
            source_format          = fmt,
        )
