import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
import time
import re

from ai_digest import process_article_with_ai


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
MAX_RESULTS = 10
ABSTRACT_LIMIT = 500


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


def parse_published_at(article):
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    def normalize_to_iso(year_value: str, month_value: str = "", day_value: str = "") -> str:
        year_value = str(year_value or "").strip()
        month_value = str(month_value or "").strip()
        day_value = str(day_value or "").strip()

        if not year_value.isdigit():
            return ""

        year_int = int(year_value)
        month_int = 1
        day_int = 1

        if month_value:
            if month_value.isdigit():
                month_int = max(1, min(int(month_value), 12))
            else:
                month_int = month_map.get(month_value.lower(), 1)

        if day_value and day_value.isdigit():
            day_int = max(1, min(int(day_value), 28))

        return f"{year_int:04d}-{month_int:02d}-{day_int:02d}T00:00:00Z"

    year = get_text(article.find(".//PubDate/Year"))
    month = get_text(article.find(".//PubDate/Month"))
    day = get_text(article.find(".//PubDate/Day"))

    normalized = normalize_to_iso(year, month, day)
    if normalized:
        return normalized

    medline_date = get_text(article.find(".//PubDate/MedlineDate"))
    year_match = re.search(r"\b(\d{4})\b", medline_date or "")
    if year_match:
        return normalize_to_iso(year_match.group(1))

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

    updated_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    for article in root.findall(".//PubmedArticle"):
        pmid = get_text(article.find(".//PMID"))
        title = get_text(article.find(".//ArticleTitle"))
        journal = get_text(article.find(".//Journal/Title"))
        abstract = get_text(article.find(".//Abstract/AbstractText"))
        published_at = parse_published_at(article)

        if not pmid or not title:
            continue

        articles.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "publishedAt": published_at,
            "abstract": abstract[:ABSTRACT_LIMIT],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "category": category,
            "source": "PubMed",
            "updatedAt": updated_at
        })

    return articles


def process_items_with_ai(items):
    processed_items = []

    for index, item in enumerate(items, start=1):
        print(f"AI processing PubMed item {index}/{len(items)}: {item.get('title', '')[:80]}")
        processed_items.append(process_article_with_ai(item))

    return processed_items


def main():
    all_articles = {}

    for category, term in SEARCH_TERMS.items():
        pmids = fetch_pmids(term)
        articles = fetch_articles(pmids, category)

        for article in articles:
            all_articles[article["pmid"]] = article

    result = list(all_articles.values())[:MAX_RESULTS]
    processed_result = process_items_with_ai(result)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(processed_result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(processed_result)} AI-processed PubMed articles")


if __name__ == "__main__":
    main()
