from __future__ import annotations

import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from feed_scheduler import SourceConfig, load_config, select_due_sources  # noqa: E402
from feed_utils import process_incremental_items  # noqa: E402
from http_client import urlopen_with_retry  # noqa: E402


class SchedulerSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
        self.sources = [
            SourceConfig(
                source_id=source_id,
                enabled=True,
                interval_hours=24,
                jitter_hours=2,
                max_items_per_run=2,
                script="scripts/fetch_pubmed.py",
                feed_file="data/pubmed-feed.json",
                push_source=source_id,
            )
            for source_id in ("first", "second", "third")
        ]

    def test_selects_at_most_two_oldest_due_sources(self) -> None:
        states = {
            "first": {"next_run_at": self.now - timedelta(hours=1)},
            "second": {"next_run_at": self.now - timedelta(hours=3)},
            "third": {"next_run_at": self.now + timedelta(hours=1)},
        }

        selected = select_due_sources(self.sources, states, self.now, limit=2)

        self.assertEqual([source.source_id for source in selected], ["second", "first"])

    def test_missing_state_is_due(self) -> None:
        states = {source.source_id: {} for source in self.sources}
        selected = select_due_sources(self.sources, states, self.now, limit=2)
        self.assertEqual(len(selected), 2)


class ConfigurationTests(unittest.TestCase):
    def test_repository_config_is_valid_and_capped(self) -> None:
        sources, max_sources, collection = load_config(ROOT / "config/feed_sources.json")
        self.assertEqual(max_sources, 2)
        self.assertEqual(collection, "feed_scheduler_state")
        self.assertEqual(len(sources), 7)
        self.assertTrue(all(source.max_items_per_run > 0 for source in sources))


class IncrementalProcessingTests(unittest.TestCase):
    def test_only_processes_configured_number_of_new_items(self) -> None:
        existing = [{"url": "old", "publishedAt": "2026-07-01T00:00:00Z"}]
        candidates = [
            {"url": "new-1", "publishedAt": "2026-07-03T00:00:00Z"},
            {"url": "new-2", "publishedAt": "2026-07-02T00:00:00Z"},
            existing[0],
        ]
        processed_batches: list[list[str]] = []

        def processor(items):
            processed_batches.append([item["url"] for item in items])
            return [{**item, "processed": True} for item in items]

        merged, processed_count = process_incremental_items(
            candidates,
            existing,
            processor,
            max_items_per_run=1,
            feed_limit=10,
        )

        self.assertEqual(processed_count, 1)
        self.assertEqual(processed_batches, [["new-1"]])
        self.assertEqual([item["url"] for item in merged], ["new-1", "old"])


class NetworkRetryTests(unittest.TestCase):
    @mock.patch("http_client.time.sleep")
    @mock.patch("http_client.urllib.request.urlopen")
    def test_retries_network_errors_at_most_twice(self, mocked_urlopen, _mocked_sleep) -> None:
        mocked_urlopen.side_effect = urllib.error.URLError("temporary DNS failure")

        with self.assertRaises(urllib.error.URLError):
            urlopen_with_retry("https://example.invalid", timeout=1)

        self.assertEqual(mocked_urlopen.call_count, 3)

    @mock.patch("http_client.urllib.request.urlopen")
    def test_does_not_retry_http_errors(self, mocked_urlopen) -> None:
        mocked_urlopen.side_effect = urllib.error.HTTPError(
            "https://example.invalid", 500, "server error", {}, None
        )

        with self.assertRaises(urllib.error.HTTPError):
            urlopen_with_retry("https://example.invalid", timeout=1)

        self.assertEqual(mocked_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
