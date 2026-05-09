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

from ai_digest import process_article_with_ai

OUT_PATH = Path("data/cochrane-feed.json")
FEED_URLS = (
    "https://www.cochranelibrary.com/cdsr/reviews/rss",
    "https://www.cochranelibrary.com/rss/latest",
)

TIMEOUT_SECONDS = 30
LIMIT = 10
ABSTRACT_LIMIT = 500

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    "?db=pubmed&term=Cochrane+Database+Syst+Rev%5Bjour%5D"
    f"&sort=pub+date&retmax={LIMIT}&retmode=json"
)

PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


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
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT_SECONDS,
                context=insecure_context,
            ) as response:
                return response.read()

        raise


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (DocSPACE bot)"},
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)

        if isinstance(reason, ssl.SSLError):
            insecure_context = ssl._create_unverified_context()
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT_SECONDS,
                context=insecure_context,
            ) as response:
                return response.read().decode("utf-8", errors="ignore")

        raise


def clean_summary(raw_text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw_text, flags=re.IGNORECASE)
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

    updated_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

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

    items.sort(
        key=lambda item: parse_pub_date(item.get("publishedAt", "")),
        reverse=True,
    )

    return items[:LIMIT]


def write_feed(items: list[dict]) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def join_abstract_text(article_node: ET.Element) -> str:
    parts: list[str] = []

    for node in article_node.findall(".//Abstract/AbstractText"):
        text = "".join(node.itertext()).strip()

        if text:
            parts.append(text)

    return clean_summary(" ".join(parts))


def parse_pubmed_date(article_node: ET.Element) -> str:
    pub_date = article_node.find(".//PubDate")

    if pub_date is None:
        return ""

    year = (pub_date.findtext("Year") or "").strip()
    month = (pub_date.findtext("Month") or "").strip()
    day = (pub_date.findtext("Day") or "").strip()
    medline = (pub_date.findtext("MedlineDate") or "").strip()

    if year and month and day:
        return f"{year} {month} {day}"

    if year and month:
        return f"{year} {month}"

    if year:
        return year

    return medline


def cochrane_url_from_ids(article_node: ET.Element, pmid: str) -> str:
    doi = ""

    for id_node in article_node.findall(".//ArticleIdList/ArticleId"):
        if (id_node.get("IdType") or "").lower() == "doi":
            doi = (id_node.text or "").strip()
            break

    if doi:
        return f"https://www.cochranelibrary.com/cdsr/doi/{doi}/full"

    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def fetch_pubmed_fallback_items() -> list[dict[str, str]]:
    updated_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    search_text = fetch_text(PUBMED_ESEARCH_URL)
    search_payload = json.loads(search_text)
    id_list = search_payload.get("esearchresult", {}).get("idlist", [])[:LIMIT]

    if not id_list:
        return []

    fetch_url = f"{PUBMED_EFETCH_URL}?db=pubmed&id={','.join(id_list)}&retmode=xml"
    xml_text = fetch_text(fetch_url)
    root = ET.fromstring(xml_text)

    items: list[dict[str, str]] = []

    for article in root.findall(".//PubmedArticle"):
        pmid = (article.findtext(".//PMID") or "").strip()
        title_node = article.find(".//ArticleTitle")
        title = "".join(title_node.itertext()).strip() if title_node is not None else ""

        if not title:
            continue

        summary = join_abstract_text(article)
        published = parse_pubmed_date(article)
        url = cochrane_url_from_ids(article, pmid) if pmid else ""

        if not url:
            continue

        items.append(
            {
                "title": title,
                "abstract": summary,
                "url": url,
                "source": "Cochrane",
                "category": "evidence_review",
                "publishedAt": published,
                "updatedAt": updated_at,
            }
        )

    return items[:LIMIT]


def process_items_with_ai(items: list[dict[str, str]]) -> list[dict]:
    processed_items: list[dict] = []

    for index, item in enumerate(items, start=1):
        print(f"AI processing Cochrane item {index}/{len(items)}: {item.get('title', '')[:80]}")
        processed_items.append(process_article_with_ai(item))

    return processed_items


def main() -> int:
    xml_payload: bytes | None = None

    for feed_url in FEED_URLS:
        try:
            xml_payload = fetch_xml(feed_url)
            break
        except Exception as error:
            print(f"[warn] failed to fetch {feed_url}: {error}")

    if xml_payload is None:
        print("[warn] all Cochrane RSS endpoints are unavailable; trying PubMed fallback")

        try:
            fallback_items = fetch_pubmed_fallback_items()
        except Exception as error:
            print(f"[warn] PubMed fallback failed: {error}; keeping existing file unchanged")
            return 0

        if not fallback_items:
            print("[warn] PubMed fallback returned no items; keeping existing file unchanged")
            return 0

        processed_fallback_items = process_items_with_ai(fallback_items)

        write_feed(processed_fallback_items)
        print(f"Saved {len(processed_fallback_items)} AI-processed Cochrane fallback items to {OUT_PATH}")

        return 0

    try:
        items = parse_items(xml_payload)
    except Exception as error:
        print(f"[warn] failed to parse Cochrane RSS: {error}; keeping existing file unchanged")
        return 0

    if not items:
        print("[warn] parsed Cochrane RSS contains no valid items; keeping existing file unchanged")
        return 0

    processed_items = process_items_with_ai(items)

    write_feed(processed_items)
    print(f"Saved {len(processed_items)} AI-processed Cochrane feed items to {OUT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
