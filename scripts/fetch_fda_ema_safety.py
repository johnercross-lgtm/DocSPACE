#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from ai_digest import process_public_health_with_ai

OUT_PATH = Path("data/fda-ema-safety-feed.json")
LIMIT = 24
TIMEOUT_SECONDS = 30

SOURCES = (
    (
        "FDA",
        "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/rss.xml",
    ),
    (
        "EMA",
        "https://www.ema.europa.eu/en/news.xml",
    ),
)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DocSPACE bot)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, ssl.SSLError):
            insecure_context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=insecure_context) as response:
                return response.read().decode("utf-8", errors="ignore")
        raise


def normalize_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_iso8601(value: str | None) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not value:
        return now

    raw = value.strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            continue
    return now


def classify_specialty(text: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["vaccine", "infect", "covid", "flu", "virus", "бактері", "інфекц"]):
        return "інфекційні хвороби"
    if any(k in lowered for k in ["heart", "cardio", "qt", "arrhythm", "кардіо"]):
        return "кардіологія"
    return "фармакотерапія"


def parse_feed(source_name: str, xml_payload: str) -> list[dict]:
    root = ET.fromstring(xml_payload)
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    items: list[dict] = []
    seen_urls: set[str] = set()

    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for node in nodes:
        title = normalize_text(node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title") or "")

        link = node.findtext("link") or ""
        if not link:
            atom_link = node.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = atom_link.attrib.get("href", "")
        link = link.strip()

        summary = normalize_text(
            node.findtext("description")
            or node.findtext("summary")
            or node.findtext("{http://www.w3.org/2005/Atom}summary")
            or ""
        )

        published_raw = (
            node.findtext("pubDate")
            or node.findtext("published")
            or node.findtext("{http://www.w3.org/2005/Atom}published")
            or node.findtext("updated")
            or node.findtext("{http://www.w3.org/2005/Atom}updated")
        )
        published_at = to_iso8601(published_raw)

        if not title or not link:
            continue
        if link in seen_urls:
            continue
        seen_urls.add(link)

        raw_text_for_ai = summary if summary else title
        specialty = classify_specialty(f"{title} {summary}")

        items.append(
            {
                "title": title,
                "abstract": raw_text_for_ai,
                "url": link,
                "source": source_name,
                "category": "drug_safety",
                "publishedAt": published_at,
                "updatedAt": updated_at,
                "originalTitle": title,
                "originalAbstract": raw_text_for_ai,
                "keyPoints": [],
                "practicalTakeaway": "",
                "specialty": specialty,
                "tags": ["drug safety", "pharmacovigilance", source_name],
                "priorityScore": 8,
                "aiProcessed": False,
                "aiModel": "",
            }
        )

    return items


def process_items_with_ai(items: list[dict]) -> list[dict]:
    processed: list[dict] = []
    for index, item in enumerate(items, start=1):
        print(f"AI processing safety item {index}/{len(items)}: {item.get('title', '')[:80]}")

        enriched = process_public_health_with_ai(dict(item))
        enriched["category"] = "drug_safety"
        enriched["source"] = item.get("source", "FDA/EMA")

        # Copyright-safe: keep concise transformed summary only, no full-text replication.
        concise = str(enriched.get("abstract") or "").strip()
        if len(concise) > 700:
            concise = concise[:700].rstrip() + "…"
        enriched["abstract"] = concise

        processed.append(enriched)

    return processed


def main() -> int:
    collected: list[dict] = []

    for source_name, feed_url in SOURCES:
        try:
            xml_payload = fetch_text(feed_url)
            parsed = parse_feed(source_name, xml_payload)
            print(f"Parsed {len(parsed)} items from {source_name}")
            collected.extend(parsed)
        except Exception as error:
            print(f"[warn] failed to fetch {source_name} safety feed: {error}")

    if not collected:
        print("[warn] no FDA/EMA safety items parsed; keeping existing file unchanged")
        return 0

    dedup: dict[str, dict] = {}
    for item in collected:
        dedup[item["url"]] = item

    items = list(dedup.values())
    items.sort(key=lambda item: item.get("publishedAt", ""), reverse=True)
    items = items[:LIMIT]

    processed = process_items_with_ai(items)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(processed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(processed)} AI-processed safety items to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
