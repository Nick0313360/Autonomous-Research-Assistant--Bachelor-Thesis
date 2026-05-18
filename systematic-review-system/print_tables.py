import pandas as pd, json, math, pickle
from pathlib import Path

BASE = Path('artefacts/cascade_rc')

# ── helpers ───────────────────────────────────────────────────────────────────
def wilson_ci(k, n, z=1.96):
    if n == 0: return (0.0, 1.0)
    p = k / n
    d = 1 + z**2/n
    c = (p + z**2/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / d
    return (max(0, c-h), min(1, c+h))

def load_eval(tid):
    with open(BASE / f'results/{tid}_eval.json') as f: return json.load(f)

def load_cert(tid):
    p = BASE / f'certificates/{tid}.json'
    return json.load(open(p)) if p.exists() else None

def topic_totals(tid):
    p = BASE / f'data/{tid}.parquet'
    if not p.exists(): return None, None
    df = pd.read_parquet(p)
    return len(df), int((df['y_abstract'] == 1).sum())

def wss_fmt(v):
    return '---' if (v is None or (isinstance(v, float) and (math.isnan(v) or v == -999.0))) else f'{v:.4f}'

sweep    = pd.read_parquet(BASE / 'results/alpha_sweep.parquet')
scrc     = pd.read_parquet(BASE / 'baselines/scrc_results.parquet')
autostop = pd.read_parquet(BASE / 'baselines/autostop_results.parquet')
rlstop   = pd.read_parquet(BASE / 'baselines/rlstop_results.parquet')
budget   = pd.read_parquet(BASE / 'ablations/budget_split.parquet')

# ═════════════════════════════════════════════════════════════════════════════
# TABLE 1A — CASCADE-RC headline results across α ∈ {0.05, 0.10, 0.15}
#            + CD012768 ABSTAIN row at α=0.05 (safety floor demo)
# ═════════════════════════════════════════════════════════════════════════════
print('=' * 90)
print('TABLE 1A — CASCADE-RC headline results  (α sweep + abstention demo)')
print('  Topics: CD008874, CD011975 at α∈{0.05,0.10,0.15}  |  CD012768 ABSTAIN at α=0.05')
print('=' * 90)
print(f'  {"Topic":<12} {"α":>5} {"Status":<12} {"m+_calib":>9} {"N_min":>6} '
      f'{"FNR_test":>9} {"WSS@95":>8} {"Esc%":>6} {"η̂⁻*":>8} {"α†":>6}')
print(f'  {"-"*88}')

for tid in ['CD008874', 'CD011975']:
    for alpha in [0.05, 0.10, 0.15]:
        row = sweep[(sweep['topic_id'] == tid) & (sweep['alpha'] == alpha)]
        if row.empty:
            continue
        r = row.iloc[0]
        ev = load_eval(tid)
        esc = f"{ev['frac_escalated']:.1%}" if alpha == 0.10 else '—'
        fnr_s = f"{r['fnr_test']:.4f}" if r['status'] == 'certified' else 'ABSTAIN'
        wss_s = wss_fmt(r['wss_95']) if r['status'] == 'certified' else '---'
        eta_s = f"{r['eta_lcb_star']:.4f}" if pd.notna(r['eta_lcb_star']) else '---'
        ad_s  = f"{r['alpha_dagger']:.4f}" if pd.notna(r['alpha_dagger']) else '---'
        nmin_s = str(int(r['nmin'])) if pd.notna(r['nmin']) else '---'
        print(f'  {tid:<12} {alpha:>5.2f} {r["status"]:<12} {int(r["m_plus"]):>9} {nmin_s:>6} '
              f'{fnr_s:>9} {wss_s:>8} {esc:>6} {eta_s:>8} {ad_s:>6}')

# CD012768 ABSTAIN row at α=0.05
row = sweep[(sweep['topic_id'] == 'CD012768') & (sweep['alpha'] == 0.05)].iloc[0]
print(f'  {"CD012768":<12} {0.05:>5.2f} {"ABSTAIN":<12} {int(row["m_plus"]):>9} '
      f'{int(row["nmin"]):>6} {"---":>9} {"---":>8} {"—":>6} {"---":>8} {"---":>6}')
print()
print('  Notes:')
print('  - η̂⁻* = eta_lcb_star: lower confidence bound on η at certified threshold (LTT/HB)')
print('  - α† = alpha_dagger: effective alpha budget consumed by the Bonferroni union')
print('  - WSS@95 = --- means recall target not achieved on test split')
print('  - CD011975 α=0.10 WSS@95 = --- because achieved recall = 0.9421 < 0.95')
print('  - Esc% shown only at α=0.10 (primary operating point); cross-α routing is identical')


# ═════════════════════════════════════════════════════════════════════════════
# TABLE 1B — Head-to-head baseline comparison  (IID split, α=0.10)
#            Strictly CD008874 and CD011975
# ═════════════════════════════════════════════════════════════════════════════
print()
print('=' * 90)
print('TABLE 1B — Head-to-head baseline comparison  (IID split, α=0.10, @recall_target=0.95)')
print('=' * 90)

for tid in ['CD008874', 'CD011975']:
    ev = load_eval(tid)
    m_test = ev['n_test_positives']
    cert = load_cert(tid)

    rows = []
    # CASCADE-RC
    fnr = ev['fnr_test']
    lo, hi = wilson_ci(round(fnr * m_test), m_test)
    rows.append(('CASCADE-RC', fnr, lo, hi, ev['recall_achieved'],
                 ev['wss_95'], cert['status'], f"Esc={ev['frac_escalated']:.1%}"))

    for method, label in [('scrc_t', 'SCRC-T'), ('scrc_i', 'SCRC-I')]:
        r = scrc[(scrc['topic_id']==tid) & (scrc['method']==method) & (scrc['target_recall']==0.95)]
        if not r.empty:
            r = r.iloc[0]
            fnr_b = 1 - r['recall_achieved']
            lo2, hi2 = wilson_ci(round(fnr_b * m_test), m_test)
            rows.append((label, fnr_b, lo2, hi2, r['recall_achieved'],
                         r['wss_95'] if pd.notna(r['wss_95']) else float('nan'), 'N/A', ''))

    for df2, label in [(autostop, 'AutoStop'), (rlstop, 'RLStop')]:
        r = df2[(df2['topic_id']==tid) & (df2['target_recall']==0.95)]
        if not r.empty:
            r = r.iloc[0]
            fnr_b = 1 - r['recall_achieved']
            lo2, hi2 = wilson_ci(round(fnr_b * m_test), m_test)
            rows.append((label, fnr_b, lo2, hi2, r['recall_achieved'],
                         r['wss_95'] if pd.notna(r['wss_95']) else float('nan'), 'N/A', ''))

    n_total, m_total = topic_totals(tid)
    print(f'\n  --- {tid}  n_total={n_total}  m+_total={m_total}  '
          f'n_test={ev["n_test"]}  m+_test={m_test} ---')
    print(f'  {"Method":<12} {"FNR":>7} {"CI_lo":>7} {"CI_hi":>7} '
          f'{"Recall":>8} {"WSS@95":>8} {"Cert":<12} Notes')
    print(f'  {"-"*72}')
    for label, fnr, lo, hi, rec, wss, cert_s, notes in rows:
        print(f'  {label:<12} {fnr:>7.4f} {lo:>7.4f} {hi:>7.4f} '
              f'{rec:>8.4f} {wss_fmt(wss):>8} {cert_s:<12} {notes}')


# ═════════════════════════════════════════════════════════════════════════════
# TABLE 3 — Temporal vs IID splits  (Appendix)
# ═════════════════════════════════════════════════════════════════════════════
print()
print('=' * 90)
print('TABLE 3 — Temporal vs IID splits  (Appendix)')
print('=' * 90)
temporal_fnr = {'CD012080': 0.1852, 'CD011768': 0.3636, 'CD012768': 0.4444}
print(f'  {"Topic":<12} {"IID_FNR":>9} {"IID_Recall":>11} {"IID_WSS@95":>11} '
      f'{"Temp_FNR":>10} {"Temp_Recall":>12} {"Temp_WSS@95":>12}')
print(f'  {"-"*82}')
for tid in ['CD012080', 'CD011768', 'CD012768']:
    ev = load_eval(tid)
    tfnr = temporal_fnr[tid]
    print(f'  {tid:<12} {ev["fnr_test"]:>9.4f} {ev["recall_achieved"]:>11.4f} '
          f'{wss_fmt(ev["wss_95"]):>11} {tfnr:>10.4f} {1-tfnr:>12.4f} {"N/A":>12}')
print()
print('  Temporal FNRs sourced from documents (no temporal-split artefact in repo).')
print('  Temporal WSS@95 not computed.')


# ═════════════════════════════════════════════════════════════════════════════
# TABLE 4 — Slack Ratios & Budget-Split Ablation  (Appendix)
#           η̂⁻* / θ̂(λ̂)⁺  across (δ_eta, δ_LTT) configurations
# ═════════════════════════════════════════════════════════════════════════════
print()
print('=' * 90)
print('TABLE 4 — Slack Ratios & Budget-Split Ablation  (Appendix)')
print('  slack_ratio = mean_eta_lcb / theta_hat_lambda_hi  (η̂⁻* / θ̂(λ̂)⁺)')
print('=' * 90)
print(f'  {"Topic":<12} {"δ_eta":>7} {"δ_LTT":>7} {"m+":>5} {"N_cert":>7} '
      f'{"Recall":>8} {"WSS@95":>8} {"mean_η̂⁻":>10} {"θ̂(λ̂)⁺":>10} {"SlackRatio":>11} {"α†":>8}')
print(f'  {"-"*95}')
for _, r in budget.sort_values(['topic_id','delta_eta']).iterrows():
    print(f'  {r["topic_id"]:<12} {r["delta_eta"]:>7.2f} {r["delta_ltt"]:>7.2f} '
          f'{int(r["m_plus"]):>5} {int(r["n_certified"]):>7} '
          f'{r["achieved_recall"]:>8.4f} {wss_fmt(r["wss_95"]):>8} '
          f'{r["mean_eta_lcb"]:>10.6f} {r["theta_hat_lambda_hi"]:>10.6f} '
          f'{r["slack_ratio"]:>11.6f} {r["alpha_dagger_at_theta"]:>8.4f}')
print()
print('  Note: all rows at α=0.10. Constraint: δ_eta + δ_LTT = 0.10.')


# ═════════════════════════════════════════════════════════════════════════════
# TABLE 5 — Full Configuration Grid  (Appendix)
#           All topics × α ∈ {0.01,0.02,0.05,0.10,0.15,0.20} with baseline FNRs
# ═════════════════════════════════════════════════════════════════════════════
print()
print('=' * 90)
print('TABLE 5 — Full Configuration Grid  (Appendix)')
print('  All topics × α levels. Baseline FNRs computed on same IID test split.')
print('=' * 90)
print(f'  {"Topic":<12} {"α":>5} {"Status":<12} {"m+":>5} {"N_min":>6} '
      f'{"CASCADE_FNR":>12} {"AutoStop_FNR":>13} {"SCRC-T_FNR":>11} '
      f'{"SCRC-I_FNR":>11} {"RLStop_FNR":>11} {"Uncalib_FNR":>12}')
print(f'  {"-"*103}')

all_topics = sorted(sweep['topic_id'].unique())
for tid in all_topics:
    for alpha in [0.01, 0.02, 0.05, 0.10, 0.15, 0.20]:
        row = sweep[(sweep['topic_id']==tid) & (sweep['alpha']==alpha)]
        if row.empty: continue
        r = row.iloc[0]
        fnr_s    = f"{r['fnr_test']:.4f}"    if r['status']=='certified' and pd.notna(r['fnr_test']) else ('ABS' if r['status']=='ABSTAIN' else '---')
        auto_s   = f"{r['autostop_fnr']:.4f}" if pd.notna(r['autostop_fnr']) else '---'
        scrc_t_s = f"{r['scrc_t_fnr']:.4f}"  if pd.notna(r['scrc_t_fnr'])  else '---'
        scrc_i_s = f"{r['scrc_i_fnr']:.4f}"  if pd.notna(r['scrc_i_fnr'])  else '---'
        rl_s     = f"{r['rlstop_fnr']:.4f}"  if pd.notna(r['rlstop_fnr'])  else '---'
        unc_s    = f"{r['uncalibrated_fnr']:.4f}" if pd.notna(r['uncalibrated_fnr']) else '---'
        nmin_s   = str(int(r['nmin'])) if pd.notna(r['nmin']) else '---'
        print(f'  {tid:<12} {alpha:>5.2f} {r["status"]:<12} {int(r["m_plus"]):>5} {nmin_s:>6} '
              f'{fnr_s:>12} {auto_s:>13} {scrc_t_s:>11} {scrc_i_s:>11} {rl_s:>11} {unc_s:>12}')
