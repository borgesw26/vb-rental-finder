"""Homes.com scraper.

Strategy: Cloudflare-protected. Use Playwright stealth, then look for
JSON-LD `RealEstateListing` blobs and structured property cards.

FRAGILE: Homes.com aggressively challenges automation. Expect this scraper
to return 0 results in many runs.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from selectolax.parser import HTMLParser

from core.normalize import extract_zip, make_dedup_key, parse_float, parse_int, parse_money
from core.schema import Listing

from .base import extract_jsonld

log = logging.getLogger(__name__)

NAME = "homesdotcom"

SEARCH_URL = (
    "https://www.homes.com/virginia-beach-va/houses-for-rent/"
    "?price_min=2300&price_max=3300"
)


def scrape(cfg: dict, http, get_pw, log=log) -> list[Listing]:
    pw = get_pw()
    if pw is None:
        log.warning("homesdotcom: Playwright unavailable; skipping")
        return []

    html = pw.fetch(SEARCH_URL, wait_selector="ul#placardContainer, .placard-cont, [data-listing-key]")
    if not html:
        log.info("homesdotcom: no html")
        return []

    out: list[Listing] = []
    seen: set[str] = set()

    # Try JSON-LD first
    for blob in extract_jsonld(html):
        for l in _from_jsonld(blob):
            if l.listing_url not in seen:
                seen.add(l.listing_url)
                out.append(l)

    # Fall back to DOM cards
    if not out:
        for l in _from_dom(html):
            if l.listing_url not in seen:
                seen.add(l.listing_url)
                out.append(l)

    log.info("homesdotcom: %d listings", len(out))
    return out


def _from_jsonld(blob: dict) -> list[Listing]:
    out: list[Listing] = []
    items: list[dict] = []
    if blob.get("@type") in ("ItemList", "RealEstateListing", "Residence"):
        items = blob.get("itemListElement") or [blob]
    elif "@graph" in blob:
        items = [g for g in blob.get("@graph", []) if isinstance(g, dict)]
    else:
        items = [blob]

    for it in items:
        node = it.get("item") if isinstance(it.get("item"), dict) else it
        if not isinstance(node, dict):
            continue
        addr = node.get("address") or {}
        if isinstance(addr, dict):
            line = addr.get("streetAddress")
            city = addr.get("addressLocality")
            state = addr.get("addressRegion")
            zip_ = addr.get("postalCode")
        else:
            line = addr
            city = state = zip_ = None
        if not line:
            continue

        url = node.get("url") or node.get("@id")
        if not url:
            continue

        offer = node.get("offers") or {}
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        rent = parse_money(offer.get("price")) if isinstance(offer, dict) else None
        rent = rent or parse_money(node.get("price"))

        beds = parse_float(node.get("numberOfRooms") or node.get("numberOfBedrooms"))
        baths = parse_float(node.get("numberOfBathroomsTotal") or node.get("numberOfBathrooms"))
        sqft_node = node.get("floorSize") or {}
        sqft = parse_int(sqft_node.get("value") if isinstance(sqft_node, dict) else sqft_node)

        l = Listing(
            source=NAME,
            listing_url=url,
            address=line,
            city=city,
            state=state,
            zip=zip_ or extract_zip(line),
            beds=beds,
            baths=baths,
            sqft=sqft,
            rent=rent,
            property_type="house",  # We restricted via URL
        )
        l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
        out.append(l)
    return out


_BEDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bd|bed)", re.I)
_BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ba|bath)", re.I)
_SQFT_RE = re.compile(r"([\d,]+)\s*sq\s*ft", re.I)


def _from_dom(html: str) -> list[Listing]:
    out: list[Listing] = []
    tree = HTMLParser(html)
    cards = tree.css("[data-listing-key], li.placard, .placard-cont, .for-rent-content-container")
    for card in cards:
        link = card.css_first("a[href]")
        if not link:
            continue
        url = link.attributes.get("href") or ""
        if url.startswith("/"):
            url = "https://www.homes.com" + url
        if not url.startswith("http"):
            continue

        addr_el = card.css_first(".property-name, .address, [class*='address']")
        addr = addr_el.text(separator=", ").strip() if addr_el else None

        price_el = card.css_first(".price-container, .price, [class*='price']")
        rent = parse_money(price_el.text() if price_el else None)

        text_blob = card.text(separator=" ")
        beds = baths = sqft = None
        m = _BEDS_RE.search(text_blob)
        if m: beds = float(m.group(1))
        m = _BATHS_RE.search(text_blob)
        if m: baths = float(m.group(1))
        m = _SQFT_RE.search(text_blob)
        if m: sqft = parse_int(m.group(1))

        if not addr or not url:
            continue

        l = Listing(
            source=NAME,
            listing_url=url,
            address=addr,
            beds=beds,
            baths=baths,
            sqft=sqft,
            rent=rent,
            zip=extract_zip(addr),
            property_type="house",
        )
        l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
        out.append(l)
    return out
