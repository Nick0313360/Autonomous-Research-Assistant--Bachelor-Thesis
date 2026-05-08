"""
CASCADE-RC Accuracy Diagnostic
Run: python -m cascade_rc.evaluation.accuracy_diagnostic

Checks every guarantee on actual CLEF-TAR 2019 data.
Prints a pass/fail table. Exit code 0 = all pass, 1 = any failure.
"""

import sys
import math
import numpy as np
import pandas as pd
from pathlib import Path


TOPICS = ["CD008874", "CD012080", "CD012768", "CD011768", "CD011975", "CD011145"]
ALPHA  = 0.10
DELTA  = 0.10
DELTA_ETA = 0.03
DELTA_LTT = 0.07
ARTEFACT_DIR = Path("artefacts/cascade_rc")

CHECKS = {
    "Λ̂ has τ_SE>0":      "walker explores self-consistency axis — Λ̂ contains τ_SE > 0 points",
    "FNR ≤ α":            "Theorem 5 — recall certificate valid on held-out test split",
    "|Λ̂| > 0":            "Non-degenerate certificate — walk did not halt at step 0",
    "m+ ≥ N_min":         "Sample size precondition satisfied",
    "η̂⁻⋆ ≥ 0":           "WSR lower bound on coupling slack is non-negative",
    "routing sums to 1":  "Routing fractions sum to 1.0 (sanity check)",
    "WSS finite":         "WSS@95 is a real number (recall target achieved)",
}

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def check_topic(topic_id: str) -> dict:
    parquet_path = ARTEFACT_DIR / "data" / f"{topic_id}.parquet"
    cert_path    = ARTEFACT_DIR / "certificates" / f"{topic_id}.pkl"

    row: dict = {c: "SKIP" for c in CHECKS}
    row["topic_id"]  = topic_id
    row["theta_hat"] = None
    row["FNR"]       = None
    row["WSS"]       = None
    row["Λ_size"]    = None
    row["tau_SE"]    = None
    row["note"]      = ""

    # ── Load data ────────────────────────────────────────────────────────────
    if not parquet_path.exists():
        row["note"] = "parquet missing — run ingest step"
        return row

    df = pd.read_parquet(parquet_path)

    # Require at minimum s, u, y_abstract; is_split and llm_y_hat are optional
    required_cols = {"s", "u", "y_abstract"}
    missing = required_cols - set(df.columns)
    if missing:
        row["note"] = f"missing columns: {missing}"
        return row

    has_split    = "is_split" in df.columns
    has_llm_hat  = "llm_y_hat" in df.columns

    if not has_split:
        row["note"] = "no is_split column — using is_calib as proxy"

    # ── Check m+ ≥ N_min ─────────────────────────────────────────────────────
    nmin = math.ceil(math.log(1 / DELTA_LTT) / (-math.log(1 - ALPHA)))  # ≈ 26
    if has_split:
        df_conf = df[df["is_split"] == 1]
    else:
        df_conf = df[df["is_calib"] == 1] if "is_calib" in df.columns else df
    m_plus = int((df_conf["y_abstract"] == 1).sum())
    row["m+"]    = m_plus
    row["N_min"] = nmin
    row["m+ ≥ N_min"] = "PASS" if m_plus >= nmin else "FAIL"
    if m_plus < nmin:
        row["note"] += f" m+={m_plus} < N_min={nmin} → would abstain"

    # ── Load certificate ─────────────────────────────────────────────────────
    if not cert_path.exists():
        row["note"] += " certificate missing — run calibrate step"
        return row

    import pickle
    with open(cert_path, "rb") as fh:
        cert = pickle.load(fh)

    if cert.status == "abstained":
        row["note"] = "abstained — m+ < N_min at calibration time"
        for c in CHECKS:
            row[c] = "N/A"
        return row

    theta_hat    = cert.theta_hat           # ndarray (3,): (λ_lo, λ_hi, τ_SE)
    lambda_size  = int(cert.lambda_hat_mask.sum())
    eta_lcb_star = float(cert.eta_lcb_grid[cert.lambda_hat_mask].max()) if lambda_size > 0 else float("nan")

    row["theta_hat"] = [round(float(x), 4) for x in theta_hat]
    row["Λ_size"]    = lambda_size
    row["tau_SE"]    = float(theta_hat[2])
    row["eta_lcb"]   = eta_lcb_star

    lam_lo, lam_hi, tau_SE = theta_hat

    # ── Individual checks ────────────────────────────────────────────────────

    # 1. Λ̂ explores τ_SE dimension (at least one certified point has τ_SE > 0)
    #    The optimal θ̂ may land at τ_SE=0 (valid when the λ band is narrow),
    #    but the WALK must have traversed the τ_SE axis.
    cert_tau_max = float(cert.theta_grid[cert.lambda_hat_mask, 2].max()) if lambda_size > 0 else 0.0
    row["cert_tau_max"] = cert_tau_max
    row["Λ̂ has τ_SE>0"] = "PASS" if cert_tau_max > 1e-6 else "FAIL"

    # 2. |Λ̂| > 0
    row["|Λ̂| > 0"] = "PASS" if lambda_size > 0 else "FAIL"

    # 3. η̂⁻⋆ ≥ 0
    row["η̂⁻⋆ ≥ 0"] = "PASS" if (not math.isnan(eta_lcb_star) and eta_lcb_star >= -1e-10) else "FAIL"

    # 4. Routing sums to 1 — use test split if available, else full dataset
    if has_split:
        df_test = df[df["is_split"] == 2].copy()
    else:
        # No split column: use records not used for calibration as a proxy test set
        calib_mask = df["is_calib"] == 1 if "is_calib" in df.columns else pd.Series(False, index=df.index)
        df_test = df[~calib_mask].copy()

    if len(df_test) == 0:
        row["routing sums to 1"] = "N/A (no test rows)"
    else:
        s   = df_test["s"].values
        u   = df_test["u"].values
        esc = (s >= lam_lo) & (s < lam_hi)
        cheap   = (s < lam_lo).mean()
        auto    = (s >= lam_hi).mean()
        llm_f   = (esc & (u >= tau_SE)).mean()
        human   = (esc & (u < tau_SE)).mean()
        total   = cheap + auto + llm_f + human
        row["routing sums to 1"] = "PASS" if abs(total - 1.0) < 1e-6 else f"FAIL ({total:.6f})"

    # 5. FNR ≤ α  (THE CRITICAL ONE)
    if len(df_test) == 0:
        row["FNR ≤ α"] = "N/A (no test rows)"
    else:
        s = df_test["s"].values
        u = df_test["u"].values
        pos_test = df_test[df_test["y_abstract"] == 1].copy()

        if len(pos_test) == 0:
            row["FNR ≤ α"] = "N/A (no test positives)"
        else:
            ps = pos_test["s"].values
            pu = pos_test["u"].values
            esc_mask     = (ps >= lam_lo) & (ps < lam_hi)
            cheap_miss   = ps < lam_lo
            llm_followed = esc_mask & (pu >= tau_SE)

            if has_llm_hat:
                llm_miss = llm_followed & (pos_test["llm_y_hat"].values == 0)
            else:
                llm_miss = llm_followed  # pessimistic

            fnr = float((cheap_miss | llm_miss).mean())
            row["FNR"]    = round(fnr, 4)
            row["FNR ≤ α"] = "PASS" if fnr <= ALPHA + 1e-10 else f"FAIL ({fnr:.4f} > {ALPHA})"

    # 6. WSS@95
    if len(df_test) == 0:
        row["WSS finite"] = "N/A (no test rows)"
    else:
        s = df_test["s"].values
        u = df_test["u"].values
        esc = (s >= lam_lo) & (s < lam_hi)

        if has_llm_hat:
            include = (
                (s >= lam_hi) |
                (esc & (u >= tau_SE) & (df_test["llm_y_hat"].values == 1)) |
                (esc & (u < tau_SE))
            )
        else:
            include = ~(s < lam_lo)  # pessimistic

        y     = df_test["y_abstract"].values
        n_pos = y.sum()
        if n_pos > 0:
            recall = float((y[include] == 1).sum() / n_pos)
            if recall >= 0.95:
                wss = float((~include).sum() / len(df_test) - 0.05)
                row["WSS"]      = round(wss, 4)
                row["WSS finite"] = "PASS"
            else:
                row["WSS"]      = None
                row["WSS finite"] = f"WARN (recall={recall:.3f} < 0.95)"
        else:
            row["WSS finite"] = "N/A"

    return row


def print_diagnostic_table(rows: list[dict]) -> bool:
    all_pass = True

    print(f"\n{'='*80}")
    print(f"  CASCADE-RC ACCURACY DIAGNOSTIC  |  α={ALPHA}  δ={DELTA}  N_min=26")
    print(f"{'='*80}")

    header = f"{'Topic':<12} {'τ_SE':>7} {'|Λ̂|':>6} {'FNR':>7} {'WSS@95':>8} {'m+':>4} | Checks"
    print(f"\n{BOLD}{header}{RESET}")
    print("-" * 80)

    for row in rows:
        tid = row["topic_id"]
        check_vals = [row.get(k, "SKIP") for k in CHECKS]
        has_failures = any(str(v).startswith("FAIL") for v in check_vals)
        all_skipped  = all(v == "SKIP" for v in check_vals)
        if has_failures:
            all_pass = False
        if all_skipped:
            all_pass = False  # no-data topics are not "passing"

        tau_str = f"{row['tau_SE']:.4f}" if row["tau_SE"] is not None else "—"
        lam_str = f"{row['Λ_size']}"     if row["Λ_size"]  is not None else "—"
        fnr_str = f"{row['FNR']:.4f}"    if row["FNR"]     is not None else "—"
        wss_str = f"{row['WSS']:.4f}"    if row["WSS"]     is not None else "—"
        mplus   = str(row.get("m+", "—"))

        if all_skipped:
            status = f"{YELLOW}NO DATA{RESET}"
        elif has_failures:
            status = f"{RED}FAILURES{RESET}"
        elif row.get("note"):
            status = f"{YELLOW}{row['note'][:35]}{RESET}"
        else:
            status = f"{GREEN}ALL PASS{RESET}"

        print(
            f"  {tid:<10} {tau_str:>8} {lam_str:>6} {fnr_str:>7} {wss_str:>8} "
            f"{mplus:>4} | {status}"
        )

    # Detailed failures
    failures = []
    for row in rows:
        for check_name in CHECKS:
            val = row.get(check_name, "SKIP")
            if str(val).startswith("FAIL"):
                failures.append((row["topic_id"], check_name, val))

    # Identify topics with no artefacts at all
    no_data_topics = [r["topic_id"] for r in rows if all(r.get(k, "SKIP") == "SKIP" for k in CHECKS)]
    partial_topics = [r["topic_id"] for r in rows
                      if not all(r.get(k, "SKIP") == "SKIP" for k in CHECKS)
                      and not any(str(r.get(k, "SKIP")).startswith("FAIL") for k in CHECKS)
                      and r.get("Λ_size") is None]

    if failures:
        print(f"\n{RED}{BOLD}FAILURES ({len(failures)} total):{RESET}")
        for tid, check, val in failures:
            print(f"  {RED}✗{RESET} {tid}: [{check}] = {val}")
            print(f"    → {CHECKS[check]}")

    if no_data_topics:
        print(f"\n{YELLOW}NO ARTEFACTS (pipeline not yet run for {len(no_data_topics)} topics):{RESET}")
        for tid in no_data_topics:
            print(f"  {YELLOW}○{RESET} {tid}: parquet missing — run ingest + screen + calibrate")

    if partial_topics:
        print(f"\n{YELLOW}PARTIAL DATA (certificate missing for {len(partial_topics)} topics):{RESET}")
        for tid in partial_topics:
            r = next(rr for rr in rows if rr["topic_id"] == tid)
            print(f"  {YELLOW}○{RESET} {tid}: {r.get('note', 'certificate missing')}")

    if not failures and not no_data_topics and not partial_topics:
        print(f"\n{GREEN}{BOLD}ALL CHECKS PASSED{RESET}")
    elif not failures and (no_data_topics or partial_topics):
        n_full = len(rows) - len(no_data_topics) - len(partial_topics)
        print(f"\n{YELLOW}{BOLD}INCOMPLETE: {n_full}/{len(rows)} topics fully certified, no check failures{RESET}")

    # Key metric summary
    certified = [r for r in rows if r.get("FNR") is not None]
    if certified:
        fnrs = [r["FNR"] for r in certified]
        wsss = [r["WSS"] for r in certified if r.get("WSS") is not None]
        # Count topics where Λ̂ actually explored τ_SE (correct walker-traversal check)
        tau_explored = [r for r in certified if r.get("cert_tau_max", 0.0) > 1e-6]

        print(f"\n{'─'*40}")
        print(f"  Topics certified:     {len(certified)}/{len(rows)}")
        print(f"  Mean FNR:             {np.mean(fnrs):.4f}  (max={max(fnrs):.4f} ≤ α={ALPHA}?  {'✓' if max(fnrs) <= ALPHA else '✗'})")
        if wsss:
            print(f"  Mean WSS@95:          {np.mean(wsss):.4f}")
        else:
            print(f"  WSS@95:               — (recall <0.95 or no test positives)")
        print(f"  Λ̂ τ_SE explored:     {len(tau_explored)}/{len(certified)} topics ({'✓' if len(tau_explored) == len(certified) else '✗ BUG'})")
        print(f"  θ̂ τ_SE values:       " + ", ".join(
            f"{r['tau_SE']:.4f}" for r in certified if r.get("tau_SE") is not None
        ))

    print(f"{'='*80}\n")
    return all_pass


def main() -> None:
    rows = [check_topic(t) for t in TOPICS]
    ok   = print_diagnostic_table(rows)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
