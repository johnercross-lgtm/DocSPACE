import os

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

if not token:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

print("TELEGRAM_BOT_TOKEN is available")
