"""
tier3_synthesis/review_evaluator.py
=======================================
Evaluation utilities: search completeness, screening accuracy, PRISMA compliance.
"""
from __future__ import annotations
import logging
from collections import Counter
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

_REQUIRED_PRISMA = (
    "records_identified", "duplicates_removed", "records_after_deduplication",
    "records_screened", "records_excluded_abstract", "records_sought_fulltext",
    "records_not_retrieved", "records_assessed_fulltext",
    "records_excluded_fulltext", "studies_included",
)

class ReviewEvaluator:
    def evaluate_search_completeness(self, records: List[Any], protocol: Any) -> Dict:
        total = len(records)
        db_counts: Dict[str, int] = Counter(getattr(r,"source_database","unknown") for r in records)
        target_dbs = set(getattr(protocol,"target_databases",[]))
        db_coverage = len(set(db_counts)&target_dbs)/len(target_dbs) if target_dbs else 1.0
        years = sorted({getattr(r,"year",None) for r in records if getattr(r,"year",None) is not None})
        date_range = getattr(protocol,"date_range",None)
        if date_range and years:
            s,e = date_range; temporal_coverage = sum(1 for y in years if s<=y<=e)/(e-s+1)
        else:
            temporal_coverage = 1.0 if years else 0.0
        estimated_saturation = False
        if len(years) >= 3:
            arr = np.array(list(Counter(getattr(r,"year",None) for r in records if getattr(r,"year",None)).values()),dtype=float)
            cv = float(arr.std()/arr.mean()) if arr.mean()>0 else 1.0
            estimated_saturation = cv < 0.5
        return {"total_records":total,"database_coverage":round(db_coverage,3),
                "databases_retrieved":dict(db_counts),"databases_targeted":list(target_dbs),
                "temporal_coverage":round(temporal_coverage,3),"years_covered":years,
                "estimated_saturation":estimated_saturation}

    def evaluate_screening_accuracy(self, decisions: List[Any], gold_standard: Optional[Dict[str,str]]=None) -> Dict:
        def _dec(d): return str(getattr(d,"decision","") if not isinstance(d,dict) else d.get("decision","")).lower().replace("decision.","")
        def _rid(d): return str(getattr(d,"decision_record_id","") if not isinstance(d,dict) else d.get("decision_record_id",d.get("record_id","")))
        dist = Counter(_dec(d) for d in decisions); total = len(decisions)
        result = {"total_decisions":total,"distribution":dict(dist),
                  "include_rate":dist.get("include",0)/total if total else 0.0,
                  "exclude_rate":dist.get("exclude",0)/total if total else 0.0,
                  "uncertain_rate":dist.get("uncertain",0)/total if total else 0.0}
        if not gold_standard:
            return result
        tp=fp=fn=0
        for d in decisions:
            pred=_dec(d); gold=gold_standard.get(_rid(d),"")
            if not gold: continue
            if gold=="include":
                tp+=1 if pred=="include" else 0; fn+=0 if pred=="include" else 1
            elif pred=="include": fp+=1
        precision = tp/(tp+fp) if (tp+fp)>0 else 0.0
        recall    = tp/(tp+fn) if (tp+fn)>0 else 0.0
        f1 = 2*precision*recall/(precision+recall) if (precision+recall)>0 else 0.0
        f2 = 5*precision*recall/(4*precision+recall) if (4*precision+recall)>0 else 0.0
        result.update({"true_positives":tp,"false_positives":fp,"false_negatives":fn,
                        "precision":round(precision,4),"recall":round(recall,4),
                        "f1":round(f1,4),"f2":round(f2,4)})
        return result

    def evaluate_prisma_compliance(self, prisma_state: Any) -> Dict:
        if isinstance(prisma_state,dict): counts=prisma_state
        elif hasattr(prisma_state,"generate_prisma_counts"): counts=prisma_state.generate_prisma_counts()
        elif hasattr(prisma_state,"stage_counts"):
            sc=prisma_state.stage_counts
            counts={"records_identified":sc.get("identification_total",0),"duplicates_removed":sc.get("duplicates_removed",0),
                    "records_after_deduplication":sc.get("after_dedup",0),"records_screened":sc.get("abstracts_screened",0),
                    "records_excluded_abstract":sc.get("abstract_excluded",0),"records_sought_fulltext":sc.get("fulltext_sought",0),
                    "records_not_retrieved":sc.get("fulltext_not_retrieved",0),"records_assessed_fulltext":sc.get("fulltext_assessed",0),
                    "records_excluded_fulltext":sc.get("fulltext_excluded",0),"studies_included":sc.get("studies_included",0)}
        else: counts={}
        missing=[f for f in _REQUIRED_PRISMA if counts.get(f) is None]
        if counts.get("records_identified",0)==0 and "records_identified" not in missing:
            missing.append("records_identified (is zero)")
        warnings=[]
        if counts.get("records_after_deduplication",0)>counts.get("records_identified",0): warnings.append("after_dedup > identified")
        if counts.get("studies_included",0)>counts.get("records_after_deduplication",0): warnings.append("included > after_dedup")
        n_missing=sum(1 for f in missing if "zero" not in f)
        score=max(0.0,(len(_REQUIRED_PRISMA)-n_missing)/len(_REQUIRED_PRISMA))
        return {"compliance_score":round(score,3),"missing_fields":missing,
                "flow_warnings":warnings,"all_counts":{f:counts.get(f,0) for f in _REQUIRED_PRISMA}}
