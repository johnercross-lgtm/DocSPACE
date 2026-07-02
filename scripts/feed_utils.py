from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


def run_item_limit(default: int) -> int:
    raw_value = os.environ.get("FEED_MAX_ITEMS_PER_RUN", "").strip()
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("FEED_MAX_ITEMS_PER_RUN must be an integer") from error

    if value < 1:
        raise ValueError("FEED_MAX_ITEMS_PER_RUN must be at least 1")
    return value


def load_existing_feed(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"[warn] cannot read existing feed {path}: {error}")
        return []

    if not isinstance(payload, list):
        print(f"[warn] existing feed {path} is not a JSON array")
        return []
    return [item for item in payload if isinstance(item, dict)]


def process_incremental_items(
    candidates: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    processor: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    max_items_per_run: int,
    feed_limit: int,
    key: str = "url",
    reprocess_existing: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    existing_by_key = {
        str(item.get(key)): item
        for item in existing
        if item.get(key)
    }
    new_candidates = [
        item for item in candidates
        if item.get(key)
        and (
            str(item.get(key)) not in existing_by_key
            or (
                reprocess_existing is not None
                and reprocess_existing(existing_by_key[str(item.get(key))])
            )
        )
    ][:max_items_per_run]

    processed_new = processor(new_candidates) if new_candidates else []
    merged_by_key = dict(existing_by_key)
    for item in processed_new:
        item_key = item.get(key)
        if item_key:
            merged_by_key[str(item_key)] = item

    ordered_keys: list[str] = []
    for item in [*candidates, *existing]:
        item_key = item.get(key)
        normalized_key = str(item_key) if item_key else ""
        if normalized_key and normalized_key in merged_by_key and normalized_key not in ordered_keys:
            ordered_keys.append(normalized_key)

    merged = [merged_by_key[item_key] for item_key in ordered_keys[:feed_limit]]
    return merged, len(processed_new)
