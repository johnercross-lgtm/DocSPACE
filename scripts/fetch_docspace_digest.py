import json
import urllib.request
from pathlib import Path
from datetime import datetime
import re
import html
import time

OUT_PATH = Path("data/docspace-digest-feed.json")
CHANNEL_USERNAME = "docspace_digest"
URL = f"https://t.me/s/{CHANNEL_USERNAME}?nocache={int(time.time())}"


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
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


def normalize_url(url):
    if not url:
        return ""

    url = html.unescape(url).strip()
    url = url.strip("'\" ")

    if url.startswith("//"):
        return "https:" + url

    return url


def extract_image_url(block):
    patterns = [
        r"""background-image:\s*url\(['"]?([^'")]+)['"]?\)""",
        r"""<a[^>]+class="[^"]*tgme_widget_message_photo_wrap[^"]*"[^>]+style="[^"]*background-image:\s*url\(['"]?([^'")]+)['"]?\)""",
        r"""<img[^>]+src="([^"]+)"""",
        r"""<img[^>]+data-src="([^"]+)"""",
        r"""data-src="([^"]+)"""",
    ]

    for pattern in patterns:
        match = re.search(pattern, block, flags=re.DOTALL)

        if match:
            image_url = normalize_url(match.group(1))

            if image_url and not image_url.startswith("data:"):
                return image_url

    return ""


def split_message_blocks(page):
    parts = re.split(r'<div class="tgme_widget_message_wrap', page)
    blocks = []

    for raw in parts[1:]:
        blocks.append('<div class="tgme_widget_message_wrap' + raw)

    return blocks


def parse_posts(page):
    posts = []
    seen = set()

    blocks = split_message_blocks(page)

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

        image_url = extract_image_url(block)

        if not link_match:
            continue

        url = normalize_url(link_match.group(1))

        text = ""
        if text_match:
            text = clean_text(text_match.group(1))

        if len(text) < 10 and not image_url:
            continue

        if url in seen:
            continue

        seen.add(url)

        title = text.split("\n")[0].strip()[:140] if text else "DocSPACE Medical Digest"

        posts.append({
            "id": f"docspace_digest_{url.split('/')[-1]}",
            "type": "docspace_digest",
            "title": title,
            "abstract": text[:1200],
            "imageUrl": image_url,
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
    print(f"Posts with images: {sum(1 for post in posts if post.get('imageUrl'))}")

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
