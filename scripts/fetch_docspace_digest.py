#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup, Tag


TELEGRAM_SOURCE_URL = "https://t.me/s/docspace_digest"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "docspace-digest-feed.json"
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_MAX_PAGES = 8
DEFAULT_LIMIT = 40
TITLE_LIMIT = 140
ABSTRACT_LIMIT = 460

_BACKGROUND_IMAGE_RE = re.compile(
    r"background-image\s*:\s*url\(\s*(['\"])(?P<url>.+?)\1\s*\)",
    flags=re.IGNORECASE,
)
_BACKGROUND_IMAGE_UNQUOTED_RE = re.compile(
    r"background-image\s*:\s*url\(\s*(?P<url>[^)\"']+)\s*\)",
    flags=re.IGNORECASE,
)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_html(url: str, timeout_seconds: int) -> str:
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.text


def parse_message_id(raw_data_post: str | None) -> int | None:
    if not raw_data_post:
        return None
    try:
        return int(raw_data_post.rsplit("/", 1)[-1])
    except (ValueError, TypeError):
        return None


def normalize_url(raw_url: str) -> str:
    value = raw_url.strip().strip("\"'")
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


def extract_image_url(wrapper: Tag) -> str:
    for node in wrapper.select("a.tgme_widget_message_photo_wrap[style], div.tgme_widget_message_photo_wrap[style], a[style*='background-image'], div[style*='background-image']"):
        style_value = node.get("style", "")
        image_url = extract_background_image(style_value)
        if image_url:
            return image_url

    for image_node in wrapper.select("img[src]"):
        classes = " ".join(image_node.get("class", []))
        if "emoji" in classes:
            continue
        image_url = normalize_url(image_node.get("src", ""))
        if image_url:
            return image_url

    return ""


def extract_title_abstract(text: str) -> tuple[str, str]:
    if not text:
        return "", ""

    parts = re.split(r"(?<=[\.\!\?])\s+", text)
