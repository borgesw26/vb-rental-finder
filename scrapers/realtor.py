"""Realtor.com scraper.

Strategy: fetch the public rentals search page for Virginia Beach (filtered
to single-family homes), then pull __NEXT_DATA__. The exact JSON path
shifts; we walk the tree for listing-shaped objects.

FRAGILE: Realtor.com may serve a bot challenge or empty SSR payload. We fall
back to Playwright when httpx returns no usable data.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.normalize import extract_zip, make_dedup_key, parse_float, parse_int, parse_money
from core.schema import Listing

from .base import extract_next_data, safe_get
from .json_walk import looks_like_listing, walk

log = logging.getLogger(__name__)

NAME = "realtor"

# Single-family + rentals + Virginia Beach, paginated.
SEARCH_URLS = [
    "https://www.realtor.com/apartments/Virginia-Beach_VA/type-single-family-home",
    "https://www.realtor.com/realestateandhomes-search/Virginia-Beach_VA/type-single-family-home/show-rent",
]


def scrape(cfg: dict, http, get_pw, log=log) -> list[Listing]:
    results: list[Listing] = []
    seen_urls: set[str] = set()

    for url in SEARCH_URLS:
        html = _fetch(http, get_pw, url)
        if not html:
            log.info("realtor: no html for %s", url)
            continue
        data = extract_next_data(html)
        if not data:
            log.info("realtor: no __NEXT_DATA__ for %s", url)
            continue

        for node in walk(data):
            if not looks_like_listing(node):
                continue
            listing = _node_to_listing(node)
            if not listing:
                continue
            if listing.listing_url in seen_urls:
                continue
            seen_urls.add(listing.listing_url)
            results.append(listing)
        log.info("realtor: %d listings collected from %s", len(results), url)
        if results:
            break  # First search URL that produced data is enough.

    return results


def _fetch(http, get_pw, url: str) -> Optional[str]:
    try:
        resp = http.get(url, headers={
            "Referer": "https://www.realtor.com/",
        })
        if resp.status_code == 200 and "__NEXT_DATA__" in resp.text:
            return resp.text
    except Exception as e:
        log.debug("realtor httpx failed for %s: %s", url, e)

    pw = get_pw()
    if pw is None:
        return None
    return pw.fetch(url, wait_selector="script#__NEXT_DATA__")


def _node_to_listing(node: dict) -> Optional[Listing]:
    addr_node = node.get("address") or node.get("location") or {}
    if isinstance(addr_node, dict):
        line = (
            addr_node.get("line")
            or addr_node.get("street_address")
            or addr_node.get("streetAddress")
            or addr_node.get("addressLine")
        )
        city = addr_node.get("city")
        state = addr_node.get("state_code") or addr_node.get("stateCode") or addr_node.get("state")
        zip_ = addr_node.get("postal_code") or addr_node.get("zipCode") or addr_node.get("postalCode")
    elif isinstance(addr_node, str):
        line = addr_node
        city = state = zip_ = None
    else:
        return None

    if not line:
        return None

    desc = node.get("description") or {}
    beds = parse_float(safe_get(desc, "beds") if isinstance(desc, dict) else None) \
        or parse_float(node.get("beds")) or parse_float(node.get("bedrooms"))
    baths = parse_float(safe_get(desc, "baths_consolidated") if isinstance(desc, dict) else None) \
        or parse_float(safe_get(desc, "baths") if isinstance(desc, dict) else None) \
        or parse_float(node.get("baths")) or parse_float(node.get("bathrooms"))
    sqft = parse_int(safe_get(desc, "sqft") if isinstance(desc, dict) else None) \
        or parse_int(node.get("sqft")) or parse_int(node.get("livingArea"))
    year_built = parse_int(safe_get(desc, "year_built") if isinstance(desc, dict) else None) \
        or parse_int(node.get("year_built")) or parse_int(node.get("yearBuilt"))
    prop_type = (
        (safe_get(desc, "type") if isinstance(desc, dict) else None)
        or node.get("type") or node.get("prop_type") or node.get("propertyType")
    )

    rent = parse_money(
        node.get("list_price") or node.get("price")
        or node.get("price_min") or node.get("rent")
        or safe_get(node, "list_price_min")
    )

    href = node.get("href") or node.get("url") or node.get("permalink") or node.get("detailUrl")
    if href and href.startswith("/"):
        listing_url = "https://www.realtor.com" + href
    else:
        listing_url = href

    if not listing_url:
        # Some Realtor records expose only listing_id; build from that.
        prop_id = node.get("property_id") or node.get("propertyId") or node.get("listing_id")
        if prop_id:
            listing_url = f"https://www.realtor.com/realestateandhomes-detail/M{prop_id}"
        else:
            return None

    photos: list[str] = []
    primary = node.get("primary_photo") or node.get("primaryPhoto")
    if isinstance(primary, dict) and primary.get("href"):
        photos.append(primary["href"])
    for p in (node.get("photos") or []):
        if isinstance(p, dict) and p.get("href"):
            photos.append(p["href"])

    mls = node.get("mls") or {}
    mls_number = (
        (mls.get("id") if isinstance(mls, dict) else None)
        or node.get("mls_id")
        or node.get("mlsId")
    )

    listed = node.get("list_date") or node.get("listDate")

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
        year_built=year_built,
        rent=rent,
        property_type=str(prop_type).replace("_", " ") if prop_type else None,
        mls_number=str(mls_number) if mls_number else None,
        photos=photos,
        listed_date=str(listed) if listed else None,
    )
    listing.dedup_key = make_dedup_key(listing.address, listing.beds, listing.baths)
    return listing
