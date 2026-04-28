"""Redfin scraper.

Strategy: hit Redfin's stingray gis-csv endpoint for rentals (uipt=1 = SFH).
Returns CSV (sometimes with a JS-anti-XSSI prefix). For Virginia Beach the
city region_id is 20290, region_type=6.

If gis-csv is unavailable for rentals (Redfin sometimes scopes it to for-sale),
we fall back to scraping the rentals search HTML in Playwright.

FRAGILE: Redfin's rental coverage in Hampton Roads is sparse and the gis-csv
endpoint rate-limits aggressively.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Optional

from core.normalize import extract_zip, make_dedup_key, parse_float, parse_int, parse_money
from core.schema import Listing

from .base import extract_next_data
from .json_walk import looks_like_listing, walk

log = logging.getLogger(__name__)

NAME = "redfin"

# region_id 20290 = Virginia Beach (city) per Redfin's gis taxonomy.
GIS_CSV_URL = (
    "https://www.redfin.com/stingray/api/gis-csv"
    "?al=1&isRentals=true&market=hamptonroads"
    "&min_price=2300&max_price=3300"
    "&num_homes=350&ord=redfin-recommended-asc"
    "&page_number=1&propertyType=Houses"
    "&region_id=20290&region_type=6"
    "&sf=1,2,3,5,6,7&status=9&uipt=1&v=8"
)

SEARCH_URL = "https://www.redfin.com/city/20290/VA/Virginia-Beach/apartments-for-rent"


def scrape(cfg: dict, http, get_pw, log=log) -> list[Listing]:
    listings = _from_gis_csv(http)
    if listings:
        log.info("redfin: %d via gis-csv", len(listings))
        return listings

    # Fall back to rendered HTML
    pw = get_pw()
    if pw is None:
        log.warning("redfin: gis-csv empty and Playwright unavailable")
        return []

    html = pw.fetch(SEARCH_URL, wait_selector="div.HomeCardContainer, div.HomeViews")
    if not html:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    data = extract_next_data(html)
    if data:
        for node in walk(data):
            if not looks_like_listing(node):
                continue
            l = _node_to_listing(node)
            if l and l.listing_url not in seen:
                seen.add(l.listing_url)
                out.append(l)
    log.info("redfin: %d via fallback", len(out))
    return out


def _from_gis_csv(http) -> list[Listing]:
    try:
        resp = http.get(GIS_CSV_URL, headers={
            "Accept": "text/csv,*/*;q=0.8",
            "Referer": "https://www.redfin.com/",
        })
    except Exception as e:
        log.debug("redfin gis-csv failed: %s", e)
        return []
    if resp.status_code != 200:
        log.debug("redfin gis-csv status %s", resp.status_code)
        return []

    text = resp.text or ""
    # Redfin prefixes responses with `{}&&` to thwart JS hijacking.
    if text.startswith("{}&&"):
        text = text[4:]
    if not text.strip() or "\n" not in text:
        return []

    out: list[Listing] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        addr = row.get("ADDRESS") or row.get("address")
        if not addr:
            continue
        rent = parse_money(row.get("PRICE") or row.get("price"))
        beds = parse_float(row.get("BEDS") or row.get("beds"))
        baths = parse_float(row.get("BATHS") or row.get("baths"))
        sqft = parse_int(row.get("SQUARE FEET") or row.get("squareFeet"))
        ptype = (row.get("PROPERTY TYPE") or row.get("propertyType") or "").strip()
        zip_ = row.get("ZIP OR POSTAL CODE") or row.get("zipOrPostalCode")
        url = row.get("URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis FOR INFO ON PRICING)") or row.get("URL")
        if not url:
            continue
        if url.startswith("/"):
            url = "https://www.redfin.com" + url
        l = Listing(
            source=NAME,
            listing_url=url,
            address=addr,
            city=row.get("CITY"),
            state=row.get("STATE OR PROVINCE") or row.get("STATE"),
            zip=zip_ or extract_zip(addr),
            beds=beds,
            baths=baths,
            sqft=sqft,
            rent=rent,
            property_type=ptype.lower() if ptype else None,
            year_built=parse_int(row.get("YEAR BUILT")),
            mls_number=row.get("MLS#") or row.get("MLS NUMBER"),
        )
        l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
        out.append(l)
    return out


def _node_to_listing(node: dict) -> Optional[Listing]:
    address = node.get("streetLine", {})
    if isinstance(address, dict):
        line = address.get("value") or address.get("formattedShort")
    else:
        line = address
    city = (node.get("city") or {}).get("name") if isinstance(node.get("city"), dict) else node.get("city")
    state = (node.get("state") or {}).get("value") if isinstance(node.get("state"), dict) else node.get("state")
    zip_ = (node.get("postalCode") or {}).get("value") if isinstance(node.get("postalCode"), dict) else node.get("postalCode")

    if not line:
        return None

    rent = parse_money(node.get("price", {}).get("value") if isinstance(node.get("price"), dict) else node.get("price"))
    beds = parse_float(node.get("beds"))
    baths = parse_float(node.get("baths"))
    sqft = parse_int((node.get("sqFt") or {}).get("value") if isinstance(node.get("sqFt"), dict) else node.get("sqFt"))
    ptype = node.get("propertyType")

    href = node.get("url")
    if href and href.startswith("/"):
        href = "https://www.redfin.com" + href

    if not href:
        return None

    l = Listing(
        source=NAME,
        listing_url=href,
        address=line,
        city=city,
        state=state,
        zip=zip_ or extract_zip(line),
        beds=beds,
        baths=baths,
        sqft=sqft,
        rent=rent,
        property_type=str(ptype).lower() if ptype else None,
    )
    l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
    return l
