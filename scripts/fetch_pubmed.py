import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
import time

SEARCH_TERM = "pediatrics"
OUT_PATH = Path("data/pubmed-feed.json")
MAX_RESULTS = 5


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(element):
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def fetch_pmids():
    encoded = urllib.parse.quote(SEARCH_TERM)
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={encoded}&retmax={MAX_RESULTS}&sort=date&retmode=json"
    )
    data = get_json(url)
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_articles(pmids):
    if not pmids:
        return []

    time.sleep(1)  # пауза чтобы не словить блок

    ids = ",".join(pmids)
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={ids}&retmode=xml"
    )

    with urllib.request.urlopen(url, timeout=30) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    articles = []

    for article in root.findall(".//PubmedArticle"):
        pmid = get_text(article.find(".//PMID"))
        title = get_text(article.find(".//ArticleTitle"))
        journal = get_text(article.find(".//Journal/Title"))
        abstract = get_text(article.find(".//Abstract/AbstractText"))

        year = get_text(article.find(".//PubDate/Year"))

        if not pmid or not title:
            continue

        articles.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "publishedAt": year,
            "abstract": abstract[:400],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "category": "pediatrics",
            "source": "PubMed",
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return articles


def main():
    pmids = fetch_pmids()
    articles = fetch_articles(pmids)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(articles)} articles")


if __name__ == "__main__":
    main()
