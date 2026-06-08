"""
Print two LaTeX tables from bench run_stats.json and sac_results.json.

Expected file layout (relative to repo root):
  data/reports/<TOPIC>_bench_v1/run_stats.json   — one per topic
  data/sac_results.json                           — combined SAC scores

run_stats.json schema:
  {
    "topic_id":   str,        # e.g. "CD008874"
    "n_records":  int,        # total records screened
    "m_plus":     int,        # number of relevant records
    "wss_95":     float,      # -0.05 sentinel = recall target not met
    "runtime_h":  float,      # wall-clock hours
    "cost_usd":   float       # USD cost of LLM calls
  }

sac_results.json schema — either a list:
  [{"topic_id": str, "sac": float, "ci_lo": float, "ci_hi": float,
    "above_null": bool, ...}, ...]
or a dict keyed by topic_id:
  {"CD008874": {"sac": float, "ci_lo": float, "ci_hi": float,
                "above_null": bool, ...}, ...}
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "data" / "reports"
SAC_FILE = REPO_ROOT / "data" / "sac_results.json"

SENTINEL = -0.05
TOPIC_ORDER = [
    "CD008874", "CD011145", "CD011768",
    "CD011975", "CD012080", "CD012768",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt(value: Any, decimals: int = 3) -> str:
    if value is None:
        return r"\na"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return r"\na"
        if abs(value - SENTINEL) < 1e-9:
            return r"---"
    return f"{value:.{decimals}f}"


def _fmt_wss(value: Any) -> str:
    if value is None:
        return r"---"
    if isinstance(value, float) and (math.isnan(value) or abs(value - SENTINEL) < 1e-9):
        return r"---"
    return f"{value:.3f}"


def _fmt_bool(value: Any) -> str:
    if value is None:
        return r"\na"
    return "Yes" if value else "No"


def _load_run_stats() -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for path in REPORTS_DIR.glob("*_bench_v1/run_stats.json"):
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        tid = data.get("topic_id") or path.parent.name.split("_bench_v1")[0]
        stats[tid] = data
    return stats


def _load_sac() -> dict[str, dict]:
    if not SAC_FILE.exists():
        return {}
    with SAC_FILE.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, list):
        return {r["topic_id"]: r for r in raw}
    # already a dict keyed by topic_id
    return raw


def _mean_row(rows: list[dict], key: str) -> str:
    vals = [r[key] for r in rows if r.get(key) is not None
            and not (isinstance(r[key], float) and math.isnan(r[key]))
            and not (isinstance(r[key], float) and abs(r[key] - SENTINEL) < 1e-9)]
    if not vals:
        return r"\na"
    return f"{sum(vals)/len(vals):.3f}"


def _mean_int(rows: list[dict], key: str) -> str:
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))
            and not math.isnan(float(r[key]))]
    if not vals:
        return r"\na"
    return f"{round(sum(vals)/len(vals))}"


# ── TABLE 1 (AGENTICS paper) ──────────────────────────────────────────────────
#   Topic | Records | m+ | WSS@95 | SAC | Runtime(h) | Cost(USD)

def build_table1(run_stats: dict[str, dict], sac: dict[str, dict]) -> str:
    col_spec = "l r r r r r r"
    header = (
        r"  \hline" + "\n"
        r"  Topic & Records & $m^+$ & WSS@95 & SAC & Runtime (h) & Cost (USD) \\" + "\n"
        r"  \hline"
    )

    data_rows: list[dict] = []
    body_lines: list[str] = []

    for tid in TOPIC_ORDER:
        rs = run_stats.get(tid, {})
        sc = sac.get(tid, {})

        n_rec   = rs.get("n_records")
        m_plus  = rs.get("m_plus")
        wss     = rs.get("wss_95")
        sac_val = sc.get("sac")
        rt      = rs.get("runtime_h")
        cost    = rs.get("cost_usd")

        n_rec_s  = str(n_rec)  if isinstance(n_rec,  int) else (r"\na" if n_rec  is None else f"{n_rec:.0f}")
        m_plus_s = str(m_plus) if isinstance(m_plus, int) else (r"\na" if m_plus is None else f"{m_plus:.0f}")
        wss_s    = _fmt_wss(wss)
        sac_s    = _fmt(sac_val)
        rt_s     = _fmt(rt)
        cost_s   = _fmt(cost)

        body_lines.append(
            f"  {tid} & {n_rec_s} & {m_plus_s} & {wss_s} & {sac_s} & {rt_s} & {cost_s} \\\\"
        )
        data_rows.append({
            "wss_95":     wss,
            "sac":        sac_val,
            "runtime_h":  rt,
            "cost_usd":   cost,
            "n_records":  n_rec,
            "m_plus":     m_plus,
        })

    mean_n   = _mean_int(data_rows, "n_records")
    mean_mp  = _mean_int(data_rows, "m_plus")
    mean_wss = _mean_row(data_rows, "wss_95")
    mean_sac = _mean_row(data_rows, "sac")
    mean_rt  = _mean_row(data_rows, "runtime_h")
    mean_cost = _mean_row(data_rows, "cost_usd")

    mean_line = (
        f"  \\hline\n"
        f"  Mean & {mean_n} & {mean_mp} & {mean_wss} & {mean_sac} & {mean_rt} & {mean_cost} \\\\"
    )

    return "\n".join([
        r"\begin{table}[ht]",
        r"\centering",
        r"\caption{Benchmark results per topic (AGENTICS)}",
        r"\label{tab:agentics-results}",
        rf"\begin{{tabular}}{{{col_spec}}}",
        header,
        "\n".join(body_lines),
        mean_line,
        r"  \hline",
        r"\end{tabular}",
        r"\end{table}",
    ])


# ── TABLE 2 (BIBM paper) ──────────────────────────────────────────────────────
#   Topic | SAC | SAC_CI_lo | SAC_CI_hi | above_null | WSS@95

def build_table2(run_stats: dict[str, dict], sac: dict[str, dict]) -> str:
    col_spec = "l r r r c r"
    header = (
        r"  \hline" + "\n"
        r"  Topic & SAC & CI$_{lo}$ & CI$_{hi}$ & Above null & WSS@95 \\" + "\n"
        r"  \hline"
    )

    body_lines: list[str] = []
    for tid in TOPIC_ORDER:
        sc  = sac.get(tid, {})
        rs  = run_stats.get(tid, {})

        sac_val  = sc.get("sac")
        ci_lo    = sc.get("ci_lo")
        ci_hi    = sc.get("ci_hi")
        above    = sc.get("above_null")
        wss      = rs.get("wss_95")

        body_lines.append(
            f"  {tid} & {_fmt(sac_val)} & {_fmt(ci_lo)} & {_fmt(ci_hi)} "
            f"& {_fmt_bool(above)} & {_fmt_wss(wss)} \\\\"
        )

    return "\n".join([
        r"\begin{table}[ht]",
        r"\centering",
        r"\caption{SAC scores and WSS@95 per topic (BIBM)}",
        r"\label{tab:bibm-sac}",
        rf"\begin{{tabular}}{{{col_spec}}}",
        header,
        "\n".join(body_lines),
        r"  \hline",
        r"\end{tabular}",
        r"\end{table}",
    ])


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    run_stats = _load_run_stats()
    sac = _load_sac()

    missing = [t for t in TOPIC_ORDER if t not in run_stats]
    if missing:
        print(f"[warn] no run_stats.json found for: {', '.join(missing)}")

    print("% ═══════════════════════════════════════")
    print("% TABLE 1 — AGENTICS paper")
    print("% ═══════════════════════════════════════")
    print(build_table1(run_stats, sac))
    print()
    print("% ═══════════════════════════════════════")
    print("% TABLE 2 — BIBM paper")
    print("% ═══════════════════════════════════════")
    print(build_table2(run_stats, sac))


if __name__ == "__main__":
    main()
