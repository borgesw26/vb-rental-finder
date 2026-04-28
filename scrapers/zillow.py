"""Zillow scraper.

Strategy: load the rentals/houses search page for Virginia Beach in Playwright
(stealth-patched). Pull __NEXT_DATA__ if present, else parse the legacy
window-init script. Walk the tree for listing-shaped objects.

FRAGILE: Zillow aggressively rejects headless and same-IP traffic. Expect
0 results sometimes; this is not a code bug.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from core.normalize import extract_zip, make_dedup_key, parse_float, parse_int, parse_money
from core.schema import Listing

from .base import extract_next_data
from .json_walk import looks_like_listing, walk

log = logging.getLogger(__name__)

NAME = "zillow"

# Filtered to Houses and rent band. Zillow rewrites this URL into a
# searchQueryState param on first visit.
SEARCH_URL = (
    "https://www.zillow.com/virginia-beach-va/rentals/houses/"
    "?searchQueryState="
    + json.dumps({
        "pagination": {},
        "isMapVisible": False,
        "mapBounds": {
            "west": -76.30, "east": -75.85,
            "south": 36.55, "north": 36.95,
        },
        "filterState": {
            "fr": {"value": True},
            "fsba": {"value": False},
            "fsbo": {"value": False},
            "nc": {"value": False},
            "cmsn": {"value": False},
            "auc": {"value": False},
            "fore": {"value": False},
            "ah": {"value": True},
            "tow": {"value": False},
            "apa": {"value": False},
            "manu": {"value": False},
            "apco": {"value": False},
            "con": {"value": False},
            "mp": {"min": 2300, "max": 3300},
        },
        "isListVisible": True,
        "regionSelection": [{"regionId": 21172, "regionType": 6}],
    }, separators=(",", ":"))
)


def scrape(cfg: dict, http, get_pw, log=log) -> list[Listing]:
    pw = get_pw()
    if pw is None:
        log.warning("zillow: Playwright unavailable; skipping")
        return []

    html = pw.fetch(SEARCH_URL, wait_selector="article, [data-test='property-card']")
    if not html:
        log.info("zillow: no html returned")
        return []

    listings: list[Listing] = []
    seen: set[str] = set()

    data = extract_next_data(html) or _legacy_search_results(html)
    if data:
        for node in walk(data):
            if not looks_like_listing(node):
                continue
            l = _node_to_listing(node)
            if l and l.listing_url not in seen:
                seen.add(l.listing_url)
                listings.append(l)

    if not listings:
        # Last resort: scrape rendered cards by selector
        listings = _from_dom(html)
        for l in listings:
            seen.add(l.listing_url)

    log.info("zillow: %d listings", len(listings))
    return listings


_LEGACY_RE = re.compile(r"window\['?\"?searchPageState\"?'?\s*=\s*(\{.*?\});", re.DOTALL)


def _legacy_search_results(html: str) -> Optional[dict]:
    m = _LEGACY_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _node_to_listing(node: dict) -> Optional[Listing]:
    address = (
        node.get("address")
        or node.get("addressStreet")
        or node.get("streetAddress")
    )
    if isinstance(address, dict):
        line = address.get("streetAddress") or address.get("line")
        city = address.get("city")
        state = address.get("state")
        zip_ = address.get("zipcode") or address.get("postalCode")
    else:
        line = address
        city = node.get("addressCity")
        state = node.get("addressState")
        zip_ = node.get("addressZipcode")

    if not line:
        return None

    rent = parse_money(
        node.get("price")
        or node.get("priceForHDP")
        or node.get("unformattedPrice")
        or node.get("rent")
    )
    beds = parse_float(node.get("beds") or node.get("bedrooms"))
    baths = parse_float(node.get("baths") or node.get("bathrooms"))
    sqft = parse_int(node.get("area") or node.get("livingArea"))

    href = node.get("detailUrl") or node.get("hdpUrl") or node.get("url")
    if href and href.startswith("/"):
        listing_url = "https://www.zillow.com" + href
    else:
        listing_url = href
    if not listing_url:
        return None

    prop_type = node.get("hdpData", {}).get("homeInfo", {}).get("homeType") if isinstance(node.get("hdpData"), dict) else None
    if not prop_type:
        prop_type = node.get("homeType") or node.get("propertyType")

    photos = []
    img = node.get("imgSrc") or node.get("imageUrl")
    if img:
        photos.append(img)
    carousel = node.get("carouselPhotos") or []
    for c in carousel:
        if isinstance(c, dict) and c.get("url"):
            photos.append(c["url"])

    listing = Listing(
        source=NAME,
        listing_url=listing_url,
        address=line,
        city=city,
        state=state,
        zip=zip_ or extract_zip(line),
        beds=beds,
        baths=baths,
        sqft=sqft,
        rent=rent,
        property_type=str(prop_type).replace("_", " ").lower() if prop_type else None,
        photos=photos,
    )
    listing.dedup_key = make_dedup_key(listing.address, listing.beds, listing.baths)
    return listing


def _from_dom(html: str) -> list[Listing]:
    """Last-ditch: parse rendered property-card HTML."""
    from selectolax.parser import HTMLParser

    out: list[Listing] = []
    tree = HTMLParser(html)
    for card in tree.css("article, [data-test='property-card']"):
        link = card.css_first("a[href]")
        if not link:
            continue
        href = link.attributes.get("href") or ""
        if href.startswith("/"):
            href = "https://www.zillow.com" + href
        addr = card.css_first("address")
        rent_el = card.css_first("[data-test='property-card-price']")
        beds_baths = card.css_first("ul")
        beds = baths = sqft = None
        if beds_baths:
            text = beds_baths.text(separator=" ")
            m = re.search(r"(\d+)\s*bd", text, re.I)
            if m: beds = float(m.group(1))
            m = re.search(r"(\d+(?:\.\d+)?)\s*ba", text, re.I)
            if m: baths = float(m.group(1))
            m = re.search(r"([\d,]+)\s*sqft", text, re.I)
            if m: sqft = parse_int(m.group(1))
        rent = parse_money(rent_el.text() if rent_el else None)
        line = addr.text().strip() if addr else None
        if not line or not href:
            continue
        listing = Listing(
            source=NAME,
            listing_url=href,
            address=line,
            beds=beds,
            baths=baths,
            sqft=sqft,
            rent=rent,
            zip=extract_zip(line),
        )
        listing.dedup_key = make_dedup_key(listing.address, listing.beds, listing.baths)
        out.append(listing)
    return out
