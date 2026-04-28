"""Shared scraper utilities and the scraper interface."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)


def extract_next_data(html: str) -> Optional[dict]:
    """Extract the __NEXT_DATA__ JSON blob common to Next.js sites."""
    if not html:
        return None
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")
    if node is None:
        return None
    try:
        return json.loads(node.text())
    except (ValueError, json.JSONDecodeError):
        return None


def extract_first_json_blob(html: str, *script_selectors: str) -> Optional[dict]:
    """Best-effort: try several script selectors, return first parseable JSON."""
    if not html:
        return None
    tree = HTMLParser(html)
    for sel in script_selectors:
        node = tree.css_first(sel)
        if node is None:
            continue
        text = node.text() or ""
        try:
            return json.loads(text)
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def safe_get(d: Any, *keys, default=None):
    """Walk nested dicts/lists safely."""
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(k, int):
            try:
                cur = cur[k]
            except (IndexError, TypeError):
                return default
        else:
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                return default
    return cur if cur is not None else default


_SCRIPT_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def extract_jsonld(html: str) -> list[dict]:
    """Pull all JSON-LD documents from a page."""
    out: list[dict] = []
    for m in _SCRIPT_JSON_RE.finditer(html or ""):
        text = m.group(1).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out
