ARTEFACT_DIR ?= artefacts/cascade_rc
TOPICS       ?= CD008874 CD012080 CD012768 CD011768 CD011975 CD011145
ALPHA        ?= 0.10

.PHONY: figures tables alpha_sweep validate manuscript

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
