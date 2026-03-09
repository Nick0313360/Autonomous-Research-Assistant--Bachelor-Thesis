"""
Module 1 — Main Handler
-----------------------

Two modes:
1. Basic search (AI off)
2. Iterative refinement with LLM (AI on)

Usage:
python literature_handler.py         # Basic search
python literature_handler.py --ai    # Run with AI refinement
"""

import argparse
from connectors.pubmed_connector import search as pubmed_search
from connectors.semantic_connector import search as semantic_search
from deduplicator.deduplicator import deduplicate
from refinement.llm_refiner import analyse_query_gaps, expand_query

# -------------------------------------
# Helper functions
# -------------------------------------

def run_basic_search(query, pubmed_limit=50, semantic_limit=3000):
    """
    Basic search: query both databases, merge, deduplicate, print stats
    """
    print("\nRunning basic search with query:\n", query)
    
    pubmed_results = pubmed_search(query, pubmed_limit)
    semantic_results = semantic_search(query, semantic_limit)
    
    print(f"\nResults before deduplication:")
    print(f"PubMed: {len(pubmed_results)}, Semantic Scholar: {len(semantic_results)}")
    
    combined = pubmed_results + semantic_results
    unique, stats = deduplicate(combined)
    
    print(f"\nDeduplication stats:")
    print(f"DOI duplicates removed: {stats['doi_duplicates']}")
    print(f"Title duplicates removed: {stats['title_duplicates']}")
    print(f"Total unique papers: {len(unique)}\n")
    
    return unique


def run_iterative_search(initial_query, max_iterations=3):
    """
    Iterative search with LLM query gap analysis
    """
    all_papers = []
    query = initial_query
    
    for iteration in range(max_iterations):
        print(f"\n========== ITERATION {iteration + 1} ==========")
        results = run_basic_search(query)
        
        all_papers.extend(results)
        all_papers, stats = deduplicate(all_papers)
        print(f"\nTotal unique papers so far: {len(all_papers)}")
        
        # Stop condition: last iteration
        if iteration == max_iterations - 1:
            break
        
        # LLM query refinement
        print("\nRunning LLM gap analysis and query expansion...")
        new_terms = analyse_query_gaps(all_papers, query)
        print("Suggested new terms:", new_terms)
        
        query = expand_query(query, new_terms)
        print("\nExpanded query for next iteration:\n", query)
    
    return all_papers


def main():
    parser = argparse.ArgumentParser(description="Module 1 Literature Search Handler")
    parser.add_argument("--ai", action="store_true", help="Enable iterative LLM refinement")
    
    args = parser.parse_args()
    
    initial_query = "artificial intelligence systematic review automation"
    
    if args.ai:
        print("AI refinement mode enabled.\n")
        papers = run_iterative_search(initial_query)
    else:
        print("Basic search mode (AI OFF).\n")
        papers = run_basic_search(initial_query)
    
    print("\n========== FINAL RESULTS ==========")
    print(f"Total unique papers collected: {len(papers)}\n")
    for i, p in enumerate(papers[:10], 1):
        print(f"{i}) {p['title']} ({p['source']})")


if __name__ == "__main__":
    main()