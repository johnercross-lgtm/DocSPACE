#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ai_digest import process_public_health_with_ai
from feed_utils import load_existing_feed, process_incremental_items, run_item_limit
from http_client import urlopen_with_retry


OUT_PATH = Path("data/nszu-feed.json")
CHANNEL_USERNAME = "NSZU_gov"
CHANNEL_URL = f"https://t.me/s/{CHANNEL_USERNAME}"
LIMIT = 20
ABSTRACT_LIMIT = 420
FULL_TEXT_LIMIT = 4000

TOPIC_KEYWORDS = (
    "есоз",
    "ehealth",
    "електронн",
    "декларац",
    "направлен",
    "пакет медичних гарантій",
    "пмг",
    "відкриті дані",
    "відкритих даних",
    "контрактуван",
    "реімбурсац",
    "програма медичних гарантій",
    "медгарантій",
    "кабінет пацієнта",
)


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urlopen_with_retry(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def normalize_text(text: str) -> str:
    text = re.sub(r"<br\\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def strip_leading_noise(text: str) -> str:
    # Remove decorative emoji/hashtags and normalize to a neutral feed style.
    value = re.sub(r"^[#\u2600-\U0001FAFF\s]+", "", text).strip()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_url(url: str) -> str:
    if not url:
        return ""
    value = html.unescape(url).strip().strip("'").strip('"')
    if value.startswith("//"):
        return "https:" + value
    return value


def split_message_blocks(page: str) -> list[str]:
    parts = re.split(r'<div class="tgme_widget_message_wrap', page)
    return ['<div class="tgme_widget_message_wrap' + raw for raw in parts[1:]]


def is_target_topic(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in TOPIC_KEYWORDS)


def extract_title_and_abstract(text: str) -> tuple[str, str, str]:
    clean = strip_leading_noise(text.strip())
    if not clean:
        return "", "", ""

    one_line = re.sub(r"\s+", " ", clean).strip()
    title_parts = re.split(r"(?<=[.!?])\s+", one_line)
    title = (title_parts[0] if title_parts else one_line)[:130].strip()
    abstract = one_line[:320].strip()
    if len(one_line) > ABSTRACT_LIMIT:
        abstract = f"{abstract.rstrip()}…"
    full_text = one_line[:FULL_TEXT_LIMIT].strip()
    return title, abstract, full_text


def deduplicate_by_url(items: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def parse_posts(page: str) -> list[dict]:
    posts: list[dict] = []
    blocks = split_message_blocks(page)
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for block in blocks:
        link_match = re.search(r'<a class="tgme_widget_message_date" href="([^"]+)"', block)
        text_match = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, flags=re.DOTALL)
        time_match = re.search(r'<time datetime="([^"]+)"', block)

        if not link_match:
            continue

        url = normalize_url(link_match.group(1))
        if not url:
            continue

        raw_text = normalize_text(text_match.group(1)) if text_match else ""
        if len(raw_text) < 30:
            continue
        if not is_target_topic(raw_text):
            continue

        title, abstract, full_text = extract_title_and_abstract(raw_text)
        if not title or not abstract:
            continue

        posts.append(
            {
                "title": title,
                "abstract": abstract,
                "url": url,
                "source": "НСЗУ",
                "category": "health_system_policy",
                "publishedAt": (time_match.group(1).replace("+00:00", "Z") if time_match else updated_at),
                "updatedAt": updated_at,
                "originalTitle": title,
                "originalAbstract": full_text,
                "fullText": full_text,
                "keyPoints": [],
                "practicalTakeaway": "",
                "specialty": "сімейна медицина",
                "tags": ["НСЗУ", "ЕСОЗ", "медичні гарантії"],
                "priorityScore": 7,
                "aiProcessed": False,
                "aiModel": "",
            }
        )

    deduped = deduplicate_by_url(posts)
    deduped.sort(key=lambda item: item.get("publishedAt", ""), reverse=True)
    return deduped[:LIMIT]


def process_items_with_ai(items: list[dict]) -> list[dict]:
    processed: list[dict] = []
    for index, item in enumerate(items, start=1):
        print(f"AI processing NSZU item {index}/{len(items)}: {item.get('title', '')[:80]}")
        ai_input = dict(item)
        full_text = str(ai_input.get("fullText") or ai_input.get("abstract") or "").strip()
        if full_text:
            ai_input["abstract"] = full_text
            ai_input["originalAbstract"] = full_text

        enriched = process_public_health_with_ai(ai_input)

        # Keep full readable body in feed; AI enriches title/key points/tags.
        if full_text:
            enriched["abstract"] = full_text
            enriched["originalAbstract"] = full_text

        enriched["source"] = "НСЗУ"
        # Keep a distinct category for NSZU system-level content.
        enriched["category"] = "health_system_policy"
        enriched.pop("fullText", None)
        processed.append(enriched)
    return processed


def write_feed(items: list[dict]) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    try:
        page = fetch_html(CHANNEL_URL)
    except Exception as error:
        print(f"[warn] failed to fetch NSZU channel: {error}; keeping existing file unchanged")
        return 1

    items = parse_posts(page)
    if not items:
        print("[warn] no NSZU items found by topic filter; keeping existing file unchanged")
        return 0

    processed, items_processed = process_incremental_items(
        candidates=items,
        existing=load_existing_feed(OUT_PATH),
        processor=process_items_with_ai,
        max_items_per_run=run_item_limit(LIMIT),
        feed_limit=LIMIT,
        reprocess_existing=lambda item: not item.get("aiProcessed", False),
    )
    if not processed:
        print("[warn] incremental merge produced no NSZU items; keeping existing file unchanged")
        return 0
    write_feed(processed)
    print(f"Saved {len(processed)} NSZU feed items to {OUT_PATH}; new_items_processed={items_processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
