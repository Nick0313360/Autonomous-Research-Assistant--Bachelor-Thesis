# Design: Crash-Resumable B=5, T=0.7 Ensemble Cache

**Date:** 2026-04-30
**Branch:** feature_redesignv2
**Prompt:** Prompt 3.1
**Files to create:** `cascade_rc/cache/sqlite_cache.py`, `cascade_rc/tests/test_sqlite_cache.py`, `cascade_rc/tests/test_llm_ensemble.py`
**Files to modify:** `cascade_rc/cache/llm_ensemble.py`

---

## 1. Goal

Enable crash-resumable ensemble screening: for B=5 slots per PMID, cache each LLM
response individually so that killing and restarting a run costs zero new LLM calls for
already-completed slots. The cache is the canonical record of replayability; LLM seed
determinism is intentionally out of scope.

---

## 2. Architecture

```
screen_abstract_ensemble(title, abstract, pico, pmid, ..., _cache, _client)
  │
  ├─ compute prompt_sha = sha256(filled_prompt.encode()).hexdigest()
  │
  └─ for b in 0..B-1:
       hit = cache.get(model_id, prompt_sha, pmid, temperature, seed_b=b, template_v)
       if hit:   vote from hit["vote_label"]         ← SQLite read, no LLM call
       else:     response = await client.complete()
                 cache.put(..., response, verdict, vote_label)
       votes.append(vote)
  │
  └─ majority, u, y_hat = _majority_and_u(votes, B)
     return EnsembleResult(votes, majority, u, y_hat)
```

**Single execution model:** the sequential loop runs always. The old `asyncio.gather`
parallel-fire path is removed entirely. At B=5, T=0.7, the extra ~4s latency vs
parallel is not worth maintaining two execution branches.

**`pmid=None` opt-out:** when `pmid` is `None`, `_cache` lookups are silently skipped.
Existing callers that do not supply `pmid` continue to work without change.

---

## 3. `SQLiteEnsembleCache` — `cascade_rc/cache/sqlite_cache.py`

### Schema

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    TEXT    NOT NULL,
    prompt_sha  TEXT    NOT NULL,   -- sha256 of rendered prompt (correctness invalidation)
    pmid        TEXT    NOT NULL,
    temperature REAL    NOT NULL,
    seed_b      INTEGER NOT NULL,   -- slot index 0..B-1 (cache discriminator only, NOT passed to LLM)
    template_v  TEXT    NOT NULL,   -- human-readable version tag (ablation filtering, e.g. WHERE template_v='v2')
    response    TEXT    NOT NULL,   -- raw JSON string from LLM
    verdict     INTEGER NOT NULL,   -- 0=Exclude, 1=Include, 2=Uncertain
    vote_label  TEXT    NOT NULL,   -- "Exclude" | "Include" | "Uncertain" (lossless round-trip)
    created_at  TEXT    NOT NULL,   -- ISO-8601 UTC: datetime.now(timezone.utc).isoformat()
    -- prompt_sha invalidates on any template edit; template_v enables human-readable
    -- ablation queries without juggling SHAs. Both columns serve different consumers.
    UNIQUE(model_id, prompt_sha, pmid, temperature, seed_b, template_v)
);
CREATE INDEX IF NOT EXISTS ix_pmid ON llm_calls(pmid);
```

### Interface

```python
class SQLiteEnsembleCache:
    def __init__(self, path: Path) -> None: ...
    # WAL + NORMAL sync; threading.local() per-thread connection pool.

    def get(self, *, model_id: str, prompt_sha: str, pmid: str,
            temperature: float, seed_b: int, template_v: str) -> dict | None: ...
    # Returns stored row dict or None on cache miss.

    def put(self, *, model_id: str, prompt_sha: str, pmid: str,
            temperature: float, seed_b: int, template_v: str,
            response: dict, verdict: int, vote_label: str) -> None: ...
    # INSERT OR IGNORE — idempotent; safe to call on retry.

    def fetch_ensemble(self, *, model_id: str, prompt_sha: str, pmid: str,
                       temperature: float, template_v: str, B: int) -> list[dict]: ...
    # Returns up to B cached rows for this (model, prompt, pmid, temp, template).

    def stats(self) -> dict: ...
    # {"total_rows": int, "unique_pmids": int, "rows_per_seed_b": dict[str, int]}
    # rows_per_seed_b shows whether all 5 slots are uniformly populated.

    def close(self) -> None: ...
    # Closes all thread-local connections; flushes WAL sidecars (.db-wal, .db-shm).
```

---

## 4. Refactored `screen_abstract_ensemble` — `cascade_rc/cache/llm_ensemble.py`

### Signature additions (no removals)

```python
async def screen_abstract_ensemble(
    title: str,
    abstract: str,
    pico: dict,
    pmid: str | None = None,           # None → caching skipped
    n_calls: int = 5,
    temperature: float = 0.7,
    _client: Optional[Any] = None,
    _cache: Optional[Any] = None,      # SQLiteEnsembleCache | None
    _model_id: str = "gpt-oss:120b",
    _template_v: str = "v1",
) -> EnsembleResult: ...
```

### `_majority_and_u` return signature change

Returns `(majority, u, y_hat)` — three values — so the caller never re-derives `y_hat`.

### Helpers added

- `_vote_to_int(vote: Vote) -> int` — `Include→1`, `Exclude→0`, `Uncertain→2`
- `_int_to_vote(v: int) -> Vote` — inverse of above

### Structured log lines

```
cache_hit  pmid=<pmid> slot=<b>
cache_miss pmid=<pmid> slot=<b> vote=<vote>
```

---

## 5. Offline driver (`__main__` block in `llm_ensemble.py`)

```
python -m cascade_rc.cache.llm_ensemble \
    --topic CD012768 \
    [--B 5] [--T 0.7] \
    [--cache-path artefacts/cascade_rc/llm_cache.db] \
    [--template-v v1] \
    [--ncbi-email user@example.com] \
    [--max-failures 10] \
    [--resume-from-pmid <pmid>] \
    [--dry-run]
```

**Flow:**
1. Load `CascadeRCConfig`; CLI args override config values.
2. `load_topic(topic_id, data_dir)` → `topic.candidate_pmids`.
3. `pubmed_fetch.fetch_abstracts(pmids, email)` → `dict[pmid → {title, abstract}]`.
   Skip PMIDs with no abstract (log warning).
4. Open `SQLiteEnsembleCache(cache_path)`.
5. Build fixed PICO from `_CRITERION_TEXT` (same for every PMID; topic-specific PICO
   deferred to a future template version bump).
6. `--dry-run`: report per-PMID cache completeness, exit 0 — no LLM calls.
7. `--resume-from-pmid`: skip SQLite reads for PMIDs known complete.
8. Per-PMID loop (tqdm): call `screen_abstract_ensemble(...)`.
   - **Transient errors** (timeout, LLM 503, parse error): catch, log warning, increment
     failure counter; continue. If counter exceeds `--max-failures`, abort the run.
   - **Structural errors** (cache write failure, all 5 slots fail): raise immediately,
     abort the run. A PMID with partial slots and no clean retry path is a corrupt state.
9. Print `json.dumps(cache.stats(), indent=2)` to stdout on exit.

---

## 6. Tests

### `cascade_rc/tests/test_sqlite_cache.py`

| Test | Assertion |
|---|---|
| `test_idempotency` | `put()` twice with identical key → `COUNT(*) == 1` |
| `test_resumability` | Pre-populate 3×5 rows; run 100-PMID loop; assert `client.complete` called `97×5=485` times |
| `test_seed_partition` | Delete `seed_b=2` row; run ensemble; assert `client.complete` called exactly once |
| `test_concurrent_writes` | Two threads, different keys, no exceptions, both rows present (validates `threading.local()`) |
| `test_close_flushes_wal` | Write rows, `close()`, assert no `.db-wal` / `.db-shm` sidecars |

### `cascade_rc/tests/test_llm_ensemble.py`

| Test | Votes | Expected |
|---|---|---|
| `test_tie_uncertain_b5_2_2_1` | `[Inc, Inc, Exc, Exc, Unc]` | `majority="Uncertain", u=0.0, y_hat=0` |
| `test_tie_b4_genuine` | `[Inc, Inc, Exc, Exc]` (B=4) | `majority="Uncertain", u=0.0, y_hat=0` |
| `test_b4_not_a_tie` | `[Inc, Inc, Exc, Unc]` (B=4) | `majority="Include", u=0.5, y_hat=1` — **not a tie**; Uncertain excluded from competition |
| `test_all_uncertain` | `[Unc×5]` | `majority="Uncertain", u=0.0, y_hat=0` — pathological LLM-undecidable case, routes to human review |
| `test_partial_cache_completion` | Slots 0,2,4 pre-populated | `client.complete` called exactly twice (slots 1,3); `votes` length 5; order preserved |
| `test_cache_hit_skips_llm` | All 5 slots pre-populated | `client.complete` never called |
| `test_vote_label_roundtrip` | All three verdict values | `get()` returns matching `vote_label` |

**Note on B=4 spec correction:** The original spec listed `[Inc×2, Exc×1, Unc×1]` as a
B=4 tie — this is wrong. `_majority_and_u` excludes Uncertain from the binary competition,
so `[Inc×2, Exc×1]` is an Include win, not a tie. The genuine B=4 tie is `[Inc×2, Exc×2]`.
The `test_b4_not_a_tie` test explicitly documents the correct behaviour to prevent
regressions from "fixing" it.

---

## 7. Acceptance criteria

```bash
sqlite3 artefacts/cascade_rc/llm_cache.db \
    "SELECT COUNT(*) FROM llm_calls"
# → B × n_pmids_in_topic (e.g. 5 × 614 = 3070 for CD012768)

# Kill mid-run and restart → zero new LLM calls for completed slots
# (verified by comparing client.complete call count to cache.stats()["total_rows"])
```
