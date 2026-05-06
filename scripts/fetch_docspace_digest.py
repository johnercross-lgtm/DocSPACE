#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


TELEGRAM_SOURCE_URL = "https://t.me/s/docspace_digest"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "docspace-digest-feed.json"
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_MAX_PAGES = 8
DEFAULT_LIMIT = 40
TITLE_LIMIT = 140
ABSTRACT_LIMIT = 460
USER_AGENT = "Mozilla/5.0 (DocSPACE digest bot)"

_BACKGROUND_IMAGE_RE = re.compile(
    r"background-image\s*:\s*url\(\s*(['\"])(?P<url>.+?)\1\s*\)",
    flags=re.IGNORECASE,
)
_BACKGROUND_IMAGE_UNQUOTED_RE = re.compile(
    r"background-image\s*:\s*url\(\s*(?P<url>[^)\"']+)\s*\)",
    flags=re.IGNORECASE,
)
_DATA_POST_ID_RE = re.compile(r"data-post\s*=\s*[\"'][^\"']*/(?P<id>\d+)[\"']", flags=re.IGNORECASE)
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass
class TelegramMessageDraft:
    message_id: int | None = None
    url: str = ""
    published_at: str = ""
    text_chunks: list[str] = field(default_factory=list)
    image_candidates: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.text_chunks))

    @property
    def image_url(self) -> str:
        for candidate in self.image_candidates:
            normalized = normalize_url(candidate)
            if normalized:
                return normalized
        return ""


class TelegramDigestHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[TelegramMessageDraft] = []
        self._current: TelegramMessageDraft | None = None
        self._wrapper_div_depth = 0
        self._text_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: (value or "") for key, value in attrs}
        class_names = class_name_set(attrs_dict.get("class", ""))

        if tag == "div" and "tgme_widget_message_wrap" in class_names and self._current is None:
            self._current = TelegramMessageDraft()
            self._wrapper_div_depth = 1
            self._text_depth = 0
            return

        if self._current is None:
            return

        if tag == "div":
            self._wrapper_div_depth += 1
            if "tgme_widget_message_text" in class_names:
                self._text_depth = 1
        elif self._text_depth > 0 and tag not in _VOID_TAGS:
            self._text_depth += 1

        self._capture_message_metadata(tag=tag, attrs=attrs_dict, classes=class_names)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._current is None or self._text_depth <= 0:
            return
        chunk = data.strip()
        if chunk:
            self._current.text_chunks.append(chunk)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return

        if self._text_depth > 0:
            self._text_depth -= 1

        if tag == "div":
            self._wrapper_div_depth -= 1
            if self._wrapper_div_depth <= 0:
                self.items.append(self._current)
                self._current = None
                self._wrapper_div_depth = 0
                self._text_depth = 0

    def _capture_message_metadata(self, tag: str, attrs: dict[str, str], classes: set[str]) -> None:
        if self._current is None:
            return

        if tag == "div" and "tgme_widget_message" in classes:
            parsed_id = parse_message_id(attrs.get("data-post"))
            if parsed_id is not None:
                self._current.message_id = parsed_id

        if tag == "a" and "tgme_widget_message_date" in classes and not self._current.url:
            self._current.url = normalize_url(attrs.get("href", ""))

        if tag == "time" and not self._current.published_at:
            self._current.published_at = attrs.get("datetime", "").strip()

        style_value = attrs.get("style", "")
        if style_value:
            extracted = extract_background_image(style_value)
            if extracted:
                self._current.image_candidates.append(extracted)

        if tag == "img":
            if "emoji" in classes:
                return
            src = attrs.get("src", "")
            if src:
                self._current.image_candidates.append(src)


def class_name_set(raw_classes: str) -> set[str]:
    return {token for token in raw_classes.split() if token}


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_html(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, ssl.SSLError):
            insecure_context = ssl._create_unverified_context()
            with urllib.request.urlopen(request, timeout=timeout_seconds, context=insecure_context) as response:
                body = response.read()
        else:
            raise
    return body.decode("utf-8", errors="ignore")


def parse_message_id(raw_data_post: str | None) -> int | None:
    if not raw_data_post:
        return None
    try:
        return int(raw_data_post.rsplit("/", 1)[-1])
    except (ValueError, TypeError):
        return None


def normalize_url(raw_url: str) -> str:
    value = raw_url.strip().strip('"\'')
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"https://t.me{value}"
    return value


def extract_background_image(style_value: str) -> str:
    if not style_value:
        return ""

    match = _BACKGROUND_IMAGE_RE.search(style_value)
    if match:
        return normalize_url(match.group("url"))

    unquoted_match = _BACKGROUND_IMAGE_UNQUOTED_RE.search(style_value)
    if unquoted_match:
        return normalize_url(unquoted_match.group("url"))

    return ""


def extract_title_abstract(text: str) -> tuple[str, str]:
    if not text:
        return "", ""

    parts = re.split(r"(?<=[\.\!\?])\s+", text)
    title_candidate = parts[0] if parts else text
    title = title_candidate[:TITLE_LIMIT].strip()
    if len(title_candidate) > TITLE_LIMIT:
        title = f"{title.rstrip()}…"

    abstract = text[:ABSTRACT_LIMIT].strip()
    if len(text) > ABSTRACT_LIMIT:
        abstract = f"{abstract.rstrip()}…"

    return title, abstract


def parse_posts(html: str, updated_at_iso: str) -> list[dict[str, str]]:
    parser = TelegramDigestHTMLParser()
    parser.feed(html)

    items: list[dict[str, str]] = []
    for message in parser.items:
        message_id = message.message_id
        if message_id is None:
            continue

        url = message.url.strip()
        published_at = message.published_at.strip()
        if not url or not published_at:
            continue

        title, abstract = extract_title_abstract(message.text)
        if not title:
            title = f"DocSPACE Digest #{message_id}"

        items.append(
            {
                "id": f"docspace_digest_{message_id}",
                "type": "docspace_digest",
                "title": title,
                "abstract": abstract,
                "imageUrl": message.image_url,
                "url": url,
                "source": "DocSPACE Medical Digest",
                "category": "editorial_digest",
                "publishedAt": published_at,
                "updatedAt": updated_at_iso,
            }
        )

    return items


def parse_oldest_message_id(html: str) -> int | None:
    ids = [int(match.group("id")) for match in _DATA_POST_ID_RE.finditer(html)]
    if not ids:
        return None
    return min(ids)


def iso_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def deduplicate_items(items: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for item in items:
        key = item.get("id", "").strip()
        if not key:
            continue

        existing = by_id.get(key)
        if existing is None:
            by_id[key] = item
            continue

        current_date = iso_to_datetime(item.get("publishedAt", "1970-01-01T00:00:00Z"))
        existing_date = iso_to_datetime(existing.get("publishedAt", "1970-01-01T00:00:00Z"))
        if current_date >= existing_date:
            by_id[key] = item

    return list(by_id.values())


def collect_posts(channel_url: str, max_pages: int, timeout_seconds: int) -> list[dict[str, str]]:
    updated_at_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    before: int | None = None
    seen_before_markers: set[int] = set()
    all_items: list[dict[str, str]] = []

    for _ in range(max_pages):
        page_url = channel_url if before is None else f"{channel_url}?before={before}"
        html = fetch_html(page_url, timeout_seconds)

        all_items.extend(parse_posts(html, updated_at_iso=updated_at_iso))

        oldest_id = parse_oldest_message_id(html)
        if oldest_id is None or oldest_id in seen_before_markers:
            break

        seen_before_markers.add(oldest_id)
        before = oldest_id

    deduped = deduplicate_items(all_items)
    deduped.sort(key=lambda item: iso_to_datetime(item["publishedAt"]), reverse=True)
    return deduped


def write_feed(items: list[dict[str, str]], output_path: Path, limit: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = items[:limit]
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch DocSPACE Medical Digest feed from Telegram.")
    parser.add_argument("--channel-url", type=str, default=TELEGRAM_SOURCE_URL, help="Telegram /s/ channel URL")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum number of items to write")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Telegram pages to parse")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    items = collect_posts(
        channel_url=args.channel_url,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout,
    )
    write_feed(items=items, output_path=args.output, limit=args.limit)
    print(f"Saved {min(len(items), args.limit)} items to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
