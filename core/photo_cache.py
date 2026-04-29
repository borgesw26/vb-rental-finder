"""Local photo cache.

Many listing sites (Redfin in particular) hotlink-protect their images
via Referer/Origin checks, so embedding their CDN URLs directly in
report.html produces broken thumbnails. We download once, hash the URL
into a stable filename, and reference the local file from the report.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# Sniff first 12 bytes for content type when the server lies.
_MAGIC_TO_EXT = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),  # plus 'WEBP' at offset 8 — close enough
)


def _ext_from_bytes(data: bytes) -> Optional[str]:
    for magic, ext in _MAGIC_TO_EXT:
        if data.startswith(magic):
            return ext
    return None


class PhotoCache:
    def __init__(
        self,
        cache_dir: Path | str,
        *,
        rate_per_sec: float = 2.0,
        user_agent: str = "vb-rental-finder/0.1 (+personal use)",
        timeout_seconds: float = 20.0,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = 1.0 / max(rate_per_sec, 0.1)
        self._last = 0.0
        self._lock = threading.Lock()
        self.client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    @staticmethod
    def hash_url(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def existing_path(self, url: str) -> Optional[Path]:
        h = self.hash_url(url)
        for p in self.cache_dir.glob(f"{h}.*"):
            return p
        return None

    def _wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def cache(self, url: str, *, referer: Optional[str] = None) -> Optional[Path]:
        if not url:
            return None
        existing = self.existing_path(url)
        if existing:
            return existing

        self._wait()
        try:
            headers = {}
            if referer:
                headers["Referer"] = referer
            resp = self.client.get(url, headers=headers)
        except Exception as e:
            log.debug("photo fetch error %s: %s", url, e)
            return None
        if resp.status_code != 200 or not resp.content:
            log.debug("photo %s -> status %s", url, resp.status_code)
            return None

        ext = _ext_from_bytes(resp.content[:16])
        if not ext:
            ct = (resp.headers.get("content-type", "")).split(";")[0].strip()
            ext = mimetypes.guess_extension(ct) or ".jpg"
            if ext == ".jpe":
                ext = ".jpg"

        path = self.cache_dir / f"{self.hash_url(url)}{ext}"
        path.write_bytes(resp.content)
        return path

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
