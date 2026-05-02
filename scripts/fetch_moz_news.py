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
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive"
        }
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def clean_text(text):
    text = re.sub(r"\s+", " ", text)
    text = text.replace("&quot;", '"')
    text = text.replace("&amp;", "&")
    text = text.replace("&nbsp;", " ")
    return text.strip()


def parse_news(html):
    items = []
    seen_urls = set()

    matches = re.findall(
        r'href="(/uk/[^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.DOTALL
    )

    for link, raw_title in matches:
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = clean_text(title)

        if len(title) < 20:
            continue

        if any(skip in link for skip in [
            "/uk/contacts",
            "/uk/pro-ministerstvo",
            "/uk/gromadskosti",
            "/uk/poslugi",
            "/uk/dostup-do-publichnoi-informacii"
        ]):
            continue

        full_url = "https://moz.gov.ua" + link

        if full_url in seen_urls:
            continue

        seen_urls.add(full_url)

        items.append({
            "title": title,
            "url": full_url,
            "source": "МОЗ України",
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

    print(f"Saved {len(news)} MOZ news")


if __name__ == "__main__":
    main()
