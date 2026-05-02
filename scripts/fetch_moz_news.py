import json
import urllib.request
from pathlib import Path
from datetime import datetime
import re

OUT_PATH = Path("data/ukrainian-news-feed.json")

URL = "https://moz.gov.ua/uk/ostanni-novini"


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_news(html):
    items = []

    # грубый парсинг ссылок новостей
    matches = re.findall(r'href="(/article/[^"]+)"[^>]*>([^<]+)</a>', html)

    for link, title in matches:
        full_url = "https://moz.gov.ua" + link

        if len(title.strip()) < 10:
            continue

        items.append({
            "title": title.strip(),
            "url": full_url,
            "source": "МОЗ",
            "category": "health_news",
            "publishedAt": "",
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return items[:20]


def main():
    html = fetch_html(URL)
    news = parse_news(html)

    OUT_PATH.write_text(
        json.dumps(news, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(news)} MOZ news")


if __name__ == "__main__":
    main()
