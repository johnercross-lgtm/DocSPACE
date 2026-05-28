import json
import os
import urllib.parse
import urllib.request

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_USERNAME = "docspace_digest"

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")


def api_call(method, params=None):
    params = params or {}
    query = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    if query:
        url += "?" + query

    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")

    return payload["result"]


def choose_best_photo(photo_sizes):
    if not photo_sizes:
        return None

    def score(photo):
        file_size = photo.get("file_size") or 0
        pixels = (photo.get("width") or 0) * (photo.get("height") or 0)
        return (file_size, pixels)

    return max(photo_sizes, key=score)


def main():
    me = api_call("getMe")
    webhook = api_call("getWebhookInfo")

    print(f"Bot username: @{me.get('username')}")
    print(f"Webhook url: {webhook.get('url') or 'none'}")

    updates = api_call(
        "getUpdates",
        {
            "limit": 50,
            "timeout": 0,
            "allowed_updates": json.dumps(["channel_post", "edited_channel_post"]),
        },
    )

    print(f"Updates count: {len(updates)}")

    found_posts = 0
    found_photos = 0

    for update in updates:
        message = update.get("channel_post") or update.get("edited_channel_post")

        if not message:
            continue

        chat = message.get("chat", {})
        username = (chat.get("username") or "").lower()

        if username != CHANNEL_USERNAME.lower():
            print(f"Skip other chat: @{username}")
            continue

        found_posts += 1

        message_id = message.get("message_id")
        text = (message.get("caption") or message.get("text") or "").strip()
        photo_sizes = message.get("photo") or []

        print("")
        print("=" * 72)
        print(f"Message id: {message_id}")
        print(f"Text: {text[:140]!r}")

        if not photo_sizes:
            print("No photo")
            continue

        found_photos += 1

        print("Photo sizes:")

        for photo in photo_sizes:
            print(
                f"- {photo.get('width')}x{photo.get('height')} "
                f"bytes={photo.get('file_size')} "
                f"file_id={str(photo.get('file_id'))[:18]}..."
            )

        best = choose_best_photo(photo_sizes)

        print(
            f"Selected: {best.get('width')}x{best.get('height')} "
            f"bytes={best.get('file_size')}"
        )

        file_info = api_call("getFile", {"file_id": best["file_id"]})
        file_path = file_info.get("file_path")

        print(f"Telegram file_path: {file_path}")

        if file_path:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

            with urllib.request.urlopen(file_url, timeout=60) as response:
                data = response.read()

            print(f"Downloaded bytes: {len(data)}")

    print("")
    print("=" * 72)
    print(f"Found channel posts: {found_posts}")
    print(f"Found posts with photos: {found_photos}")


if __name__ == "__main__":
    main()
