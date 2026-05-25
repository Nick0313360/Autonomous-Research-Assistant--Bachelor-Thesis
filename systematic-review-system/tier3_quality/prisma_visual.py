from __future__ import annotations


def render_prisma_svg(counts: dict, exclusion_reasons: dict = None) -> str:
    """Return a PRISMA 2020 flow diagram as a self-contained SVG string."""
    if exclusion_reasons is None:
        exclusion_reasons = {}

    n_identified    = counts.get("records_identified", 0)
    n_duplicates    = counts.get("duplicates_removed", 0)
    n_screened      = counts.get("records_screened", 0)
    n_exc_abstract  = counts.get("records_excluded_abstract", 0)
    n_not_retrieved = counts.get("records_not_retrieved", 0)
    n_assessed_ft   = counts.get("records_assessed_fulltext", 0)
    n_exc_ft        = counts.get("records_excluded_fulltext", 0)
    n_included      = counts.get("studies_included", 0)
    query_versions  = counts.get("query_versions", [])

    # Search iteration summary line for box 1
    n_iterations = len(query_versions) if query_versions else None
    iter_line = (
        f"({n_iterations} search iteration{'s' if n_iterations != 1 else ''})"
        if n_iterations else ""
    )

    # ── exclusion reasons block (side C) ──────────────────────────────────
    reason_items  = list(exclusion_reasons.items())[:6]
    # Each reason on its own line, truncated to fit
    reason_lines: list[str] = []
    reason_y0 = 553
    for i, (reason, cnt) in enumerate(reason_items):
        label = (reason[:34] + "…") if len(reason) > 34 else reason
        y = reason_y0 + i * 14
        reason_lines.append(
            f'  <text x="535" y="{y}" font-family="sans-serif" font-size="9" '
            f'text-anchor="middle" fill="#555">{label}: {cnt}</text>'
        )
    reasons_svg = "\n".join(reason_lines)

    # Side-C box grows to fit content: base covers not-retrieved + excluded + reasons
    side_c_base_h = 120
    side_c_h = side_c_base_h + max(0, len(reason_items) - 1) * 14

    # ── rotated phase-label helper ─────────────────────────────────────────
    def phase_label(cx: int, cy: int, text: str) -> str:
        return (
            f'<text transform="rotate(-90,{cx},{cy})" x="{cx}" y="{cy}" '
            f'font-family="sans-serif" font-size="9" fill="#bbb" '
            f'text-anchor="middle">{text}</text>'
        )

    total_h = 780 + max(0, len(reason_items) - 1) * 14

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="700" height="{total_h}">',

        # arrowhead marker
        "  <defs>",
        '    <marker id="arr" markerWidth="8" markerHeight="6" '
        'refX="7" refY="3" orient="auto">',
        '      <path d="M0,0 L0,6 L8,3 z" fill="#333"/>',
        "    </marker>",
        "  </defs>",

        f'  <rect width="700" height="{total_h}" fill="#fafafa"/>',

        # phase labels
        f"  {phase_label(12, 67,  'IDENTIFICATION')}",
        f"  {phase_label(12, 242, 'SCREENING')}",
        f"  {phase_label(12, 490, 'ELIGIBILITY')}",
        f"  {phase_label(12, 720, 'INCLUDED')}",

        # ── BOX 1: Records identified ─────────────────────────────────────
        '  <rect x="20" y="20" width="300" height="95" rx="3" '
        'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="170" y="44" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">Records identified through</text>',
        f'  <text x="170" y="60" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">database searching</text>',
        f'  <text x="170" y="78" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle">(n = {n_identified})</text>',
        *(
            [f'  <text x="170" y="96" font-family="sans-serif" font-size="10" '
             f'text-anchor="middle" fill="#888">{iter_line}</text>']
            if iter_line else []
        ),

        # ── BOX 2: Records screened ───────────────────────────────────────
        '  <rect x="20" y="205" width="300" height="75" rx="3" '
        'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="170" y="230" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">Records screened</text>',
        f'  <text x="170" y="248" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle">(n = {n_screened})</text>',
        f'  <text x="170" y="266" font-family="sans-serif" font-size="10" '
        f'text-anchor="middle" fill="#666">after removing {n_duplicates} duplicates</text>',

        # ── BOX 3: Full texts assessed ────────────────────────────────────
        '  <rect x="20" y="455" width="300" height="75" rx="3" '
        'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="170" y="481" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">Full-text articles assessed</text>',
        f'  <text x="170" y="497" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">for eligibility</text>',
        f'  <text x="170" y="515" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle">(n = {n_assessed_ft})</text>',

        # ── BOX 4: Studies included ───────────────────────────────────────
        f'  <rect x="20" y="{total_h - 115}" width="300" height="75" rx="3" '
        f'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="170" y="{total_h - 91}" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">Studies included in</text>',
        f'  <text x="170" y="{total_h - 75}" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">qualitative synthesis</text>',
        f'  <text x="170" y="{total_h - 57}" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle">(n = {n_included})</text>',

        # ── DOWN ARROWS (main column) ─────────────────────────────────────
        '  <line x1="170" y1="115" x2="170" y2="203" stroke="#333" '
        'stroke-width="1.5" marker-end="url(#arr)"/>',
        '  <line x1="170" y1="280" x2="170" y2="453" stroke="#333" '
        'stroke-width="1.5" marker-end="url(#arr)"/>',
        f'  <line x1="170" y1="530" x2="170" y2="{total_h - 117}" stroke="#333" '
        f'stroke-width="1.5" marker-end="url(#arr)"/>',

        # ── SIDE A: Duplicates removed (aligned with Box 1) ───────────────
        '  <rect x="400" y="35" width="270" height="50" rx="3" '
        'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="535" y="55" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">Duplicates removed</text>',
        f'  <text x="535" y="73" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle">(n = {n_duplicates})</text>',
        '  <line x1="320" y1="67" x2="398" y2="67" stroke="#333" '
        'stroke-width="1.5" marker-end="url(#arr)"/>',

        # ── SIDE B: Records excluded at abstract (aligned with Box 2) ─────
        '  <rect x="400" y="218" width="270" height="50" rx="3" '
        'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="535" y="238" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle" font-weight="bold">Records excluded</text>',
        f'  <text x="535" y="256" font-family="sans-serif" font-size="12" '
        f'text-anchor="middle">(n = {n_exc_abstract})</text>',
        '  <line x1="320" y1="242" x2="398" y2="242" stroke="#333" '
        'stroke-width="1.5" marker-end="url(#arr)"/>',

        # ── SIDE C: Not retrieved + excluded FT (aligned with Box 3) ──────
        f'  <rect x="400" y="450" width="270" height="{side_c_h}" rx="3" '
        f'fill="white" stroke="#333" stroke-width="1"/>',
        f'  <text x="535" y="470" font-family="sans-serif" font-size="11" '
        f'text-anchor="middle" font-weight="bold">Full texts not retrieved</text>',
        f'  <text x="535" y="486" font-family="sans-serif" font-size="11" '
        f'text-anchor="middle">(n = {n_not_retrieved})</text>',
        '  <line x1="410" y1="496" x2="660" y2="496" stroke="#ddd" stroke-width="1"/>',
        f'  <text x="535" y="512" font-family="sans-serif" font-size="11" '
        f'text-anchor="middle" font-weight="bold">Full texts excluded</text>',
        f'  <text x="535" y="528" font-family="sans-serif" font-size="11" '
        f'text-anchor="middle">(n = {n_exc_ft})</text>',
    ]

    if reason_items:
        parts.append(
            '  <text x="535" y="543" font-family="sans-serif" font-size="10" '
            'text-anchor="middle" fill="#555">Reasons:</text>'
        )
        parts.append(reasons_svg)

    parts.extend([
        '  <line x1="320" y1="492" x2="398" y2="492" stroke="#333" '
        'stroke-width="1.5" marker-end="url(#arr)"/>',
        "",
        "</svg>",
    ])

    return "\n".join(parts)
