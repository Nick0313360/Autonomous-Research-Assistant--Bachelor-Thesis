"""
LLM Query Refinement Module
---------------------------

This module performs the iterative refinement step in Module 1.

Responsibilities:
1. Analyse titles and abstracts of retrieved papers
2. Detect missing concepts / keywords
3. Suggest additional search terms
4. Expand the original query
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

def extract_sample(papers, n=20):
    """
    Select a representative sample of papers
    to send to the LLM.

    We take the first N papers (sorted by relevance).
    """

    return papers[:n]


def build_context(sample_papers):
    """
    Format paper titles + abstracts
    into a prompt-friendly block.
    """

    text_block = ""

    for p in sample_papers:

        text_block += f"\nTitle: {p['title']}\n"

        if p.get("abstract"):
            text_block += f"Abstract: {p['abstract']}\n"

    return text_block


def analyse_query_gaps(papers, original_query):
    """
    Ask the LLM to identify missing concepts
    from the search query.
    """

    sample = extract_sample(papers)

    context = build_context(sample)

    prompt = f"""
You are an expert systematic review search strategist.

The following titles and abstracts were retrieved
from a literature search.

Original query:
{original_query}

Your task:
Identify important keywords, concepts, or methods
that appear in these papers but are missing
from the original search query.

Return between 5 and 10 search terms.

Return ONLY a comma separated list.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You are a systematic review search expert."},
            {"role": "user", "content": prompt + "\n\nPapers:\n" + context}
        ]
    )

    keywords = response.choices[0].message.content.strip()

    return keywords


def expand_query(original_query, new_terms):
    """
    Build a new expanded query.
    """

    terms = [t.strip() for t in new_terms.split(",")]

    expanded = original_query + " OR " + " OR ".join(terms)

    return expanded