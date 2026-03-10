"""
PubMed Connector
----------------
Handles communication with the PubMed database using the NCBI Entrez API.

Responsibilities:
- Run a structured query
- Retrieve PubMed IDs
- Fetch metadata for each paper

Returns standardized paper objects used throughout the pipeline.
"""

from Bio import Entrez
import xml.etree.ElementTree as ET

Entrez.email = "your_email@example.com"


def search_pubmed(query, retmax=500):
    """
    Search PubMed and return a list of PubMed IDs
    """

    handle = Entrez.esearch(
        db="pubmed",
        term=query,
        retmax=str(retmax),
        sort="relevance",
        retmode="xml"
    )

    results = Entrez.read(handle)
    return results["IdList"]


def fetch_pubmed_details(id_list):
    """
    Fetch full metadata for PubMed IDs
    """

    if not id_list:
        return []

    ids = ",".join(id_list)

    handle = Entrez.efetch(
        db="pubmed",
        id=ids,
        retmode="xml"
    )

    xml_data = handle.read()
    handle.close()

    root = ET.fromstring(xml_data)

    papers = []

    for article in root.findall(".//PubmedArticle"):

        medline = article.find("MedlineCitation")
        art = medline.find("Article")

        title = art.findtext("ArticleTitle")

        abstract_elem = art.find("Abstract/AbstractText")
        abstract = abstract_elem.text if abstract_elem is not None else ""

        doi = None
        for el in article.findall(".//ArticleId"):
            if el.attrib.get("IdType") == "doi":
                doi = el.text

        papers.append({
            "title": title,
            "abstract": abstract,
            "doi": doi,
            "source": "pubmed"
        })

    return papers


def search(query, retmax=500):
    ids = search_pubmed(query, retmax)
    return fetch_pubmed_details(ids)