"""Polite, rate-limited httpx client with retries."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


class RateLimitedClient:
    """Per-domain rate limiter wrapping httpx.Client."""

    def __init__(
        self,
        rate_limit_seconds: float = 2.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        user_agent: str = "vb-rental-finder/0.1",
        extra_headers: Optional[dict] = None,
    ):
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self._last_request_at: dict[str, float] = {}
        self._domain_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        if extra_headers:
            headers.update(extra_headers)

        self.client = httpx.Client(
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=True,
            http2=False,
        )

    def _wait_for_domain(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        with self._global_lock:
            lock = self._domain_locks.setdefault(host, threading.Lock())
        with lock:
            now = time.monotonic()
            last = self._last_request_at.get(host, 0.0)
            wait = self.rate_limit_seconds - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at[host] = time.monotonic()

    def get(self, url: str, **kwargs) -> httpx.Response:
        self._wait_for_domain(url)
        return self._get_with_retry(url, **kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        reraise=True,
    )
    def _get_with_retry(self, url: str, **kwargs) -> httpx.Response:
        log.debug("GET %s", url)
        resp = self.client.get(url, **kwargs)
        # Treat 429/5xx as transient
        if resp.status_code in (429,) or 500 <= resp.status_code < 600:
            raise httpx.TransportError(f"transient status {resp.status_code} on {url}")
        return resp

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
