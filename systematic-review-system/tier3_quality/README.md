# Tier 3 Quality — PRISMA Visual

Standalone utility for rendering PRISMA 2020 flow diagrams as self-contained SVG strings.

## Why a separate folder?

`tier3_quality/` is intentionally separate from `tier3_synthesis/` for two reasons:

1. **No LLM dependency** — `prisma_visual.py` is pure Python with no external API calls. Keeping it isolated means it can be imported by any pipeline stage (including `main.py` and the frontend) without pulling in the full synthesis stack.
2. **Reusability** — the PRISMA diagram can be regenerated at any point from just a counts dictionary, independent of whether a full synthesis run has completed.

## Module

| File | Purpose |
|---|---|
| `prisma_visual.py` | `render_prisma_svg(counts, exclusion_reasons)` — takes a counts dict (records identified, screened, excluded, included, etc.) and returns a self-contained SVG string implementing the PRISMA 2020 flow diagram standard. |

## Usage

```python
from tier3_quality.prisma_visual import render_prisma_svg

svg = render_prisma_svg(
    counts={
        "records_identified": 1200,
        "duplicates_removed": 143,
        "records_screened": 1057,
        "records_excluded_abstract": 890,
        "records_assessed_fulltext": 167,
        "records_excluded_fulltext": 148,
        "studies_included": 19,
    }
)
# svg is a complete <svg>...</svg> string — embed in HTML or save as .svg
```
