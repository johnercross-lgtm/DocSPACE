import json
import urllib.request
from pathlib import Path
from datetime import datetime
import re
import html

OUT_PATH = Path("data/ukrainian-news-feed.json")
URL = "https://t.me/s/mozofficial"


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def clean_text(text):
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def parse_posts(page):
    posts = []
    blocks = re.findall(
        r'<div class="tgme_widget_message_wrap.*?</div>\s*</div>',
        page,
        flags=re.DOTALL
    )

    for block in blocks:
        link_match = re.search(
            r'<a class="tgme_widget_message_date" href="([^"]+)"',
            block
        )
        text_match = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block,
            flags=re.DOTALL
        )
        time_match = re.search(
            r'<time datetime="([^"]+)"',
            block
        )

        if not link_match or not text_match:
            continue

        text = clean_text(text_match.group(1))

        if len(text) < 40:
            continue

        title = text.split("\n")[0][:140]

        posts.append({
            "title": title,
            "abstract": text[:500],
            "url": link_match.group(1),
            "source": "МОЗ України",
            "category": "official_health_news",
            "publishedAt": time_match.group(1) if time_match else "",
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return posts[:20]


def main():
    page = fetch_html(URL)
    news = parse_posts(page)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(news, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(news)} MOZ Telegram posts")


if __name__ == "__main__":
    main()
