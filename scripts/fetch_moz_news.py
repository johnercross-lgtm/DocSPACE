import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

OUT_PATH = Path("data/ukrainian-news-feed.json")

# RSS НСЗУ
RSS_URL = "https://nszu.gov.ua/rss"


def fetch_rss(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def parse_rss(xml_data):
    root = ET.fromstring(xml_data)
    items = []

    for item in root.findall(".//item"):
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        description = item.findtext("description", default="")

        if not title or not link:
            continue

        items.append({
            "title": title.strip(),
            "url": link.strip(),
            "abstract": description.strip()[:300],
            "source": "НСЗУ",
            "category": "official_health_news",
            "publishedAt": pub_date,
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return items[:20]


def main():
    xml_data = fetch_rss(RSS_URL)
    news = parse_rss(xml_data)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(news, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(news)} NSZU news")


if __name__ == "__main__":
    main()
