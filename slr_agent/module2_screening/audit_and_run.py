import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

ROOT = "data/doi-10/synergy-dataset-v1.0"
PLOT_DIR = "plots"
REPORT_DIR = "reports"

os.makedirs(PLOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

sns.set_theme(style="whitegrid", context="paper")


# -------------------------------
# LOAD DATA
# -------------------------------
def load_synergy(root_path):
    all_data = []

    for review in os.listdir(root_path):
        review_path = os.path.join(root_path, review)

        if not os.path.isdir(review_path):
            continue

        labels_file = os.path.join(review_path, "labels.csv")
        if not os.path.exists(labels_file):
            continue

        df = pd.read_csv(labels_file)

        cols = {c.lower(): c for c in df.columns}

        def find(names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        label_col = find(["label", "included", "label_included", "included_final"])

        if label_col is None:
            print(f"[SKIP] {review}")
            continue

        labels = pd.to_numeric(df[label_col], errors="coerce")

        df_clean = pd.DataFrame({
            "review": review,
            "label": labels
        }).dropna()

        all_data.append(df_clean)

        print(f"[OK] {review} | {len(df_clean)} rows")

    return pd.concat(all_data, ignore_index=True)


# -------------------------------
# AUDIT
# -------------------------------
def audit(df):
    results = []

    for review, g in df.groupby("review"):
        total = len(g)
        included = (g["label"] == 1).sum()
        excluded = (g["label"] == 0).sum()

        ratio = included / total if total > 0 else 0
        imbalance = excluded / included if included > 0 else np.inf

        severity = (
            "EXTREME" if ratio < 0.01 else
            "HIGH" if ratio < 0.05 else
            "MODERATE"
        )

        results.append({
            "review": review,
            "total": total,
            "included": included,
            "excluded": excluded,
            "include_ratio": ratio,
            "imbalance_ratio": imbalance,
            "severity": severity
        })

    return pd.DataFrame(results)


# -------------------------------
# VISUALIZATION
# -------------------------------
def save_fig(name):
    plt.tight_layout()
    plt.savefig(f"{PLOT_DIR}/{name}.png", dpi=300)
    plt.close()


def visualize(audit_df, df):

    # Dataset size
    plt.figure(figsize=(10, 5))
    sns.barplot(data=audit_df.sort_values("total", ascending=False),
                x="review", y="total", palette="viridis")
    plt.xticks(rotation=90)
    plt.ylabel("Number of Papers")
    plt.title("Dataset Size per Review")
    save_fig("dataset_size_per_review")

    # Inclusion rate
    plt.figure(figsize=(10, 5))
    sns.barplot(data=audit_df.sort_values("include_ratio"),
                x="review", y="include_ratio", palette="magma")
    plt.xticks(rotation=90)
    plt.ylabel("Inclusion Rate")
    plt.title("Inclusion Rate per Review")
    save_fig("inclusion_rate_per_review")

    # Inclusion distribution
    plt.figure(figsize=(6, 4))
    sns.histplot(audit_df["include_ratio"], bins=20, kde=True)
    plt.xlabel("Inclusion Rate")
    plt.title("Distribution of Inclusion Rates")
    save_fig("inclusion_distribution")

    # Imbalance (log scale)
    plt.figure(figsize=(10, 5))
    sns.barplot(data=audit_df.sort_values("imbalance_ratio"),
                x="review", y="imbalance_ratio", palette="coolwarm")
    plt.yscale("log")
    plt.xticks(rotation=90)
    plt.ylabel("Imbalance Ratio (log scale)")
    plt.title("Class Imbalance per Review")
    save_fig("imbalance_log")

    # Global class distribution
    plt.figure(figsize=(5, 4))
    sns.countplot(data=df, x="label", palette="Set2")
    plt.xticks([0, 1], ["Excluded", "Included"])
    plt.title("Global Class Distribution")
    save_fig("global_class_distribution")

    # Severity distribution
    plt.figure(figsize=(6, 4))
    sns.countplot(data=audit_df, x="severity",
                  order=["EXTREME", "HIGH", "MODERATE"])
    plt.title("Imbalance Severity Across Reviews")
    save_fig("severity_distribution")


# -------------------------------
# TEXT REPORT EXPORT
# -------------------------------
def write_report(df, audit_df):
    total = len(df)
    included = (df["label"] == 1).sum()
    excluded = (df["label"] == 0).sum()

    report_text = f"""
SYNERGY DATASET AUDIT REPORT

Total papers: {total}
Included: {included} ({included/total:.4f})
Excluded: {excluded} ({excluded/total:.4f})
Global imbalance ratio: {excluded/included:.2f}:1

Dataset contains {len(audit_df)} systematic reviews.

Inclusion rate range:
Min: {audit_df['include_ratio'].min():.4f}
Max: {audit_df['include_ratio'].max():.4f}

Dataset size range:
Min: {audit_df['total'].min()}
Max: {audit_df['total'].max()}

Severity distribution:
{audit_df['severity'].value_counts().to_string()}

Key observations:
- Extreme class imbalance dominates most reviews.
- Inclusion rates vary significantly across datasets.
- Dataset is highly heterogeneous and non-i.i.d.
- Labels are separated from textual data (requires merging).
- Suitable for adaptive and retrieval-based ML systems.
"""

    with open(f"{REPORT_DIR}/audit_summary.txt", "w") as f:
        f.write(report_text)

    print(f"[Saved] {REPORT_DIR}/audit_summary.txt")


# -------------------------------
# MAIN
# -------------------------------
if __name__ == "__main__":
    df = load_synergy(ROOT)

    audit_df = audit(df)

    print(audit_df.sort_values("include_ratio"))

    visualize(audit_df, df)

    audit_df.to_csv(f"{REPORT_DIR}/audit_report.csv", index=False)
    write_report(df, audit_df)