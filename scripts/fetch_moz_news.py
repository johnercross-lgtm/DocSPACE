import json
import urllib.request
from pathlib import Path
from datetime import datetime
import re

OUT_PATH = Path("data/ukrainian-news-feed.json")

URL = "https://nszu.gov.ua/novini"


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_news(html):
    items = []
    seen = set()

    matches = re.findall(
        r'href="(/novini/[^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.DOTALL
    )

    for link, raw_title in matches:
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = clean(title)

        if len(title) < 20:
            continue

        full_url = "https://nszu.gov.ua" + link

        if full_url in seen:
            continue

        seen.add(full_url)

        items.append({
            "title": title,
            "url": full_url,
            "source": "НСЗУ",
            "category": "official_health_news",
            "publishedAt": "",
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return items[:20]


def main():
    html = fetch_html(URL)
    news = parse_news(html)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(news, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(news)} NSZU news")


if __name__ == "__main__":
    main()
