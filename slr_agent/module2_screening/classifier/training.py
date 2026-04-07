"""Module 2 — Training (SynergyTrainer, SynergyDataAudit, SynergySplitter)"""

from __future__ import annotations

import os
import sys
import json
import random
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict

import pandas as pd

# Allow imports from parent directory (module2_screening)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Paper, SearchQuery
from connectors import GptConnector


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def _extract_paper_metadata(review_dir: Path) -> pd.DataFrame:
    """Extract title/abstract from works_*.zip JSON files in a review folder."""
    records = []
    for zip_path in review_dir.glob("works_*.zip"):
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if name.endswith(".json"):
                        with zf.open(name) as jf:
                            data = json.load(jf)
                            if isinstance(data, list):
                                for item in data:
                                    title = item.get("title", "") or ""
                                    abstract = item.get("abstract", "") or ""
                                    openalex_id = item.get("id", "")
                                    doi = ""
                                    for loc in item.get("locations", []):
                                        if loc.get("landing_page_url", ""):
                                            doi = str(loc["landing_page_url"])
                                            break
                                    if not doi:
                                        dois = item.get("doi", "")
                                        doi = dois if dois else ""
                                    records.append(
                                        {
                                            "openalex_id": openalex_id,
                                            "doi": doi,
                                            "title": title,
                                            "abstract": abstract,
                                        }
                                    )
        except Exception:
            continue
    return pd.DataFrame(records)


def _load_review(review_dir: Path) -> Optional[pd.DataFrame]:
    """Load a single review: labels.csv + metadata from works_*.zip."""
    labels_path = review_dir / "labels.csv"
    if not labels_path.exists():
        return None

    labels = pd.read_csv(labels_path)
    labels.columns = [c.lower().strip() for c in labels.columns]

    # SYNERGY uses label_included, not just label
    label_col = None
    for c in ["label_included", "label", "included"]:
        if c in labels.columns:
            label_col = c
            break
    if label_col is None:
        return None

    # Extract metadata
    metadata = _extract_paper_metadata(review_dir)
    if metadata.empty:
        return None

    # Merge on openalex_id or doi
    merge_col = "openalex_id" if "openalex_id" in labels.columns else "doi"
    if merge_col not in metadata.columns:
        return None

    merged = metadata.merge(
        labels[[merge_col, label_col]],
        on=merge_col,
        how="left",
    )

    merged["label"] = merged[label_col].fillna(0).astype(int)
    merged["review_id"] = review_dir.name

    return merged[["review_id", "title", "abstract", "label"]]


# ══════════════════════════════════════════════════════════════════════════════
# DATA AUDIT
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class SynergyDataAudit:
    """
    Module 2::Training::SynergyDataAudit
    Run BEFORE training. Reveals dataset structure.
    DATA IN:  synergyDir — path to SYNERGY dataset root
              Expects: synergyDir/<review_name>/labels.csv + works_*.zip
    DATA OUT: dict with total_reviews, total_papers, avg_inclusion_pct, reviews
    """

    synergyDir: str

    def run(self) -> dict:
        path = Path(self.synergyDir)
        reviews = []

        # Scan for review folders
        review_dirs = sorted(
            [d for d in path.iterdir() if d.is_dir() and (d / "labels.csv").exists()]
        )

        if not review_dirs:
            # Try one level deeper (e.g., doi-10/synergy-dataset-v1.0/)
            for sub in sorted(path.iterdir()):
                if sub.is_dir():
                    review_dirs.extend(
                        [
                            d
                            for d in sub.iterdir()
                            if d.is_dir() and (d / "labels.csv").exists()
                        ]
                    )

        for review_dir in review_dirs:
            df = _load_review(review_dir)
            if df is None or df.empty:
                print(f"  SKIP {review_dir.name} — could not load")
                continue

            n_inc = int((df["label"] == 1).sum())
            n_exc = int((df["label"] == 0).sum())
            n_tot = len(df)
            m_tit = int(df["title"].isna().sum())
            m_abs = int(df["abstract"].isna().sum())
            pct = round(n_inc / max(n_tot, 1) * 100, 2)

            reviews.append(
                {
                    "review_id": review_dir.name,
                    "n_total": n_tot,
                    "n_include": n_inc,
                    "n_exclude": n_exc,
                    "inclusion_pct": pct,
                    "missing_title": m_tit,
                    "missing_abstract": m_abs,
                }
            )

        total_papers = sum(r["n_total"] for r in reviews)
        total_includes = sum(r["n_include"] for r in reviews)
        avg_pct = round(total_includes / max(total_papers, 1) * 100, 2)

        print(f"\n=== SYNERGY Data Audit ===")
        print(f"Reviews:         {len(reviews)}")
        print(f"Total papers:    {total_papers}")
        print(f"Total includes:  {total_includes}")
        print(f"Avg inclusion %: {avg_pct}%\n")
        for r in sorted(reviews, key=lambda x: x["inclusion_pct"]):
            flag = " *** LOW" if r["inclusion_pct"] < 2 else ""
            print(
                f"  {r['review_id']:<30} "
                f"n={r['n_total']:>5}  "
                f"inc={r['n_include']:>4} ({r['inclusion_pct']:>5.1f}%){flag}"
            )

        return {
            "total_reviews": len(reviews),
            "total_papers": total_papers,
            "avg_inclusion_pct": avg_pct,
            "reviews": reviews,
        }


# ══════════════════════════════════════════════════════════════════════════════
# TRAIN/VAL/TEST SPLIT
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class SynergySplitter:
    """
    Module 2::Training::SynergySplitter
    Splits at REVIEW level, not paper level.
    DATA IN:  auditResult, valFrac, testFrac, seed
    DATA OUT: dict: { "train": [...], "val": [...], "test": [...] }
    """

    auditResult: dict
    valFrac: float = 0.15
    testFrac: float = 0.15
    seed: int = 42

    def split(self) -> Dict[str, List[str]]:
        ids = [r["review_id"] for r in self.auditResult["reviews"]]
        rng = random.Random(self.seed)
        rng.shuffle(ids)

        n_test = max(1, int(len(ids) * self.testFrac))
        n_val = max(1, int(len(ids) * self.valFrac))

        test_ids = ids[:n_test]
        val_ids = ids[n_test : n_test + n_val]
        train_ids = ids[n_test + n_val :]

        print(f"\n=== SYNERGY Split (seed={self.seed}) ===")
        print(f"Train: {len(train_ids)} reviews")
        print(f"Val:   {len(val_ids)} reviews")
        print(f"Test:  {len(test_ids)} reviews")

        return {"train": train_ids, "val": val_ids, "test": test_ids}


# ══════════════════════════════════════════════════════════════════════════════
# FINE-TUNE SPECTER2
# ══════════════════════════════════════════════════════════════════════════════


class SynergyTrainer:
    """
    Module 2::Training::SynergyTrainer
    Run ONCE offline. Saves fine-tuned SPECTER2 to outputDir.
    DATA IN:  synergyDir, trainIds, valIds
    DATA OUT: outputDir/ — HuggingFace model directory
    """

    def __init__(
        self,
        synergyDir: str = "./synergy_data/",
        outputDir: str = "./specter2_screening/",
        baseModel: str = "allenai/specter2_base",
        trainIds: Optional[List[str]] = None,
        valIds: Optional[List[str]] = None,
        negRatio: int = 3,
        epochs: int = 3,
        batchSize: int = 16,
        lr: float = 2e-5,
        warmupSteps: int = 100,
    ):
        self.synergyDir = synergyDir
        self.outputDir = outputDir
        self.baseModel = baseModel
        self.trainIds = trainIds
        self.valIds = valIds
        self.negRatio = negRatio
        self.epochs = epochs
        self.batchSize = batchSize
        self.lr = lr
        self.warmupSteps = warmupSteps

    def run(self) -> None:
        from sentence_transformers import SentenceTransformer, InputExample, losses
        from torch.utils.data import DataLoader

        df = self._loadSynergy()
        print(f"Loaded {len(df)} papers across {df['review_id'].nunique()} reviews")

        train_df = df[df["review_id"].isin(self.trainIds)] if self.trainIds else df
        examples = self._buildPairs(train_df)
        print(f"Built {len(examples)} contrastive training pairs")

        model = SentenceTransformer(self.baseModel)
        loader = DataLoader(examples, shuffle=True, batch_size=self.batchSize)
        loss_fn = losses.CosineSimilarityLoss(model)
        evaluator = None

        if self.valIds:
            val_df = df[df["review_id"].isin(self.valIds)]
            evaluator = self._buildEvaluator(val_df)

        model.fit(
            train_objectives=[(loader, loss_fn)],
            epochs=self.epochs,
            warmup_steps=self.warmupSteps,
            optimizer_params={"lr": self.lr},
            output_path=self.outputDir,
            evaluator=evaluator,
            evaluation_steps=500 if evaluator else 0,
            save_best_model=True,
            show_progress_bar=True,
        )
        print(f"Fine-tuned model saved to {self.outputDir}")

    def _loadSynergy(self) -> pd.DataFrame:
        path = Path(self.synergyDir)
        dfs = []

        # Scan for review folders
        review_dirs = sorted(
            [d for d in path.iterdir() if d.is_dir() and (d / "labels.csv").exists()]
        )

        if not review_dirs:
            for sub in sorted(path.iterdir()):
                if sub.is_dir():
                    review_dirs.extend(
                        [
                            d
                            for d in sub.iterdir()
                            if d.is_dir() and (d / "labels.csv").exists()
                        ]
                    )

        for review_dir in review_dirs:
            df = _load_review(review_dir)
            if df is not None and not df.empty:
                dfs.append(df)

        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    def _buildPairs(self, df: pd.DataFrame) -> list:
        from sentence_transformers import InputExample

        examples = []
        for _, group in df.groupby("review_id"):
            pos = group[group["label"] == 1]["text"].tolist()
            neg = group[group["label"] == 0]["text"].tolist()
            if len(pos) < 2:
                continue
            for i in range(min(len(pos), 200)):
                for j in range(i + 1, min(len(pos), 200)):
                    examples.append(InputExample(texts=[pos[i], pos[j]], label=1.0))
            for i, p in enumerate(pos[:200]):
                for n in neg[i * self.negRatio : i * self.negRatio + self.negRatio]:
                    examples.append(InputExample(texts=[p, n], label=0.0))
        return examples

    def _buildEvaluator(self, val_df: pd.DataFrame) -> object:
        from sentence_transformers.evaluation import BinaryClassificationEvaluator

        s1, s2, labels = [], [], []
        for _, group in val_df.groupby("review_id"):
            pos = group[group["label"] == 1]["text"].tolist()
            neg = group[group["label"] == 0]["text"].tolist()
            if not pos or not neg:
                continue
            for i in range(min(len(pos) - 1, 50)):
                s1.append(pos[i])
                s2.append(pos[i + 1])
                labels.append(1)
            for i, p in enumerate(pos[:50]):
                for n in neg[i * 2 : i * 2 + 2]:
                    s1.append(p)
                    s2.append(n)
                    labels.append(0)
        return BinaryClassificationEvaluator(s1, s2, labels, name="synergy_val")


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Module 2 training utilities")
    parser.add_argument(
        "--audit", action="store_true", help="Run data audit on SYNERGY"
    )
    parser.add_argument(
        "--split", action="store_true", help="Show train/val/test split"
    )
    parser.add_argument(
        "--train", action="store_true", help="Fine-tune SPECTER2 on SYNERGY"
    )
    parser.add_argument(
        "--synergy",
        default="../../data/doi-10/synergy-dataset-v1.0/",
        help="SYNERGY data dir",
    )
    parser.add_argument(
        "--output", default="./specter2_screening/", help="Model output dir"
    )
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    audit = None
    splits = None

    if args.audit or args.split or args.train:
        audit = SynergyDataAudit(synergyDir=args.synergy).run()

    if args.split or args.train:
        splits = SynergySplitter(auditResult=audit, seed=args.seed).split()

    if args.train:
        SynergyTrainer(
            synergyDir=args.synergy,
            outputDir=args.output,
            trainIds=splits["train"],
            valIds=splits["val"],
            epochs=args.epochs,
            batchSize=args.batch,
        ).run()
