"""Tiny JSON-over-HTTPS helper built on the standard library (no dependencies)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

RETRY_STATUSES = (429, 500, 502, 503, 504)


class HTTPError(Exception):
    """An HTTP error response. The message never includes request headers, so API keys stay out of logs."""

    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} from {url.split('?')[0]}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


def request_json(
    method: str,
    url: str,
    headers: dict | None = None,
    payload: dict | list | None = None,
    timeout: int = 60,
    retries: int = 2,
):
    """Send a request and return the decoded JSON body (or None for an empty body).

    Retries transient failures (429 / 5xx / network errors) with exponential backoff.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    all_headers = {"Accept": "application/json", "User-Agent": "ai-pr-review-bot"}
    if payload is not None:
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})

    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in RETRY_STATUSES and attempt < retries:
                attempt += 1
                time.sleep(2**attempt)
                continue
            raise HTTPError(exc.code, body, url) from None
        except urllib.error.URLError:
            if attempt < retries:
                attempt += 1
                time.sleep(2**attempt)
                continue
            raise
