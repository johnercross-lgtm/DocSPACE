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
_MEDIA_CONTAINER_CLASSES = {
    "tgme_widget_message_photo_wrap",
    "tgme_widget_message_service_photo",
    "tgme_widget_message_grouped_layer",
}
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
        self._inside_media_anchor_depth = 0

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

        is_media_container = bool(class_names & _MEDIA_CONTAINER_CLASSES)
        is_media_anchor = tag == "a" and is_media_container

        if tag == "div":
            self._wrapper_div_depth += 1
            if "tgme_widget_message_text" in class_names:
                self._text_depth = 1
        elif self._text_depth > 0 and tag not in _VOID_TAGS:
            self._text_depth += 1

        if is_media_anchor:
            self._inside_media_anchor_depth += 1

        self._capture_message_metadata(
            tag=tag,
            attrs=attrs_dict,
            classes=class_names,
            is_media_container=is_media_container,
        )

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

        if tag == "a" and self._inside_media_anchor_depth > 0:
            self._inside_media_anchor_depth -= 1

        if self._text_depth > 0:
            self._text_depth -= 1

        if tag == "div":
            self._wrapper_div_depth -= 1
            if self._wrapper_div_depth <= 0:
                self.items.append(self._current)
                self._current = None
                self._wrapper_div_depth = 0
                self._text_depth = 0
                self._inside_media_anchor_depth = 0

    def _capture_message_metadata(
        self,
        tag: str,
        attrs: dict[str, str],
        classes: set[str],
        is_media_container: bool,
    ) -> None:
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
        if style_value and is_media_container:
            extracted = extract_background_image(style_value)
            if extracted:
                self._current.image_candidates.append(extracted)

        if tag == "img":
            if "emoji" in classes:
                return
            if self._inside_media_anchor_depth <= 0:
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
