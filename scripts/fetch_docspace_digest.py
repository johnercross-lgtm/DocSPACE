import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
import re
import html
import time

OUT_PATH = Path("data/docspace-digest-feed.json")
IMAGE_DIR = Path("data/docspace-digest-images")

CHANNEL_USERNAME = "docspace_digest"
URL = f"https://t.me/s/{CHANNEL_USERNAME}?nocache={int(time.time())}"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

REPO_FULL_NAME = os.environ.get("GITHUB_REPOSITORY", "johnercross-lgtm/DocSPACE")
REF_NAME = os.environ.get("GITHUB_REF_NAME", "main")
RAW_IMAGE_BASE_URL = (
    f"https://raw.githubusercontent.com/{REPO_FULL_NAME}/{REF_NAME}/data/docspace-digest-images"
)


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
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
        "Powered by DocSPACE",
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


def extract_message_id(url):
    if not url:
        return ""

    return url.rstrip("/").split("/")[-1]


def extract_image_url(block):
    photo_wraps = re.findall(
        r'<a[^>]+class="[^"]*tgme_widget_message_photo_wrap[^"]*"[^>]*>',
        block,
        flags=re.DOTALL,
    )

    for wrap in photo_wraps:
        style_match = re.search(
            r'style="([^"]+)"',
            wrap,
            flags=re.DOTALL,
        )

        if not style_match:
            continue

        style = style_match.group(1)

        image_match = re.search(
            r'background-image:\s*url\([\'"]?([^\'")]+)[\'"]?\)',
            style,
            flags=re.DOTALL,
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


def telegram_api_call(method, params=None):
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

    params = params or {}
    query = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    if query:
        url += "?" + query

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DocSPACE Digest Fetcher/1.0"},
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")

    return payload["result"]


def download_telegram_file(file_path):
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DocSPACE Digest Fetcher/1.0"},
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def choose_best_photo(photo_sizes):
    if not photo_sizes:
        return None

    def score(photo):
        file_size = photo.get("file_size") or 0
        pixels = (photo.get("width") or 0) * (photo.get("height") or 0)
        return (file_size, pixels)

    return max(photo_sizes, key=score)


def extension_from_file_path(file_path, fallback):
    suffix = Path(file_path or "").suffix.lower()

    if suffix:
        return suffix

    return fallback


def extension_from_document(document, fallback=".bin"):
    file_name = document.get("file_name") or ""
    mime_type = document.get("mime_type") or ""

    suffix = Path(file_name).suffix.lower()

    if suffix:
        return suffix

    if mime_type == "image/png":
        return ".png"

    if mime_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"

    if mime_type == "image/webp":
        return ".webp"

    return fallback


def public_image_url(filename):
    return f"{RAW_IMAGE_BASE_URL}/{urllib.parse.quote(filename)}"


def save_digest_image(message_id, kind, data, extension):
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    safe_extension = extension if extension.startswith(".") else f".{extension}"
    filename = f"docspace_digest_{message_id}_{kind}{safe_extension}"
    path = IMAGE_DIR / filename

    path.write_bytes(data)

    print(
        f"[DocSPACE Digest] saved image message_id={message_id} "
        f"kind={kind} bytes={len(data)} path={path}"
    )

    return public_image_url(filename)


def get_telegram_file_data(file_id):
    file_info = telegram_api_call("getFile", {"file_id": file_id})
    file_path = file_info.get("file_path")

    if not file_path:
        return None, ""

    data = download_telegram_file(file_path)
    return data, file_path


def extract_bot_image_for_message(message):
    message_id = str(message.get("message_id") or "")
    document = message.get("document")
    photo_sizes = message.get("photo") or []

    if document:
        mime_type = document.get("mime_type") or ""

        if mime_type.startswith("image/"):
            file_id = document.get("file_id")

            if file_id:
                print(
                    f"[DocSPACE Digest] document image found "
                    f"message_id={message_id} mime={mime_type} "
                    f"bytes={document.get('file_size')}"
                )

                data, file_path = get_telegram_file_data(file_id)

                if data:
                    extension = extension_from_document(document, ".bin")
                    return save_digest_image(message_id, "document", data, extension)

    if photo_sizes:
        best = choose_best_photo(photo_sizes)

        if best:
            file_id = best.get("file_id")

            print(
                f"[DocSPACE Digest] photo found message_id={message_id} "
                f"selected={best.get('width')}x{best.get('height')} "
                f"bytes={best.get('file_size')}"
            )

            if file_id:
                data, file_path = get_telegram_file_data(file_id)

                if data:
                    extension = extension_from_file_path(file_path, ".jpg")
                    size_part = f"{best.get('width')}x{best.get('height')}"
                    return save_digest_image(message_id, f"photo_{size_part}", data, extension)

    return ""


def build_bot_image_map():
    if not BOT_TOKEN:
        print("[DocSPACE Digest] TELEGRAM_BOT_TOKEN not provided, using HTML image fallback")
        return {}

    try:
        webhook = telegram_api_call("getWebhookInfo")
        webhook_url = webhook.get("url") or ""

        if webhook_url:
            print(
                "[DocSPACE Digest] Telegram webhook is active, "
                "skipping getUpdates and using HTML image fallback"
            )
            return {}

        updates = telegram_api_call(
            "getUpdates",
            {
                "limit": 100,
                "timeout": 0,
                "allowed_updates": json.dumps(["channel_post", "edited_channel_post"]),
            },
        )

    except Exception as error:
        print(f"[DocSPACE Digest] Telegram Bot API unavailable: {error}")
        return {}

    image_map = {}

    print(f"[DocSPACE Digest] Telegram updates count={len(updates)}")

    for update in updates:
        message = update.get("channel_post") or update.get("edited_channel_post")

        if not message:
            continue

        chat = message.get("chat", {})
        username = (chat.get("username") or "").lower()

        if username != CHANNEL_USERNAME.lower():
            continue

        message_id = str(message.get("message_id") or "")

        if not message_id:
            continue

        try:
            image_url = extract_bot_image_for_message(message)

            if image_url:
                image_map[message_id] = image_url

        except Exception as error:
            print(
                f"[DocSPACE Digest] failed to extract bot image "
                f"message_id={message_id}: {error}"
            )

    print(f"[DocSPACE Digest] Bot images mapped={len(image_map)}")

    return image_map


def parse_posts(page):
    posts = []
    seen = set()

    blocks = split_message_blocks(page)

    for block in blocks:
        link_match = re.search(
            r'<a class="tgme_widget_message_date" href="([^"]+)"',
            block,
        )

        text_match = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block,
            flags=re.DOTALL,
        )

        time_match = re.search(
            r'<time datetime="([^"]+)"',
            block,
        )

        if not link_match:
            continue

        url = normalize_url(link_match.group(1))

        if url in seen:
            continue

        seen.add(url)

        message_id = extract_message_id(url)
        text = ""

        if text_match:
            text = clean_text(text_match.group(1))
            text = normalize_digest_text(text)

        image_url = extract_image_url(block)

        title = "DocSPACE Medical Digest"

        if text:
            title = text.split("\n")[0].strip()[:140]

        posts.append(
            {
                "_messageId": message_id,
                "id": f"docspace_digest_{message_id}",
                "type": "docspace_digest",
                "title": title,
                "abstract": text[:1200],
                "imageUrl": image_url,
                "url": url,
                "source": "DocSPACE Medical Digest",
                "category": "editorial_digest",
                "publishedAt": time_match.group(1) if time_match else "",
                "updatedAt": datetime.utcnow().isoformat() + "Z",
            }
        )

    return posts[:20]


def main():
    page = fetch_html(URL)
    posts = parse_posts(page)
    bot_image_map = build_bot_image_map()

    final_posts = []

    for post in posts:
        message_id = post.get("_messageId") or ""

        if message_id in bot_image_map:
            post["imageUrl"] = bot_image_map[message_id]
            print(f"[DocSPACE Digest] using bot image for message_id={message_id}")

        post.pop("_messageId", None)

        if len(post.get("abstract", "")) < 10 and not post.get("imageUrl"):
            continue

        final_posts.append(post)

    print(f"Parsed {len(final_posts)} posts")
    print(f"Posts with images: {sum(1 for post in final_posts if post.get('imageUrl'))}")

    if len(final_posts) == 0:
        raise RuntimeError("No posts parsed. Keeping old feed untouched.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(
        json.dumps(final_posts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved {len(final_posts)} posts")


if __name__ == "__main__":
    main()
