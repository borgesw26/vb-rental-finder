"""Craigslist (Hampton Roads) scraper.

Strategy: hit the apa search endpoint with housing_type=6 (house), narrowed
by min_price/max_price and a Virginia Beach postal anchor. Parse the JSON
embedded in the modern Craigslist results page; fall back to RSS.

Less fragile than the big sites but listings are user-posted so quality is
mixed and address granularity varies.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import feedparser
from selectolax.parser import HTMLParser

from core.normalize import extract_zip, make_dedup_key, parse_float, parse_int, parse_money
from core.schema import Listing

log = logging.getLogger(__name__)

NAME = "craigslist"

# housing_type=6 -> "house"; bundleDuplicates dedupes across reposts
_BASE = "https://hampton.craigslist.org/search/apa"
_PARAMS = {
    "bundleDuplicates": "1",
    "housing_type": "6",
    "max_price": "3300",
    "min_price": "2300",
    "postal": "23454",
    "search_distance": "8",
    "query": "Virginia Beach",
}


def _build_search_url(extra: Optional[dict] = None) -> str:
    params = dict(_PARAMS)
    if extra:
        params.update(extra)
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{_BASE}?{qs}"


def scrape(cfg: dict, http, get_pw, log=log) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()

    # 1) Try modern HTML page (data is in inline JSON)
    url = _build_search_url()
    try:
        resp = http.get(url, headers={"Accept": "text/html"})
        if resp.status_code == 200:
            for l in _from_search_html(resp.text):
                if l.listing_url not in seen:
                    seen.add(l.listing_url)
                    out.append(l)
    except Exception as e:
        log.debug("craigslist html failed: %s", e)

    # 2) RSS fallback
    if not out:
        rss_url = _build_search_url({"format": "rss"})
        try:
            resp = http.get(rss_url, headers={"Accept": "application/rss+xml,application/xml"})
            if resp.status_code == 200:
                for l in _from_rss(resp.text):
                    if l.listing_url not in seen:
                        seen.add(l.listing_url)
                        out.append(l)
        except Exception as e:
            log.debug("craigslist rss failed: %s", e)

    log.info("craigslist: %d listings", len(out))
    return out


_INLINE_JSON_RE = re.compile(
    r"id=\"ld_searchpage_results\"[^>]*>(\{.*?\})</script>", re.DOTALL
)


def _from_search_html(html: str) -> list[Listing]:
    out: list[Listing] = []

    # Try JSON-LD ItemList
    m = _INLINE_JSON_RE.search(html or "")
    if m:
        try:
            blob = json.loads(m.group(1))
            for it in (blob.get("itemListElement") or []):
                node = it.get("item") if isinstance(it.get("item"), dict) else it
                if not isinstance(node, dict):
                    continue
                url = node.get("url") or node.get("@id")
                if not url:
                    continue
                addr = node.get("name") or "Virginia Beach, VA"
                offer = node.get("offers") or {}
                if isinstance(offer, list):
                    offer = offer[0] if offer else {}
                rent = parse_money(offer.get("price") if isinstance(offer, dict) else None)
                l = Listing(
                    source=NAME,
                    listing_url=url,
                    address=addr,
                    city="Virginia Beach",
                    state="VA",
                    rent=rent,
                    description=node.get("description"),
                    property_type="house",
                )
                l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
                out.append(l)
            if out:
                return out
        except json.JSONDecodeError:
            pass

    # Fall back to DOM cards
    tree = HTMLParser(html or "")
    for li in tree.css("li.cl-static-search-result, li.cl-search-result, .result-row"):
        link = li.css_first("a[href]")
        if not link:
            continue
        url = link.attributes.get("href") or ""
        if not url.startswith("http"):
            continue
        title_el = li.css_first(".title, .result-title, .titlestring, .label")
        title = title_el.text().strip() if title_el else None
        price_el = li.css_first(".price, .result-price")
        rent = parse_money(price_el.text() if price_el else None)
        meta_el = li.css_first(".housing, .result-meta, .meta")
        meta = meta_el.text(separator=" ") if meta_el else ""
        beds = baths = sqft = None
        m = re.search(r"(\d+)\s*br", meta, re.I)
        if m: beds = float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*ba", meta, re.I)
        if m: baths = float(m.group(1))
        m = re.search(r"(\d{3,5})\s*ft", meta, re.I)
        if m: sqft = parse_int(m.group(1))
        l = Listing(
            source=NAME,
            listing_url=url,
            address=title or "Virginia Beach, VA",
            city="Virginia Beach",
            state="VA",
            beds=beds,
            baths=baths,
            sqft=sqft,
            rent=rent,
            property_type="house",
            description=title,
        )
        l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
        out.append(l)
    return out


def _from_rss(xml: str) -> list[Listing]:
    out: list[Listing] = []
    feed = feedparser.parse(xml)
    for entry in feed.entries:
        url = entry.get("link") or entry.get("id")
        if not url:
            continue
        title = entry.get("title", "")
        desc = entry.get("summary", "") or entry.get("description", "")
        rent = parse_money(_extract_first_dollar(title) or _extract_first_dollar(desc))
        l = Listing(
            source=NAME,
            listing_url=url,
            address=title or "Virginia Beach, VA",
            city="Virginia Beach",
            state="VA",
            rent=rent,
            description=desc,
            listed_date=entry.get("updated") or entry.get("published"),
            property_type="house",
        )
        l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
        out.append(l)
    return out


_DOLLAR_RE = re.compile(r"\$([\d,]+)")


def _extract_first_dollar(text: str) -> Optional[str]:
    if not text:
        return None
    m = _DOLLAR_RE.search(text)
    return m.group(1) if m else None
