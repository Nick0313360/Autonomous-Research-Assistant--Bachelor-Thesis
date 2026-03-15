from rapidfuzz import fuzz


def deduplicate(papers, similarity_threshold=90):

    unique = []
    seen_doi = set()

    doi_duplicates = 0
    title_duplicates = 0

    # DOI deduplication
    for p in papers:

        doi = p.get("doi")

        if doi and doi in seen_doi:
            doi_duplicates += 1
            continue

        if doi:
            seen_doi.add(doi)

        unique.append(p)

    # Title similarity deduplication
    final = []

    for p in unique:

        duplicate = False

        for existing in final:

            score = fuzz.ratio(
                p["title"].lower(),
                existing["title"].lower()
            )

            if score >= similarity_threshold:
                duplicate = True
                title_duplicates += 1
                break

        if not duplicate:
            final.append(p)

    stats = {
        "doi_duplicates": doi_duplicates,
        "title_duplicates": title_duplicates
    }

    return final, stats