from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from typing import Any


def _network_retry_limit() -> int:
    raw_value = os.environ.get("FEED_NETWORK_RETRIES", "2").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 2
    return min(2, max(0, value))


def _is_network_error(error: BaseException) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return False
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


def urlopen_with_retry(
    request: str | urllib.request.Request,
    *,
    timeout: float,
    **kwargs: Any,
):
    retries = _network_retry_limit()

    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout, **kwargs)
        except Exception as error:
            if not _is_network_error(error) or attempt >= retries:
                raise

            delay_seconds = 2 ** attempt
            print(
                f"[network] request failed attempt={attempt + 1}/{retries + 1}; "
                f"retry_in={delay_seconds}s error={error}"
            )
            time.sleep(delay_seconds)

    raise RuntimeError("unreachable network retry state")
