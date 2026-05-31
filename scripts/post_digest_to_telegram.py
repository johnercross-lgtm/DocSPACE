import json
import os
import urllib.parse
import urllib.request

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

if not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_CHANNEL_ID is empty")

message = """
🧠 DocSPACE Medical Digest

Тестова автоматична публікація.

• PubMed
• Cochrane
• МОЗ України
• НСЗУ
• AI digest

Powered by DocSPACE
""".strip()

encoded = urllib.parse.urlencode({
    "chat_id": CHANNEL_ID,
    "text": message
})

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

req = urllib.request.Request(
    url,
    data=encoded.encode("utf-8"),
    headers={"User-Agent": "DocSPACE Telegram Poster/1.0"}
)

with urllib.request.urlopen(req, timeout=30) as response:
    payload = json.loads(response.read().decode("utf-8"))

if not payload.get("ok"):
    raise RuntimeError(f"Telegram API error: {payload}")

print(json.dumps(payload, ensure_ascii=False, indent=2))
