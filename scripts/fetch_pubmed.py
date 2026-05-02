import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

SEARCH_TERMS = {
    "pediatrics": "pediatrics",
    "cardiology": "cardiology",
    "diabetes": "diabetes",
    "infectious_diseases": "infectious diseases"
}

OUT_PATH = Path("data/pubmed-feed.json")
MAX_PER_CATEGORY = 10


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(element):
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def fetch_pmids(term):
    encoded = urllib.parse.quote(term)
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={encoded}&retmax={MAX_PER_CATEGORY}&sort=date&retmode=json"
    )
    data = get_json(url)
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_articles(pmids, category):
    if not pmids:
        return []

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
        month = get_text(article.find(".//PubDate/Month"))
        day = get_text(article.find(".//PubDate/Day"))

        published_at = year or ""

        if month:
            published_at += f"-{month}"
        if day:
            published_at += f"-{day}"

        authors = []
        for author in article.findall(".//Author"):
            last = get_text(author.find("LastName"))
            initials = get_text(author.find("Initials"))
            name = f"{last} {initials}".strip()
            if name:
                authors.append(name)

        if not pmid or not title:
            continue

        articles.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "publishedAt": published_at,
            "abstract": abstract[:600],
            "authors": authors[:6],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "category": category,
            "source": "PubMed",
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return articles


def main():
    all_articles = {}

    for category, term in SEARCH_TERMS.items():
        pmids = fetch_pmids(term)
        articles = fetch_articles(pmids, category)

        for article in articles:
            all_articles[article["pmid"]] = article

    result = list(all_articles.values())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(result)} PubMed articles")


if __name__ == "__main__":
    main()
