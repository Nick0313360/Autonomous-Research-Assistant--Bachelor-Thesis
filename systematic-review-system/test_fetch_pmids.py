"""
Smoke test for PubMedConnector.fetch_by_pmids.

Run from the systematic-review-system directory:
    python test_fetch_pmids.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from tier1_search.pubmed_connector import PubMedConnector


async def test() -> None:
    # CD008874 known included PMIDs from CLEF-TAR
    test_pmids = ["16897682", "19963188", "21975617"]
    conn = PubMedConnector()
    result = await conn.fetch_by_pmids(test_pmids)
    for pmid, data in result.items():
        print(f"{pmid}: title={data['title'][:60]}...")
        print(f"       abstract_len={len(data['abstract'])}")
    assert len(result) == 3, f"Expected 3 got {len(result)}"
    assert all(data["title"] for data in result.values()), "Empty title found"
    print("PASS")


asyncio.run(test())
