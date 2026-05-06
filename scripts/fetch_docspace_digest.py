import json
import urllib.request
from pathlib import Path
from datetime import datetime
import re
import html
import time

OUT_PATH = Path("data/docspace-digest-feed.json")
URL = f"https://t.me/s/docspace_digest?nocache={int(time.time())}"


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
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
    seen = set()

    blocks = re.split(r'<div class="tgme_widget_message_wrap', page)

    for raw_block in blocks:
        block = '<div class="tgme_widget_message_wrap' + raw_block

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

        url = link_match.group(1).strip()
        text = clean_text(text_match.group(1))

        if len(text) < 20:
            continue

        if url in seen:
            continue

        seen.add(url)

        title = text.split("\n")[0].strip()[:140]

        posts.append({
            "id": url.split("/")[-1],
            "type": "docspace_digest",
            "title": title,
            "abstract": text[:900],
            "url": url,
            "source": "DocSPACE Medical Digest",
            "category": "editorial_digest",
            "publishedAt": time_match.group(1) if time_match else "",
            "updatedAt": datetime.utcnow().isoformat() + "Z"
        })

    return posts[:20]


def main():
    page = fetch_html(URL)
    posts = parse_posts(page)

    print(f"Parsed {len(posts)} DocSPACE digest posts")

    if len(posts) == 0:
        raise RuntimeError("No DocSPACE digest posts parsed. Keeping old feed untouched.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(posts)} DocSPACE digest posts")


if __name__ == "__main__":
    main()
