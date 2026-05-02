import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
import time

SEARCH_TERMS = {
    "general_medicine": (
        "cardiology OR gastroenterology OR endocrinology OR neurology OR pediatrics "
        "OR pulmonology OR oncology OR dermatology OR psychiatry OR rheumatology "
        "OR nephrology OR urology OR gynecology OR infectious diseases OR emergency medicine "
        "OR family medicine OR internal medicine OR surgery OR hepatology OR hematology "
        "OR immunology OR pharmacology OR antibiotics OR vaccination OR diabetes "
        "OR hypertension OR obesity OR asthma OR COPD"
    )
}

OUT_PATH = Path("data/pubmed-feed.json")
MAX_RESULTS = 30


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DocSPACE PubMed Feed Bot/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(element):
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def fetch_pmids(term):
    encoded = urllib.parse.quote(term)

    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed"
        f"&term={encoded}"
        f"&retmax={MAX_RESULTS}"
        f"&sort=date"
        f"&retmode=json"
    )

    data = get_json(url)
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_articles(pmids, category):
    if not pmids:
        return []

    time.sleep(2)

    ids = ",".join(pmids)

    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed"
        f"&id={ids}"
        f"&retmode=xml"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DocSPACE PubMed Feed Bot/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
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

        published_at = year

        if month:
            published_at += f"-{month}"
        if day:
            published_at += f"-{day}"

        if not pmid or not title:
            continue

        articles.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "publishedAt": published_at,
            "abstract": abstract[:500],
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
