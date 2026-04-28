"""Lazy Playwright + stealth helper.

Used by scrapers whose targets reject vanilla httpx requests.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class PlaywrightFetcher:
    """Thin wrapper that fetches rendered HTML for a given URL."""

    def __init__(
        self,
        headless: bool = True,
        slow_mo_ms: int = 0,
        default_timeout_ms: int = 45000,
        rate_limit_seconds: float = 2.0,
        user_agent: Optional[str] = None,
    ):
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self.default_timeout_ms = default_timeout_ms
        self.rate_limit_seconds = rate_limit_seconds
        self.user_agent = user_agent or _DEFAULT_UA
        self._last_request_at: dict[str, float] = {}
        self._lock = threading.Lock()
        self._pw = None
        self._browser = None
        self._context = None

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        with self._lock:
            now = time.monotonic()
            last = self._last_request_at.get(host, 0.0)
            wait = self.rate_limit_seconds - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at[host] = time.monotonic()

    def _ensure(self) -> None:
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo_ms,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        # Best-effort stealth — try both v1 and v2 APIs.
        self._stealth = None
        try:
            # playwright-stealth v1.x
            from playwright_stealth import stealth_sync  # type: ignore
            self._stealth = stealth_sync
        except Exception:
            try:
                # playwright-stealth v2.x
                from playwright_stealth import Stealth  # type: ignore
                _s = Stealth()
                def _apply(page):
                    fn = getattr(_s, "apply_stealth_sync", None) \
                         or getattr(_s, "apply_sync", None)
                    if fn:
                        fn(page)
                self._stealth = _apply
            except Exception:
                self._stealth = None

    def fetch(self, url: str, wait_selector: Optional[str] = None) -> Optional[str]:
        self._wait(url)
        try:
            self._ensure()
        except Exception as e:
            log.warning("Playwright unavailable: %s", e)
            return None

        page = self._context.new_page()
        try:
            page.set_default_timeout(self.default_timeout_ms)
            if self._stealth:
                try:
                    self._stealth(page)
                except Exception:
                    pass
            log.debug("Playwright GET %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=self.default_timeout_ms)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=self.default_timeout_ms)
                except Exception:
                    pass
            # Small dwell to let lazy JSON hydrate
            page.wait_for_timeout(1500)
            return page.content()
        except Exception as e:
            log.warning("Playwright fetch failed for %s: %s", url, e)
            return None
        finally:
            try:
                page.close()
            except Exception:
                pass

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._context = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@contextmanager
def playwright_fetcher_from_config(cfg: dict):
    pw_cfg = cfg.get("playwright", {})
    http_cfg = cfg.get("http", {})
    f = PlaywrightFetcher(
        headless=pw_cfg.get("headless", True),
        slow_mo_ms=pw_cfg.get("slow_mo_ms", 0),
        default_timeout_ms=pw_cfg.get("default_timeout_ms", 45000),
        rate_limit_seconds=http_cfg.get("rate_limit_seconds", 2.0),
        user_agent=http_cfg.get("user_agent"),
    )
    try:
        yield f
    finally:
        f.close()
