import os
import urllib.parse
import urllib.request

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]

message = """
🧠 DocSPACE Medical Digest

Тестова автоматична публікація.

• PubMed
• Cochrane
• МОЗ України
• AI digest

Powered by DocSPACE
"""

encoded = urllib.parse.urlencode({
    "chat_id": CHANNEL_ID,
    "text": message
})

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

req = urllib.request.Request(
    url,
    data=encoded.encode("utf-8")
)

with urllib.request.urlopen(req) as response:
    print(response.read().decode())
