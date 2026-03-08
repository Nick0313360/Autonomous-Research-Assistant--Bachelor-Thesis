"""
MODULE 1 — Search and Iterative Refinement
------------------------------------------

This module implements the PRISMA Identification stage.

Pipeline:
1. Run database searches
2. Merge results
3. Deduplicate
4. Log statistics
5. Repeat for iterative refinement

Output:
- Clean list of unique papers
- PRISMA search statistics
"""

from pubmed_connector import search as pubmed_search
from semantic_connector import search as semantic_search
from deduplicator import deduplicate


def run_search_iteration(query):

    print("\n====================================")
    print("Running search iteration")
    print("Query:", query)
    print("====================================")

    pubmed = pubmed_search(query, 200)
    semantic = semantic_search(query, 300)

    print("\nSearch Results:")
    print("PubMed:", len(pubmed))
    print("Semantic Scholar:", len(semantic))

    combined = pubmed + semantic

    print("Combined results:", len(combined))

    unique, stats = deduplicate(combined)

    print("\nDeduplication:")
    print("DOI duplicates removed:", stats["doi_duplicates"])
    print("Title duplicates removed:", stats["title_duplicates"])

    print("Unique papers after deduplication:", len(unique))

    return unique


def iterative_search(initial_query, iterations=2):

    all_papers = []

    current_query = initial_query

    for i in range(iterations):

        print("\n\nITERATION", i + 1)

        papers = run_search_iteration(current_query)

        all_papers.extend(papers)

        all_papers, stats = deduplicate(all_papers)

        print("\nMerged unique papers so far:", len(all_papers))

        # Placeholder for LLM query expansion
        # For now we simulate manual expansion
        if i == 0:
            current_query = (
                initial_query +
                " OR evidence synthesis OR literature screening"
            )

    return all_papers


def main():

    initial_query = (
        "artificial intelligence systematic review automation"
    )

    papers = iterative_search(initial_query)

    print("\n\nFINAL IDENTIFICATION RESULTS")
    print("Total unique papers:", len(papers))

    print("\nSample papers:\n")

    for i, p in enumerate(papers[:10]):
        print(f"{i+1}. {p['title']} ({p['source']})")


if __name__ == "__main__":
    main()