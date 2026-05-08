ARTEFACT_DIR  ?= artefacts/cascade_rc
TOPICS        ?= CD008874 CD012080 CD012768 CD011768 CD011975 CD011145
ALPHA         ?= 0.10
MAX_WORKERS   ?= 6
N_CONCURRENT  ?= 20

.PHONY: figures tables alpha_sweep validate manuscript \
        parallel parallel-safe parallel-dry parallel-two-phase \
        cache-merge cache-migrate

figures:
	PYTHONHASHSEED=0 python3 -m cascade_rc.evaluation.figures \
		--artefact-dir $(ARTEFACT_DIR)

tables:
	python3 -m cascade_rc.evaluation.tables \
		--artefact-dir $(ARTEFACT_DIR) \
		--alpha $(ALPHA) \
		--headline    paper/tables/headline_results.tex \
		--nmin        paper/tables/nmin_compliance.tex \
		--budget      paper/tables/budget_split.tex \
		--walk        paper/tables/walk_ordering.tex \
		--msensitivity paper/tables/m_sensitivity.tex

alpha_sweep:
	python3 -m cascade_rc.evaluation.alpha_sweep \
		--topics $(TOPICS) \
		--output $(ARTEFACT_DIR)/results/alpha_sweep.parquet

validate:
	python3 -m cascade_rc.run_pipeline --validate-nmin
	python3 -c "\
import pandas as pd; \
from cascade_rc.evaluation.alpha_sweep import validate_theorem5; \
df = pd.read_parquet('$(ARTEFACT_DIR)/results/alpha_sweep.parquet'); \
r = validate_theorem5(df); \
print('Theorem 5 holds:', r['theorem5_holds']); \
print(f'Pass rate: {r[\"pass_rate\"]*100:.1f}%'); \
exit(0 if r['theorem5_holds'] else 1) \
"

manuscript: validate figures tables
	@echo ""
	@echo "All artefacts regenerated. Manuscript is ready."
	@echo "Run: cd paper && pdflatex main.tex"

# ---------------------------------------------------------------------------
# Parallel pipeline targets
# ---------------------------------------------------------------------------

## Run all 6 topics in parallel (max throughput — check API rate limits first)
parallel:
	python3 -m cascade_rc.run_parallel \
		--topics $(TOPICS) \
		--max-workers $(MAX_WORKERS) \
		--n-concurrent $(N_CONCURRENT)

## Conservative parallel run for endpoints with rate limits (300 peak API calls)
parallel-safe:
	python3 -m cascade_rc.run_parallel \
		--topics $(TOPICS) \
		--max-workers 3 \
		--n-concurrent 15

## Dry-run: show what parallel would execute without running anything
parallel-dry:
	python3 -m cascade_rc.run_parallel --dry-run \
		--topics $(TOPICS) \
		--max-workers $(MAX_WORKERS) \
		--n-concurrent $(N_CONCURRENT)

## Two-phase: parallel LLM scoring then sequential calibration (for ~16 GB RAM machines)
parallel-two-phase:
	python3 -m cascade_rc.run_parallel --two-phase \
		--topics $(TOPICS) \
		--max-workers $(MAX_WORKERS) \
		--n-concurrent $(N_CONCURRENT)

# ---------------------------------------------------------------------------
# Cache utility targets
# ---------------------------------------------------------------------------

## Merge all per-topic SQLite caches into one portable file
cache-merge:
	python3 -m cascade_rc.cache.sqlite_cache merge \
		--topics $(TOPICS) \
		--cache-dir $(ARTEFACT_DIR)/llm_cache \
		--output $(ARTEFACT_DIR)/llm_cache_merged.db

## Migrate a legacy shared llm_cache.db into per-topic files
cache-migrate:
	python3 -m cascade_rc.cache.sqlite_cache migrate \
		--source $(ARTEFACT_DIR)/llm_cache.db \
		--output-dir $(ARTEFACT_DIR)/llm_cache \
		--parquet-dir $(ARTEFACT_DIR)/data
