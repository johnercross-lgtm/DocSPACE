#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from validate_feeds import validate_file


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config/feed_sources.json"
DEFAULT_RESULTS_PATH = Path("/tmp/feed-scheduler-results.json")
UTC = timezone.utc
DOCSPACE_DIGEST_SOURCE_ID = "docspace_digest"
TELEGRAM_ALLOWED_UPDATES = ["channel_post", "edited_channel_post"]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def isoformat(value: datetime | None) -> str:
    if value is None:
        return "null"
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    enabled: bool
    interval_hours: float
    jitter_hours: float
    max_items_per_run: int
    script: str
    feed_file: str
    push_source: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceConfig":
        source = cls(**payload)
        if not source.source_id or not source.source_id.replace("_", "").isalnum():
            raise ValueError(f"invalid source_id: {source.source_id!r}")
        if source.interval_hours <= 0 or source.jitter_hours < 0:
            raise ValueError(f"invalid interval/jitter for {source.source_id}")
        if source.max_items_per_run < 1:
            raise ValueError(f"max_items_per_run must be positive for {source.source_id}")
        if not (ROOT / source.script).is_file():
            raise ValueError(f"script does not exist for {source.source_id}: {source.script}")
        return source


class StateStore(Protocol):
    def get(self, source_id: str) -> dict[str, Any]: ...
    def set(self, source_id: str, payload: dict[str, Any]) -> None: ...


class FirestoreStateStore:
    def __init__(self, collection_name: str) -> None:
        try:
            from google.cloud import firestore
        except ImportError as error:
            raise RuntimeError("google-cloud-firestore is required") from error

        project = os.environ.get("FIREBASE_PROJECT_ID") or None
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        self._client = firestore.Client(project=project, database=database)
        self._collection = self._client.collection(collection_name)

    def get(self, source_id: str) -> dict[str, Any]:
        snapshot = self._collection.document(source_id).get(timeout=20)
        return snapshot.to_dict() or {} if snapshot.exists else {}

    def set(self, source_id: str, payload: dict[str, Any]) -> None:
        self._collection.document(source_id).set(payload, merge=True, timeout=20)


def load_config(path: Path) -> tuple[list[SourceConfig], int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = [SourceConfig.from_dict(item) for item in payload.get("sources", [])]
    source_ids = [source.source_id for source in sources]
    if not sources or len(source_ids) != len(set(source_ids)):
        raise ValueError("source config must contain unique sources")

    max_sources = int(payload.get("max_sources_per_run", 2))
    if max_sources not in (1, 2):
        raise ValueError("max_sources_per_run must be 1 or 2")
    collection = str(payload.get("firestore_collection", "feed_scheduler_state")).strip()
    if not collection:
        raise ValueError("firestore_collection must not be empty")
    return sources, max_sources, collection


def state_config(source: SourceConfig) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "enabled": source.enabled,
        "interval_hours": source.interval_hours,
        "jitter_hours": source.jitter_hours,
        "max_items_per_run": source.max_items_per_run,
    }


def is_due(source: SourceConfig, state: dict[str, Any], now: datetime) -> bool:
    if not source.enabled:
        return False
    next_run_at = normalize_datetime(state.get("next_run_at"))
    return next_run_at is None or next_run_at <= now


def select_due_sources(
    sources: list[SourceConfig],
    states: dict[str, dict[str, Any]],
    now: datetime,
    limit: int,
) -> list[SourceConfig]:
    due_sources = [source for source in sources if is_due(source, states[source.source_id], now)]
    minimum = datetime.min.replace(tzinfo=UTC)
    due_sources.sort(
        key=lambda source: normalize_datetime(states[source.source_id].get("next_run_at")) or minimum
    )
    return due_sources[:limit]


def load_item_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    keys: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        value = item.get("url") or item.get("id") or f"index:{index}"
        keys.add(str(value))
    return keys


@dataclass(frozen=True)
class TelegramWebhookHook:
    bot_token: str
    webhook_url: str

    @classmethod
    def from_environment(cls) -> "TelegramWebhookHook | None":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()

        if not webhook_url:
            print(
                "[source:docspace_digest][warn] TELEGRAM_WEBHOOK_URL is missing; "
                "skipping Telegram webhook lifecycle"
            )
            return None
        if not bot_token:
            print(
                "[source:docspace_digest][warn] TELEGRAM_BOT_TOKEN is missing; "
                "skipping Telegram webhook lifecycle"
            )
            return None

        parsed_url = urllib.parse.urlparse(webhook_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("TELEGRAM_WEBHOOK_URL must be a valid HTTPS URL")

        return cls(bot_token=bot_token, webhook_url=webhook_url)

    def temporarily_delete(self) -> None:
        _telegram_api_request(
            self.bot_token,
            "deleteWebhook",
            {"drop_pending_updates": "false"},
            query_parameters=True,
        )
        print("Telegram webhook temporarily deleted")

    def restore(self) -> None:
        _telegram_api_request(
            self.bot_token,
            "setWebhook",
            {
                "url": self.webhook_url,
                "allowed_updates": json.dumps(TELEGRAM_ALLOWED_UPDATES),
            },
        )
        print("Telegram webhook restored")


def _telegram_api_request(
    bot_token: str,
    method: str,
    parameters: dict[str, str],
    *,
    query_parameters: bool = False,
) -> None:
    encoded_parameters = urllib.parse.urlencode(parameters)
    api_url = f"https://api.telegram.org/bot{bot_token}/{method}"
    request_data: bytes | None = None

    if query_parameters:
        api_url = f"{api_url}?{encoded_parameters}"
    else:
        request_data = encoded_parameters.encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=request_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "DocSPACE Feed Scheduler/1.0",
        },
        method="GET" if query_parameters else "POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Telegram {method} failed with HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Telegram {method} request failed: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError(f"Telegram {method} request timed out") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Telegram {method} returned an invalid response") from error

    if not isinstance(payload, dict):
        raise RuntimeError(f"Telegram {method} returned an invalid response")
    if not payload.get("ok"):
        description = payload.get("description") or "unknown Telegram API error"
        raise RuntimeError(f"Telegram {method} failed: {description}")


def _run_source_fetcher(source: SourceConfig) -> dict[str, Any]:
    script_path = ROOT / source.script
    feed_path = ROOT / source.feed_file
    previous_bytes = feed_path.read_bytes() if feed_path.exists() else None
    before_keys = load_item_keys(feed_path)
    environment = os.environ.copy()
    environment["FEED_MAX_ITEMS_PER_RUN"] = str(source.max_items_per_run)
    environment["MAX_AI_ITEMS_PER_RUN"] = str(source.max_items_per_run)
    environment["FEED_NETWORK_RETRIES"] = "2"

    print(
        f"[source:{source.source_id}] start script={source.script} "
        f"max_items_per_run={source.max_items_per_run}"
    )
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=20 * 60,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        if previous_bytes is None:
            feed_path.unlink(missing_ok=True)
        else:
            feed_path.write_bytes(previous_bytes)
        return {
            "ok": False,
            "error": f"source timed out after {error.timeout} seconds",
            "items_added": 0,
        }

    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)

    if completed.returncode != 0:
        if previous_bytes is None:
            feed_path.unlink(missing_ok=True)
        else:
            feed_path.write_bytes(previous_bytes)
        return {
            "ok": False,
            "error": f"fetch script exited with code {completed.returncode}",
            "items_added": 0,
        }

    try:
        validate_file(feed_path)
        after_keys = load_item_keys(feed_path)
    except Exception as error:
        if previous_bytes is None:
            feed_path.unlink(missing_ok=True)
        else:
            feed_path.write_bytes(previous_bytes)
        return {"ok": False, "error": f"feed validation failed: {error}", "items_added": 0}

    changed = previous_bytes != feed_path.read_bytes()
    return {
        "ok": True,
        "error": "",
        "items_added": len(after_keys - before_keys),
        "changed": changed,
        "feed_file": source.feed_file,
        "push_source": source.push_source,
    }


def run_source(source: SourceConfig) -> dict[str, Any]:
    if source.source_id != DOCSPACE_DIGEST_SOURCE_ID:
        return _run_source_fetcher(source)

    webhook_hook = TelegramWebhookHook.from_environment()
    if webhook_hook is None:
        return _run_source_fetcher(source)

    try:
        webhook_hook.temporarily_delete()
        return _run_source_fetcher(source)
    finally:
        webhook_hook.restore()


def write_results(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run due DocSPACE feed sources")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--source", help="Force one configured source (manual runs)")
    parser.add_argument("--max-sources", type=int)
    parser.add_argument("--results-file", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--validate-config", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources, configured_max, collection = load_config(args.config)
    print(f"[scheduler] config valid sources={len(sources)} max_sources_per_run={configured_max}")
    if args.validate_config:
        return 0

    requested_max = args.max_sources or configured_max
    if requested_max not in (1, 2):
        raise ValueError("--max-sources must be 1 or 2")
    max_sources = min(requested_max, configured_max, 2)

    source_by_id = {source.source_id: source for source in sources}
    if args.source and args.source not in source_by_id:
        raise ValueError(f"unknown source: {args.source}")

    now = utc_now()
    store = FirestoreStateStore(collection)
    states: dict[str, dict[str, Any]] = {}

    for source in sources:
        state = store.get(source.source_id)
        if not state:
            state = {
                **state_config(source),
                "last_success_at": None,
                "next_run_at": None,
                "status": "new",
            }
            store.set(source.source_id, state)
        else:
            store.set(source.source_id, state_config(source))
        states[source.source_id] = state

        due = is_due(source, state, now)
        print(
            f"[scheduler] source checked source={source.source_id} enabled={source.enabled} "
            f"due={due} last_success_at={isoformat(normalize_datetime(state.get('last_success_at')))} "
            f"next_run_at={isoformat(normalize_datetime(state.get('next_run_at')))}"
        )

    if args.source:
        selected = [source_by_id[args.source]]
        print(f"[scheduler] manual force source={args.source}")
    else:
        selected = select_due_sources(sources, states, now, max_sources)

    print(
        f"[scheduler] selected count={len(selected)} sources="
        f"{','.join(source.source_id for source in selected) or 'none'}"
    )
    results: list[dict[str, Any]] = []
    jitter = random.SystemRandom()

    for source in selected:
        attempted_at = utc_now()
        try:
            result = run_source(source)
        except Exception as error:
            result = {"ok": False, "error": f"unexpected scheduler error: {error}", "items_added": 0}

        result = {"source_id": source.source_id, **result}
        current_state = states[source.source_id]
        if result["ok"]:
            next_run_at = attempted_at + timedelta(
                hours=source.interval_hours + jitter.uniform(0, source.jitter_hours)
            )
            update = {
                **state_config(source),
                "last_attempt_at": attempted_at,
                "last_success_at": attempted_at,
                "next_run_at": next_run_at,
                "last_items_added": result["items_added"],
                "last_error": None,
                "status": "success",
                "workflow_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            }
        else:
            next_run_at = attempted_at + timedelta(hours=min(6, source.interval_hours / 4))
            update = {
                **state_config(source),
                "last_attempt_at": attempted_at,
                "last_success_at": current_state.get("last_success_at"),
                "next_run_at": next_run_at,
                "last_items_added": 0,
                "last_error": result["error"],
                "status": "error",
                "workflow_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            }

        store.set(source.source_id, update)
        print(
            f"[scheduler] source finished source={source.source_id} ok={result['ok']} "
            f"items_added={result['items_added']} next_run_at={isoformat(next_run_at)} "
            f"error={result.get('error') or 'none'}"
        )
        results.append(result)

    write_results(args.results_file, results)
    failures = sum(1 for result in results if not result["ok"])
    print(f"[scheduler] completed selected={len(results)} failures={failures}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"[scheduler:error] {error}", file=sys.stderr)
        raise SystemExit(1)
