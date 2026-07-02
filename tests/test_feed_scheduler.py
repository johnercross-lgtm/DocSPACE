from __future__ import annotations

import sys
import unittest
import urllib.error
import urllib.parse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from feed_scheduler import (  # noqa: E402
    SourceConfig,
    TelegramWebhookHook,
    _telegram_api_request,
    load_config,
    run_source,
    select_due_sources,
)
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


class DocspaceDigestWebhookHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SourceConfig(
            source_id="docspace_digest",
            enabled=True,
            interval_hours=48,
            jitter_hours=6,
            max_items_per_run=3,
            script="scripts/fetch_docspace_digest.py",
            feed_file="data/docspace-digest-feed.json",
            push_source="docspace_digest",
        )
        self.successful_result = {
            "ok": True,
            "error": "",
            "items_added": 1,
            "changed": True,
            "feed_file": self.source.feed_file,
            "push_source": self.source.push_source,
        }

    @mock.patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_WEBHOOK_URL": "https://example.com/telegram-webhook",
        },
        clear=True,
    )
    @mock.patch("feed_scheduler._run_source_fetcher")
    @mock.patch.object(TelegramWebhookHook, "restore")
    @mock.patch.object(TelegramWebhookHook, "temporarily_delete")
    def test_deletes_and_restores_webhook_around_fetcher(
        self,
        mocked_delete,
        mocked_restore,
        mocked_fetcher,
    ) -> None:
        mocked_fetcher.return_value = self.successful_result
        lifecycle = mock.Mock()
        lifecycle.attach_mock(mocked_delete, "delete")
        lifecycle.attach_mock(mocked_fetcher, "fetch")
        lifecycle.attach_mock(mocked_restore, "restore")

        result = run_source(self.source)

        self.assertEqual(result, self.successful_result)
        self.assertEqual(
            lifecycle.mock_calls,
            [mock.call.delete(), mock.call.fetch(self.source), mock.call.restore()],
        )

    @mock.patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_WEBHOOK_URL": "https://example.com/telegram-webhook",
        },
        clear=True,
    )
    @mock.patch("feed_scheduler._run_source_fetcher", side_effect=RuntimeError("fetch failed"))
    @mock.patch.object(TelegramWebhookHook, "restore")
    @mock.patch.object(TelegramWebhookHook, "temporarily_delete")
    def test_restores_webhook_when_fetcher_raises(
        self,
        mocked_delete,
        mocked_restore,
        _mocked_fetcher,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "fetch failed"):
            run_source(self.source)

        mocked_delete.assert_called_once_with()
        mocked_restore.assert_called_once_with()

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test-token"}, clear=True)
    @mock.patch("feed_scheduler._run_source_fetcher")
    @mock.patch("feed_scheduler._telegram_api_request")
    def test_missing_webhook_url_warns_and_runs_without_hook(
        self,
        mocked_api_request,
        mocked_fetcher,
    ) -> None:
        mocked_fetcher.return_value = self.successful_result

        with mock.patch("builtins.print") as mocked_print:
            result = run_source(self.source)

        self.assertEqual(result, self.successful_result)
        mocked_api_request.assert_not_called()
        mocked_fetcher.assert_called_once_with(self.source)
        self.assertTrue(
            any(
                "TELEGRAM_WEBHOOK_URL is missing" in str(call.args[0])
                for call in mocked_print.call_args_list
            )
        )

    @mock.patch("feed_scheduler._telegram_api_request")
    def test_hook_uses_expected_telegram_api_parameters(self, mocked_api_request) -> None:
        hook = TelegramWebhookHook(
            bot_token="test-token",
            webhook_url="https://example.com/telegram-webhook",
        )

        hook.temporarily_delete()
        hook.restore()

        self.assertEqual(
            mocked_api_request.call_args_list,
            [
                mock.call(
                    "test-token",
                    "deleteWebhook",
                    {"drop_pending_updates": "false"},
                    query_parameters=True,
                ),
                mock.call(
                    "test-token",
                    "setWebhook",
                    {
                        "url": "https://example.com/telegram-webhook",
                        "allowed_updates": '["channel_post", "edited_channel_post"]',
                    },
                ),
            ],
        )

    @mock.patch("feed_scheduler._run_source_fetcher")
    @mock.patch.object(TelegramWebhookHook, "from_environment")
    def test_other_sources_do_not_use_webhook_hook(
        self,
        mocked_hook_factory,
        mocked_fetcher,
    ) -> None:
        source = replace(
            self.source,
            source_id="pubmed",
            script="scripts/fetch_pubmed.py",
            feed_file="data/pubmed-feed.json",
            push_source="pubmed",
        )
        mocked_fetcher.return_value = self.successful_result

        run_source(source)

        mocked_hook_factory.assert_not_called()
        mocked_fetcher.assert_called_once_with(source)


class TelegramApiRequestTests(unittest.TestCase):
    def response(self) -> mock.MagicMock:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": true}'
        return response

    @mock.patch("feed_scheduler.urllib.request.urlopen")
    def test_delete_webhook_keeps_pending_updates(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = self.response()

        _telegram_api_request(
            "test-token",
            "deleteWebhook",
            {"drop_pending_updates": "false"},
            query_parameters=True,
        )

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.telegram.org/bottest-token/"
            "deleteWebhook?drop_pending_updates=false",
        )
        self.assertEqual(request.get_method(), "GET")

    @mock.patch("feed_scheduler.urllib.request.urlopen")
    def test_set_webhook_posts_url_and_allowed_updates(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = self.response()

        _telegram_api_request(
            "test-token",
            "setWebhook",
            {
                "url": "https://example.com/telegram-webhook",
                "allowed_updates": '["channel_post", "edited_channel_post"]',
            },
        )

        request = mocked_urlopen.call_args.args[0]
        parameters = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(
            request.full_url,
            "https://api.telegram.org/bottest-token/setWebhook",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parameters["url"], ["https://example.com/telegram-webhook"])
        self.assertEqual(
            parameters["allowed_updates"],
            ['["channel_post", "edited_channel_post"]'],
        )


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
