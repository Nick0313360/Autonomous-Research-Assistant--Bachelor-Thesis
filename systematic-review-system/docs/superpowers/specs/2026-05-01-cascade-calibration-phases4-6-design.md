# CASCADE-RC Phases 4–6: Main Calibration Design

**Date:** 2026-05-01  
**Branch:** feature_redesignv2  
**Prompt:** 7.1 — Wire Phases 4–6 into Algorithm 1 with abstention and checkpointing

---

## Scope

Three new files implement Algorithm 1 (paper §5.4):

| File | Role |
|---|---|
| `cascade_rc/certificates/store.py` | `CertificationResult` dataclass + `CertificateStore` persistence |
| `cascade_rc/calibration/main_calibrate.py` | Algorithm 1 orchestrator + chunked WSR checkpointing + CLI |
| `cascade_rc/tests/test_main_calibrate_synthetic.py` | 3 required tests |

One addition to an existing file:

| File | Change |
|---|---|
| `cascade_rc/calibration/surrogate_loss.py` | Add `slack_tensor()` for the corrected η_i formula |
| `cascade_rc/config.py` | Add `c_human: float = 5.0`, `c_llm: float = 0.001` to `LTTBudget` |

---

## Corrected Slack Formula (§5.2)

**Critical:** `proxy = 0 ⇒ η_i = L̃_i` is mathematically invalid. It makes the test `R̂ ≤ α + E[L̃]` trivially true everywhere, invalidating all certificates.

The correct definition is:

```
η_i(θ) = L̃_i(θ) - L_i(θ)
```

where `L_i(θ)` is the **observed cascade loss** given the LLM's actual cached verdict `y_hat_i`:

```
if s_i < λ_lo:                             L_i = 1   # cheap-rejected → miss
elif s_i ≥ λ_hi:                           L_i = 0   # auto-included → catch
elif u_i < τ_SE:                           L_i = 0   # escalates to human → catch (y=1)
elif u_i ≥ τ_SE and y_hat_i == 0:         L_i = 1   # LLM followed, wrong → miss
elif u_i ≥ τ_SE and y_hat_i == 1:         L_i = 0   # LLM followed, correct → catch
```

Vectorised form:
```python
L_obs = (s < lam_lo) | ((lam_lo <= s) & (s < lam_hi) & (u >= tau_se) & (y_hat == 0))
```

Since `L̃_i = (s < λ_lo) | ((λ_lo ≤ s < λ_hi) & (u ≥ τ_SE))`, the slack simplifies to:

```
η_i(θ) = L̃_i - L_i = 1 iff (λ_lo ≤ s_i < λ_hi) AND (u_i ≥ τ_SE) AND (y_hat_i == 1)
        = 0 otherwise
```

This is non-negative by Lemma 1 (dominating loss ≥ observed loss). Added as `slack_tensor(theta_grid, s_pos, u_pos, y_hat_pos)` in `surrogate_loss.py`.

---

## Algorithm 1 Step-by-Step

**Inputs:** `topic_id`, calibration parquet (columns: `pmid, s, u, y_abstract, llm_y_hat, is_calib`), `CascadeRCConfig`

**Step 1 — Filter positives:**
```python
df_pos = df[(df.is_calib == 1) & (df.y_abstract == 1)]
m_plus = len(df_pos)
```

**Step 2 — Abstention check:**
```python
N_min = ceil(log(1/δ_LTT) / (-log(1 - α)))
# With α=0.10, δ_LTT=0.07: N_min = 26
if m_plus < N_min:
    return (None, None, f"abstained:m_plus={m_plus}<{N_min}")
```

**Step 3 — Build grid:**
```python
theta_grid = surrogate_loss.grid(K=20)  # shape (G, 3), G ≤ 4200
```

**Step 4 — Slack and η̂⁻⋆ (with checkpointing):**
```python
# loss_mat: (G, m_plus) — dominating loss
loss_mat = loss_tensor(theta_grid, s_pos, u_pos)
# slack_mat: (G, m_plus) — η_i = L̃_i - L_i
slack_mat = slack_tensor(theta_grid, s_pos, u_pos, y_hat_pos)
# Compute WSR LCB in chunks of 500; checkpoint after each chunk
eta_lcb = _compute_eta_lcb_chunked(slack_mat, delta_eta, G, chunk_size=500)
```

**Step 5 — Empirical risk:**
```python
R_hat = loss_mat.mean(axis=1)  # (G,)
```

**Step 6 — Corrected level:**
```python
alpha_dagger = alpha + eta_lcb  # (G,); note: adds LCB (not subtracts)
```

**Step 7 — HB p-values:**
```python
p_hb = hb_pvalues(R_hat, alpha_dagger, n=m_plus)  # (G,)
```

**Step 8 — Fixed-sequence walk:**
```python
order = safest_to_riskiest_order(theta_grid)
lambda_hat_mask = walk_reject(p_hb, order, delta_LTT)
```

**Step 9 — Optimal θ̂:**
```python
# expected_cost computed over ALL is_calib==1 rows (positives + negatives)
# so P_escalate_* reflects realistic paper-flow proportions
costs = expected_cost(theta_grid, s_all, u_all, c_human, c_llm)
# argmin cost restricted to Λ̂
theta_hat_idx = np.argmin(np.where(lambda_hat_mask, costs, np.inf))
theta_hat = theta_grid[theta_hat_idx]
```

**Step 10 — Persist:**
```python
store.save(topic, result, artefact_dir)    # .pkl + .json
store.delete_partial(topic, artefact_dir)  # clean up partial on success
```

---

## Expected Cost Function

```
P_escalate_no_se(θ) = P(λ_lo ≤ s < λ_hi, u < τ_SE)   # uncertain, SE does NOT fire
P_escalate_se(θ)    = P(λ_lo ≤ s < λ_hi, u ≥ τ_SE)   # uncertain, SE fires → human review
expected_cost(θ)    = c_human · P_escalate_no_se + c_llm · P_escalate_se
```

Default costs: `c_human=5.0`, `c_llm=0.001` (5000× ratio; reflects ~5-min Cochrane review at $60/h vs gpt-oss inference).

These are added to `LTTBudget` and serialised in the JSON summary.

---

## `CertificationResult` Dataclass

```python
@dataclass
class CertificationResult:
    topic: str
    status: str                        # "certified" | "abstained"
    abstain_reason: str | None
    m_plus: int
    theta_hat: np.ndarray              # (3,)  optimal θ̂
    lambda_hat_mask: np.ndarray        # (G,)  True = rejected (certified)
    theta_grid: np.ndarray             # (G, 3)
    eta_lcb_grid: np.ndarray           # (G,)  η̂⁻⋆
    r_hat_grid: np.ndarray             # (G,)  R̂
    p_hb_grid: np.ndarray             # (G,)  p_HB
    alpha_dagger_grid: np.ndarray      # (G,)  α†
    config_snapshot: dict
    timestamp: str                     # ISO-8601
```

`CertificateStore` methods: `save`, `load`, `save_partial`, `load_partial`, `delete_partial`. Pickle artefact at `<artefact_dir>/certificates/<topic>.pkl`; partial at `<topic>.partial.pkl`; JSON summary at `<topic>.json`.

---

## Checkpointing Protocol

Partial state dict:
```python
{"grid_idx_completed": int, "eta_lcb_partial": np.ndarray}
```

On startup: if `<topic>.partial.pkl` exists, load it, skip rows `[0, grid_idx_completed)` in WSR loop. On successful completion: delete partial.

Chunk size: 500. Grid size ~4200 → ~9 checkpoints.

---

## CLI

```
python -m cascade_rc.calibration.main_calibrate \
  --topic CD008874 \
  --calib-parquet artefacts/cascade_rc/data/CD008874.parquet \
  --config cascade_rc.yaml
```

Exits 0 on certification or abstention (abstention prints reason to stdout). Exits 1 on error.

---

## Tests

### `test_certification_synthetic`

```python
df = generate_paper_running_example(n=10_000, seed=0)
# add is_calib (50/50 stratified), rename y → y_abstract, add llm_y_hat
# call calibrate() with α=0.10, δ_LTT=0.07
assert result.status == "certified"
assert result.lambda_hat_mask.sum() > 0
# Pin θ̂ to reference computed on first correct run (seed=0, ±1 grid step tolerance)
# Reference: determined at implementation time; hardcoded in test with docstring note
```

### `test_abstention_when_m_plus_below_N_min`

```python
# Build df_pos with exactly 20 rows (m_plus=20 < N_min=26)
_, _, reason = calibrate(...)
assert reason.startswith("abstained:m_plus=20")
```

### `test_resume_from_partial`

```python
# Run calibrate() but raise KeyboardInterrupt after 1000 grid points via monkeypatching
# Restart; assert bytes(result_full.lambda_hat_mask) == bytes(result_resumed.lambda_hat_mask)
```

---

## Files Not Touched

`wsr_lcb.py`, `hb_pvalue.py`, `walker.py` — no changes. `data/`, `cache/`, `synthetic/` — no changes.
