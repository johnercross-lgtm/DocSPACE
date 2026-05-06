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


def normalize_digest_text(text):
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    brand_lines = {
        "🧠 DocSPACE Medical Digest",
        "DocSPACE Medical Digest",
        "Powered by DocSPACE"
    }

    cleaned = []

    for line in lines:
        if line in brand_lines:
            continue

        cleaned.append(line)

    return "\n\n".join(cleaned).strip()


def normalize_url(url):
    if not url:
        return ""

    url = html.unescape(url)
    url = url.strip().strip("'").strip('"')

    if url.startswith("//"):
        return "https:" + url

    return url


def extract_image_url(block):
    photo_wraps = re.findall(
        r'<a[^>]+class="[^"]*tgme_widget_message_photo_wrap[^"]*"[^>]*>',
        block,
        flags=re.DOTALL
    )

    for wrap in photo_wraps:
        style_match = re.search(
            r'style="([^"]+)"',
            wrap,
            flags=re.DOTALL
        )

        if not style_match:
            continue

        style = style_match.group(1)

        image_match = re.search(
            r'background-image:\s*url\([\'"]?([^\'")]+)[\'"]?\)',
            style,
            flags=re.DOTALL
        )

        if not image_match:
            continue

        image_url = normalize_url(image_match.group(1))
        image_url_lower = image_url.lower()

        bad_fragments = [
            "emoji",
            "avatar",
            "profile_photo",
            "telegram.org/img",
            "tgme/emoji",
            "data:image",
        ]

        if not image_url:
            continue

        if any(bad in image_url_lower for bad in bad_fragments):
            continue

        return image_url

    return ""


def split_message_blocks(page):
    parts = re.split(r'<div class="tgme_widget_message_wrap', page)
    return ['<div class="tgme_widget_message_wrap' + raw for raw in parts[1:]]


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

        if not link_match:
            continue

        url = normalize_url(link_match.group(1))

        if url in seen:
            continue

        seen.add(url)

        text = ""

        if text_match:
            text = clean_text(text_match.group(1))
            text = normalize_digest_text(text)

        image_url = extract_image_url(block)

        if len(text) < 10 and not image_url:
            continue

        title = "DocSPACE Medical Digest"

        if text:
            title = text.split("\n")[0].strip()[:140]

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

    print(f"Parsed {len(posts)} posts")
    print(f"Posts with images: {sum(1 for post in posts if post.get('imageUrl'))}")

    if len(posts) == 0:
        raise RuntimeError("No posts parsed. Keeping old feed untouched.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved {len(posts)} posts")


if __name__ == "__main__":
    main()
