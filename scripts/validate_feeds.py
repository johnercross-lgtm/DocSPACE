#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

ISO_8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

CORE_REQUIRED_KEYS = ("title", "abstract", "url", "source", "category", "publishedAt", "updatedAt")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_non_empty_str(item: dict[str, Any], key: str, label: str) -> None:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: '{key}' must be non-empty string")


def require_iso(item: dict[str, Any], key: str, label: str) -> None:
    value = item.get(key)
    if not isinstance(value, str) or not ISO_8601_RE.match(value):
        raise ValueError(f"{label}: '{key}' must be ISO8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")


def validate_file(path: Path) -> None:
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path.name}: root must be array")

    for index, item in enumerate(payload):
        label = f"{path.name}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label}: item must be object")

        for key in CORE_REQUIRED_KEYS:
            require_non_empty_str(item, key, label)

        require_iso(item, "updatedAt", label)

        # Some feeds can still contain non-ISO published dates; keep warning-only behavior for now.
        published_at = item.get("publishedAt")
        if isinstance(published_at, str) and not ISO_8601_RE.match(published_at):
            print(f"[warn] {label}: non-ISO publishedAt '{published_at}'")

        title = item.get("title", "").strip().lower()
        abstract = item.get("abstract", "").strip().lower()
        blocked = {"стандарт", "standard", "test", "тест"}
        if title in blocked or abstract in blocked:
            raise ValueError(f"{label}: placeholder content detected (title/abstract)")


def main() -> int:
    files = [
        DATA_DIR / "cochrane-feed.json",
        DATA_DIR / "pubmed-feed.json",
        DATA_DIR / "phc-feed.json",
        DATA_DIR / "nszu-feed.json",
        DATA_DIR / "docspace-digest-feed.json",
        DATA_DIR / "ukrainian-news-feed.json",
    ]

    checked = 0
    for path in files:
        if not path.exists():
            print(f"[warn] skipped missing file: {path.name}")
            continue
        validate_file(path)
        checked += 1

    if checked == 0:
        print("[warn] no feed files found")
        return 0

    print(f"[ok] validated {checked} feed file(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"[error] {error}", file=sys.stderr)
        raise SystemExit(1)
