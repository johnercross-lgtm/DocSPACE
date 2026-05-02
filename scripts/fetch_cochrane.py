#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import ssl
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

OUT_PATH = Path("data/cochrane-feed.json")
FEED_URLS = (
    "https://www.cochranelibrary.com/cdsr/reviews/rss",
    "https://www.cochranelibrary.com/rss/latest",
)
TIMEOUT_SECONDS = 30
LIMIT = 20
ABSTRACT_LIMIT = 500


def fetch_xml(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (DocSPACE bot)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, ssl.SSLError):
            insecure_context = ssl._create_unverified_context()
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=insecure_context) as response:
                return response.read()
        raise


def clean_summary(raw_text: str) -> str:
    text = re.sub(r"<br\\s*/?>", "\n", raw_text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > ABSTRACT_LIMIT:
        return f"{text[:ABSTRACT_LIMIT].rstrip()}…"
    return text


def parse_pub_date(raw_value: str) -> datetime:
    if not raw_value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = parsedate_to_datetime(raw_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def parse_items(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    items: list[dict[str, str]] = []
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        published_at = (node.findtext("pubDate") or "").strip()
        description = node.findtext("description") or ""
        summary = clean_summary(description)

        if not title or not url:
            continue

        items.append(
            {
                "title": title,
                "abstract": summary,
                "url": url,
                "source": "Cochrane",
                "category": "evidence_review",
                "publishedAt": published_at,
                "updatedAt": updated_at,
            }
        )

    items.sort(key=lambda item: parse_pub_date(item.get("publishedAt", "")), reverse=True)
    return items[:LIMIT]


def write_feed(items: list[dict[str, str]]) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
