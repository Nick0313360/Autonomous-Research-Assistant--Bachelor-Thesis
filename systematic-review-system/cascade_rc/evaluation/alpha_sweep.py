"""
Alpha sweep for Figure 1: runs Algorithm 1 at multiple α values.
LLM calls are fully cached; only the calibration step (Algorithm 1) re-runs.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


ALPHA_SWEEP = [0.01, 0.02, 0.05, 0.10, 0.15, 0.20]

# Hoeffding-Bentkus bounds are mathematically unable to certify α < 0.05
# without abstaining when the conformal-calib positives fall below this count.
_MIN_M_PLUS_STRICT_ALPHA = 50

_DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]


# ---------------------------------------------------------------------------
# CASCADE-RC sweep
# ---------------------------------------------------------------------------

def run_alpha_sweep(
    topic_ids: list[str],
    artefact_dir: Path,
    delta_total: float = 0.10,
    delta_eta: float = 0.03,
    alpha_values: list[float] = ALPHA_SWEEP,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Re-run Algorithm 1 at each alpha in alpha_values for each topic.

    IMPORTANT: Do NOT reuse θ̂ from one α for another α.
    Each (topic, α) pair gets an independent calibration run.

    Returns a DataFrame with columns:
      topic_id, alpha, delta_ltt, fnr_test, wss_95, frac_human_review,
      lambda_hat_size, eta_lcb_star, alpha_dagger, theta_hat_tau_SE,
      m_plus, nmin, status.
    """
    from cascade_rc.calibration.main_calibrate import run_calibration
    from cascade_rc.evaluation.metrics import compute_nmin, evaluate_certificate, _ensure_is_split

    records: list[dict] = []

    for alpha in alpha_values:
        delta_ltt = delta_total - delta_eta
        nmin = compute_nmin(alpha, delta_ltt)
        print(f"\n{'='*60}")
        print(f"Alpha sweep: α={alpha:.2f}, N_min={nmin}")
        print(f"{'='*60}")

        for topic_id in topic_ids:
            parquet_path = artefact_dir / "data" / f"{topic_id}.parquet"
            if not parquet_path.exists():
                print(f"  SKIP {topic_id}: parquet not found")
                continue

            df = pd.read_parquet(parquet_path)
            df = _ensure_is_split(df)

            df_pos = df[(df["is_split"] == 1) & (df["y_abstract"] == 1)]
            m_plus = len(df_pos)

            # Early-ABSTAIN: for α < 0.05 the HB p-value denominator grows so
            # fast that fewer than _MIN_M_PLUS_STRICT_ALPHA positives cannot
            # produce a valid certificate — skip the expensive LTT walk entirely.
            if alpha < 0.05 and m_plus < _MIN_M_PLUS_STRICT_ALPHA:
                reason = (
                    f"m_plus={m_plus} < MIN_M_PLUS={_MIN_M_PLUS_STRICT_ALPHA} "
                    f"for α={alpha:.2f} (HB bounds too loose)"
                )
                print(f"  ABSTAIN {topic_id}: {reason}")
                records.append({
                    "topic_id": topic_id,
                    "alpha": alpha,
                    "status": "ABSTAIN",
                    "m_plus": m_plus,
                    "nmin": nmin,
                    "abstain_reason": reason,
                })
                continue

            if m_plus < nmin:
                print(f"  ABSTAIN {topic_id}: m+={m_plus} < N_min={nmin} at α={alpha}")
                records.append({
                    "topic_id": topic_id,
                    "alpha": alpha,
                    "status": "ABSTAIN",
                    "m_plus": m_plus,
                    "nmin": nmin,
                })
                continue

            result = run_calibration(
                df=df,
                topic_id=topic_id,
                alpha=alpha,
                delta_eta=delta_eta,
                delta_ltt=delta_ltt,
                artefact_dir=artefact_dir,
                save_certificate=False,
            )

            if result["status"] == "certified":
                eval_result = evaluate_certificate(
                    df=df,
                    theta_hat=result["theta_hat"],
                    alpha=alpha,
                )
                records.append({
                    "topic_id": topic_id,
                    "alpha": alpha,
                    "delta_ltt": delta_ltt,
                    "status": "certified",
                    "m_plus": m_plus,
                    "nmin": nmin,
                    "fnr_test": eval_result["fnr_test"],
                    "wss_95": eval_result["wss_95"],
                    "frac_human_review": eval_result["frac_human_review"],
                    "lambda_hat_size": result["lambda_hat_size"],
                    "eta_lcb_star": result["eta_lcb_star"],
                    "alpha_dagger": result["alpha_dagger"],
                    "theta_hat_tau_SE": float(result["theta_hat"][2]),
                })
                print(
                    f"  {topic_id} α={alpha:.2f}: "
                    f"FNR={eval_result['fnr_test']:.4f} "
                    f"WSS@95={eval_result['wss_95']:.4f} "
                    f"τ_SE={result['theta_hat'][2]:.4f}"
                )
            else:
                print(f"  {topic_id} α={alpha:.2f}: {result['status']}")
                records.append({"topic_id": topic_id, "alpha": alpha, **result})

    df_results = pd.DataFrame(records)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df_results.to_parquet(output_path, index=False)
        print(f"\nAlpha sweep results saved to {output_path}")

    return df_results


def validate_theorem5(df_sweep: pd.DataFrame, alpha_col: str = "alpha") -> dict:
    """Validate that CASCADE-RC FNR <= alpha at every (topic, alpha) pair.

    Returns {'violations': list, 'pass_rate': float, 'theorem5_holds': bool}.
    """
    certified = df_sweep[df_sweep.get("status", pd.Series(dtype=str)) == "certified"].copy() \
        if "status" in df_sweep.columns else pd.DataFrame()

    if certified.empty or "fnr_test" not in certified.columns:
        return {
            "total_certified": 0,
            "violations": [],
            "pass_rate": float("nan"),
            "theorem5_holds": True,
        }

    violations = certified[certified["fnr_test"] > certified[alpha_col]]
    return {
        "total_certified": len(certified),
        "violations": violations[["topic_id", alpha_col, "fnr_test"]].to_dict("records"),
        "pass_rate": 1.0 - len(violations) / max(len(certified), 1),
        "theorem5_holds": len(violations) == 0,
    }


# ---------------------------------------------------------------------------
# Baseline helpers (Task 4)
# ---------------------------------------------------------------------------

def _ensure_is_split_local(df: pd.DataFrame) -> pd.DataFrame:
    if "is_split" in df.columns:
        return df
    if "is_calib" in df.columns:
        df = df.copy()
        df["is_split"] = df["is_calib"].map({1: 1, 0: 2}).astype("int8")
    return df


def _scrc_fnr_at_alpha(df: pd.DataFrame, alpha: float, variant: str) -> float:
    """SCRC-T or SCRC-I FNR on the test split (is_split==2) at recall=1-alpha."""
    try:
        from cascade_rc.baselines.scrc import SCRC
    except ImportError:
        return float("nan")

    df = _ensure_is_split_local(df)
    cal = df[df["is_split"] == 1]
    test = df[df["is_split"] == 2]

    if len(cal) == 0 or len(test) == 0:
        return float("nan")

    scrc = SCRC(variant=variant, alpha=alpha, abstain_rate=0.1)
    scrc.fit(
        cal["s"].to_numpy(dtype=np.float64),
        cal["u"].to_numpy(dtype=np.float64),
        cal["y_abstract"].to_numpy(dtype=np.int64),
    )
    decisions = scrc.predict(
        test["s"].to_numpy(dtype=np.float64),
        test["u"].to_numpy(dtype=np.float64),
    )

    predictions = (decisions == "accept").astype(np.int8)
    y_true = test["y_abstract"].to_numpy(dtype=np.int8)
    n_pos = int(np.sum(y_true == 1))
    if n_pos == 0:
        return float("nan")
    fn = int(np.sum((predictions == 0) & (y_true == 1)))
    return float(fn / n_pos)


def _autostop_fnr_at_alpha(
    df: pd.DataFrame,
    topic_id: str,
    alpha: float,
    data_dir: Path,
) -> float:
    """AUTOSTOP FNR on the test split at stopping_recall=1-alpha."""
    try:
        from cascade_rc.baselines.run_autostop import _run_one
    except ImportError:
        return float("nan")

    df = _ensure_is_split_local(df)
    df_test = df[df["is_split"] == 2].reset_index(drop=True)
    if len(df_test) == 0:
        return float("nan")

    recall_target = 1.0 - alpha
    try:
        result = _run_one(topic_id, df_test, recall_target, data_dir)
        recall = result.get("recall_achieved", float("nan"))
        if isinstance(recall, float) and math.isnan(recall):
            return float("nan")
        return float(1.0 - recall)
    except Exception as exc:
        print(f"  AUTOSTOP error {topic_id} α={alpha:.2f}: {exc}")
        return float("nan")


def _rlstop_fnr_at_alpha(
    df: pd.DataFrame,
    topic_id: str,
    alpha: float,
    data_dir: Path,
    train_dir: Path,
) -> float:
    """RLStop FNR on the test split at target_recall=1-alpha.

    Requires pre-trained PPO model at train_dir/recall_<1-alpha:.2f>.zip.
    Returns nan if the model file is missing or stable_baselines3 is unavailable.
    """
    try:
        from stable_baselines3 import PPO
        from cascade_rc.baselines.run_rlstop import _infer_one
    except ImportError:
        return float("nan")

    df = _ensure_is_split_local(df)
    df_test = df[df["is_split"] == 2].reset_index(drop=True)
    if len(df_test) == 0:
        return float("nan")

    recall_target = 1.0 - alpha
    cache_path = train_dir / f"recall_{recall_target:.2f}.zip"
    if not cache_path.exists():
        return float("nan")

    try:
        model = PPO.load(str(cache_path))
        result = _infer_one(topic_id, df_test, recall_target, model, data_dir)
        recall = result.get("recall_achieved", float("nan"))
        if isinstance(recall, float) and math.isnan(recall):
            return float("nan")
        return float(1.0 - recall)
    except Exception as exc:
        print(f"  RLStop error {topic_id} α={alpha:.2f}: {exc}")
        return float("nan")


def _uncalibrated_fnr(df: pd.DataFrame) -> float:
    """θ=(0,0,0.5): λ_hi=0 → all docs auto-accepted → FNR=0."""
    return 0.0


def augment_with_baselines(
    df_sweep: pd.DataFrame,
    artefact_dir: Path,
    data_dir: Path = Path("data/clef_tar"),
    train_dir: Path = Path("artefacts/baselines/rlstop"),
) -> pd.DataFrame:
    """Add baseline FNR columns to the alpha sweep results DataFrame.

    Adds columns: autostop_fnr, scrc_t_fnr, scrc_i_fnr, rlstop_fnr, uncalibrated_fnr.
    """
    topic_dfs: dict[str, pd.DataFrame] = {}
    for topic_id in df_sweep["topic_id"].unique():
        p = artefact_dir / "data" / f"{topic_id}.parquet"
        if p.exists():
            topic_dfs[topic_id] = pd.read_parquet(p)

    autostop_col: list[float] = []
    scrc_t_col: list[float] = []
    scrc_i_col: list[float] = []
    rlstop_col: list[float] = []
    uncalibrated_col: list[float] = []

    for _, row in df_sweep.iterrows():
        topic_id = str(row["topic_id"])
        alpha = float(row["alpha"])
        df_topic = topic_dfs.get(topic_id)

        if df_topic is None:
            autostop_col.append(float("nan"))
            scrc_t_col.append(float("nan"))
            scrc_i_col.append(float("nan"))
            rlstop_col.append(float("nan"))
            uncalibrated_col.append(float("nan"))
            continue

        print(f"  Baselines: {topic_id} α={alpha:.2f}")
        autostop_col.append(_autostop_fnr_at_alpha(df_topic, topic_id, alpha, data_dir))
        scrc_t_col.append(_scrc_fnr_at_alpha(df_topic, alpha, "T"))
        scrc_i_col.append(_scrc_fnr_at_alpha(df_topic, alpha, "I"))
        rlstop_col.append(_rlstop_fnr_at_alpha(df_topic, topic_id, alpha, data_dir, train_dir))
        uncalibrated_col.append(_uncalibrated_fnr(df_topic))

    df_out = df_sweep.copy()
    df_out["autostop_fnr"] = autostop_col
    df_out["scrc_t_fnr"] = scrc_t_col
    df_out["scrc_i_fnr"] = scrc_i_col
    df_out["rlstop_fnr"] = rlstop_col
    df_out["uncalibrated_fnr"] = uncalibrated_col

    return df_out


# ---------------------------------------------------------------------------
# Sanity check table (Task 5)
# ---------------------------------------------------------------------------

def _print_sanity_table(df_sweep: pd.DataFrame) -> None:
    """Print mean FNR per α across certified topics — quick sanity check for Figure 1."""
    alphas_to_show = [0.01, 0.05, 0.10, 0.15, 0.20]
    header = f"{'α':>6}  {'CASCADE-RC FNR':>16}  {'AUTOSTOP FNR':>14}  {'SCRC-T FNR':>12}  {'Below diagonal?':>16}"
    print("\n" + "="*len(header))
    print("Figure 1 sanity check (mean FNR across certified topics)")
    print("="*len(header))
    print(header)
    print("-"*len(header))

    certified = df_sweep[df_sweep.get("status", pd.Series(dtype=str)) == "certified"] \
        if "status" in df_sweep.columns else pd.DataFrame()

    for alpha in alphas_to_show:
        sub = certified[certified["alpha"] == alpha] if not certified.empty else pd.DataFrame()

        if sub.empty or "fnr_test" not in sub.columns:
            crc_fnr = float("nan")
        else:
            crc_fnr = sub["fnr_test"].mean()

        autostop_fnr = sub["autostop_fnr"].mean() if (not sub.empty and "autostop_fnr" in sub.columns) else float("nan")
        scrc_t_fnr = sub["scrc_t_fnr"].mean() if (not sub.empty and "scrc_t_fnr" in sub.columns) else float("nan")

        below = "Yes" if (not math.isnan(crc_fnr) and crc_fnr <= alpha) else "No" if not math.isnan(crc_fnr) else "N/A"

        def _fmt(v: float) -> str:
            return f"{v:.4f}" if not math.isnan(v) else "  N/A  "

        print(f"{alpha:>6.2f}  {_fmt(crc_fnr):>16}  {_fmt(autostop_fnr):>14}  {_fmt(scrc_t_fnr):>12}  {below:>16}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Alpha sweep for Figure 1 (Risk-Control Validity)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--topics", nargs="+", default=_DEFAULT_TOPICS, metavar="TOPIC_ID",
        help="Topic IDs to include in the sweep.",
    )
    parser.add_argument(
        "--artefact-dir", type=Path, default=Path("artefacts/cascade_rc"),
        help="Root artefact directory (contains data/<topic>.parquet).",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/clef_tar"),
        help="CLEF-TAR data directory (used by AUTOSTOP/RLStop for topic titles).",
    )
    parser.add_argument(
        "--train-dir", type=Path, default=Path("artefacts/baselines/rlstop"),
        help="Directory with cached RLStop PPO model .zip files.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output parquet path for the sweep results.",
    )
    parser.add_argument(
        "--alpha-values", nargs="+", type=float, default=ALPHA_SWEEP, metavar="ALPHA",
        help="Alpha values to sweep.",
    )
    parser.add_argument(
        "--delta-total", type=float, default=0.10,
        help="Total delta budget (split as delta_eta + delta_ltt).",
    )
    parser.add_argument(
        "--delta-eta", type=float, default=0.03,
        help="Delta budget for eta (slack) estimation.",
    )
    parser.add_argument(
        "--skip-baselines", action="store_true",
        help="Skip baseline computation (AUTOSTOP, SCRC, RLStop). CASCADE-RC only.",
    )
    args = parser.parse_args()

    # Step 1: Run CASCADE-RC alpha sweep
    df_sweep = run_alpha_sweep(
        topic_ids=args.topics,
        artefact_dir=args.artefact_dir,
        delta_total=args.delta_total,
        delta_eta=args.delta_eta,
        alpha_values=args.alpha_values,
        output_path=None,  # save after augmentation
    )

    # Step 2: Augment with baseline FNRs
    if not args.skip_baselines:
        print("\n" + "="*60)
        print("Computing baseline FNRs ...")
        print("="*60)
        df_sweep = augment_with_baselines(
            df_sweep=df_sweep,
            artefact_dir=args.artefact_dir,
            data_dir=args.data_dir,
            train_dir=args.train_dir,
        )

    # Step 3: Validate Theorem 5
    print("\n" + "="*60)
    print("Theorem 5 validation (FNR ≤ α at every certified (topic, α))")
    print("="*60)
    t5 = validate_theorem5(df_sweep)
    print(f"  Total certified pairs : {t5['total_certified']}")
    print(f"  Pass rate             : {t5['pass_rate']:.4f}")
    print(f"  Theorem 5 holds       : {t5['theorem5_holds']}")

    if not t5["theorem5_holds"]:
        print("\n  VIOLATIONS:")
        for v in t5["violations"]:
            print(
                f"    VIOLATION: topic={v['topic_id']}, "
                f"alpha={v['alpha']:.3f}, fnr_test={v['fnr_test']:.4f} > alpha={v['alpha']:.3f}"
            )

    # Step 4: Sanity check table
    _print_sanity_table(df_sweep)

    # Step 5: Save
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        df_sweep.to_parquet(args.output, index=False)
        print(f"\nAlpha sweep results saved to {args.output}")
    else:
        print("\n(--output not specified; results not persisted)")
        print(df_sweep.to_string())

    sys.exit(0 if t5["theorem5_holds"] else 1)


if __name__ == "__main__":
    main()
