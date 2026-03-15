import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

URL = "https://api.semanticscholar.org/graph/v1/paper/search"

def search(query, limit=500):
    papers = []
    batch_size = 100
    offset = 0
    
    print(f"🔍 Searching Semantic Scholar for: {query}")
    
    while offset < limit:
        params = {
            "query": query,
            "limit": min(batch_size, limit - offset),
            "offset": offset,
            "fields": "title,abstract,year,citationCount,externalIds"
        }
        
        # This header format works with your key
        headers = {"api-key": API_KEY}
        
        try:
            r = requests.get(URL, params=params, headers=headers, timeout=15)
            
            if r.status_code == 200:
                data = r.json()
                
                for p in data.get("data", []):
                    if p.get("title"):
                        papers.append({
                            "title": p.get("title"),
                            "abstract": p.get("abstract"),
                            "doi": p.get("externalIds", {}).get("DOI"),
                            "year": p.get("year"),
                            "citation_count": p.get("citationCount"),
                            "source": "semantic_scholar"
                        })
                
                print(f"   ✓ Got {len(data.get('data', []))} papers")
                
                if len(data.get("data", [])) < batch_size:
                    break
                    
            elif r.status_code == 429:
                print(f"   ⏳ Rate limit hit. Waiting 2 seconds...")
                time.sleep(2)
                continue
                
            else:
                print(f"   ❌ Error {r.status_code}")
                break
            
            offset += batch_size
            time.sleep(1)  # Critical: 1 second between requests
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            break
    
    print(f"✅ Found {len(papers)} papers")
    return papers