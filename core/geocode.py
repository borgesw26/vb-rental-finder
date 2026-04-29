"""Nominatim geocoder with persistent JSON cache.

Per Nominatim's usage policy:
- Max 1 request / second.
- Identifying User-Agent with contact info.
- Cache results to avoid repeat lookups.

We key the cache on a normalized address+zip string so a re-run never
re-geocodes the same place.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)


def _norm_key(address: str, city: Optional[str], state: Optional[str], zip_: Optional[str]) -> str:
    parts = [
        address or "",
        city or "",
        state or "",
        zip_ or "",
    ]
    s = ", ".join(p.strip() for p in parts if p)
    s = s.lower()
    s = re.sub(r"[^a-z0-9, ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class Geocoder:
    def __init__(
        self,
        cache_path: Path | str = "core/geocode_cache.json",
        *,
        contact_email: Optional[str] = None,
        rate_per_sec: float = 1.0,
        timeout_seconds: float = 20.0,
    ):
        self.cache_path = Path(cache_path)
        self._cache: dict[str, dict] = {}
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                log.warning("geocode cache corrupt, starting fresh")
                self._cache = {}
        self._dirty = False
        self._min_interval = 1.0 / max(rate_per_sec, 0.1)
        self._last = 0.0
        self._lock = threading.Lock()
        ua = "vb-rental-finder/0.1"
        if contact_email:
            ua = f"{ua} ({contact_email})"
        self.client = httpx.Client(
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    def _wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def lookup(
        self,
        address: str,
        *,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_: Optional[str] = None,
    ) -> Optional[tuple[float, float]]:
        key = _norm_key(address, city, state, zip_)
        if not key:
            return None
        if key in self._cache:
            entry = self._cache[key]
            if entry.get("status") == "miss":
                return None
            lat = entry.get("lat")
            lng = entry.get("lng")
            if lat is not None and lng is not None:
                return float(lat), float(lng)

        # Build Nominatim query
        q_parts = [address]
        if city:
            q_parts.append(city)
        if state:
            q_parts.append(state)
        if zip_:
            q_parts.append(zip_)
        q = ", ".join(p for p in q_parts if p)

        self._wait()
        try:
            resp = self.client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 0,
                    "countrycodes": "us",
                },
            )
        except Exception as e:
            log.debug("geocode fetch error %s: %s", q, e)
            return None
        if resp.status_code != 200:
            log.debug("geocode %s -> status %s", q, resp.status_code)
            return None
        try:
            arr = resp.json()
        except json.JSONDecodeError:
            return None
        if not arr:
            self._cache[key] = {"status": "miss"}
            self._dirty = True
            return None
        first = arr[0]
        try:
            lat = float(first["lat"])
            lng = float(first["lon"])
        except (KeyError, ValueError, TypeError):
            return None
        self._cache[key] = {"status": "hit", "lat": lat, "lng": lng, "q": q}
        self._dirty = True
        return lat, lng

    def save(self) -> None:
        if not self._dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._dirty = False

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        self.save()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
