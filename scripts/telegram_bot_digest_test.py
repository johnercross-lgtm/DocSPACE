import json
import os
import urllib.parse
import urllib.request

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

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


def main():
    me = api_call("getMe")
    webhook = api_call("getWebhookInfo")

    print(f"Bot username: @{me.get('username')}")
    print(f"Webhook url: {webhook.get('url') or 'none'}")


if __name__ == "__main__":
    main()
