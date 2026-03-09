import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def search(query, limit=300):

    papers = []

    batch_size = 100
    offset = 0

    while offset < limit:

        params = {
            "query": query,
            "limit": batch_size,
            "offset": offset,
            "fields": "title,abstract,year,citationCount,openAccessPdf,externalIds"
        }

        headers = {
            "x-api-key": API_KEY
        }

        r = requests.get(URL, params=params, headers=headers)

        if r.status_code == 429:
            print("Rate limit hit. Waiting 10 seconds.")
            time.sleep(10)
            continue

        if r.status_code != 200:
            print("Semantic Scholar error:", r.status_code)
            break

        data = r.json()

        for p in data.get("data", []):

            doi = None
            if p.get("externalIds"):
                doi = p["externalIds"].get("DOI")

            papers.append({
                "title": p.get("title"),
                "abstract": p.get("abstract"),
                "doi": doi,
                "source": "semantic_scholar"
            })

        offset += batch_size
        time.sleep(1)

    return papers