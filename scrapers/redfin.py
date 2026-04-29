"""Redfin scraper.

Strategy: Redfin exposes a working rentals JSON endpoint at
`/stingray/api/v1/search/rentals` keyed on `region_id` (one per zip code,
region_type=2 in their taxonomy). We pre-resolve the region IDs for all
Virginia Beach zip codes — fast and stable since Redfin's zip→region map
hasn't changed in years — and then iterate.

The CSV/gis-csv path is intentionally skipped: in current Redfin builds
`isRentals=true` is silently ignored on that endpoint, so it returns
for-sale data even when asked for rentals.

Less fragile than Zillow/Homes.com but Redfin's rental coverage in
Hampton Roads is sparse — single-digit results per zip.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from core.normalize import extract_zip, make_dedup_key, parse_float, parse_int, parse_money
from core.schema import Listing

log = logging.getLogger(__name__)

NAME = "redfin"

# Pre-discovered region_id (region_type=2 = zip code).
# Run scrapers/_discover_redfin_regions.py to refresh.
_VB_ZIP_REGIONS: dict[str, int] = {
    "23451": 9331, "23452": 9332, "23453": 9333, "23454": 9334,
    "23455": 9335, "23456": 9336, "23457": 9337, "23459": 9339,
    "23460": 9340, "23461": 9341, "23462": 9342, "23464": 9344,
    "23466": 9346,
}

# Redfin uipt codes: 1=House, 2=Condo, 3=Townhouse, 4=Multi-fam, 5=Land,
# 6=Other, 7=Mobile/Manufactured. We only want 1.
_RENTALS_API = (
    "https://www.redfin.com/stingray/api/v1/search/rentals"
    "?al=1&num_homes=350&page_number=1&region_id={rid}"
    "&region_type=2&uipt=1&v=8"
)

# propertyType integer in homeData — observed: 6 = SFH/condo lump (Redfin).
# We'll trust the URL slug instead: /home/ vs /apartment/.


def scrape(cfg: dict, http, get_pw, log=log) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    zips = cfg.get("zips") or list(_VB_ZIP_REGIONS.keys())

    for zip_ in zips:
        rid = _VB_ZIP_REGIONS.get(zip_) or _resolve_region(http, zip_)
        if not rid:
            continue
        url = _RENTALS_API.format(rid=rid)
        try:
            resp = http.get(url, headers={
                "Accept": "application/json",
                "Referer": f"https://www.redfin.com/zipcode/{zip_}/apartments-for-rent",
            })
        except Exception as e:
            log.debug("redfin api zip %s failed: %s", zip_, e)
            continue
        if resp.status_code != 200:
            log.debug("redfin api zip %s status=%s", zip_, resp.status_code)
            continue

        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]
        try:
            import json
            data = json.loads(text)
        except (ValueError, ImportError):
            continue

        for home in (data.get("homes") or []):
            l = _home_to_listing(home, default_zip=zip_)
            if not l:
                continue
            if l.listing_url in seen:
                continue
            seen.add(l.listing_url)
            out.append(l)

    log.info("redfin: %d listings across %d zips", len(out), len(zips))
    return out


def _resolve_region(http, zip_: str) -> Optional[int]:
    """Fall back to scraping the zip's rental page for region_id."""
    try:
        resp = http.get(f"https://www.redfin.com/zipcode/{zip_}/apartments-for-rent")
        m = re.search(r"region_id=(\d+)", resp.text or "")
        return int(m.group(1)) if m else None
    except Exception as e:
        log.debug("redfin region resolve failed for %s: %s", zip_, e)
        return None


def _home_to_listing(home: dict, default_zip: Optional[str] = None) -> Optional[Listing]:
    hd = home.get("homeData") if isinstance(home.get("homeData"), dict) else home
    rx = home.get("rentalExtension") or {}
    if not isinstance(hd, dict):
        return None

    url = hd.get("url") or ""
    if "/apartment/" in url:  # not a single-family listing
        return None
    if not url:
        return None
    if url.startswith("/"):
        url = "https://www.redfin.com" + url

    addr = hd.get("addressInfo") or {}
    street = addr.get("formattedStreetLine") or addr.get("street") or addr.get("streetLine")
    city = addr.get("city")
    state = addr.get("state")
    zip_ = addr.get("zip") or addr.get("postalCode") or default_zip

    if not street:
        m = re.search(r"/[A-Z]{2}/[^/]+/([^/]+?)(?:-\d{5})?(?:/unit-[^/]+)?/home/", url)
        if m:
            street = m.group(1).replace("-", " ")
        else:
            return None

    rent_range = rx.get("rentPriceRange") or {}
    rent = parse_money(rent_range.get("min")) or parse_money(rent_range.get("max"))

    bed_range = rx.get("bedRange") or {}
    beds = parse_float(bed_range.get("min")) or parse_float(bed_range.get("max"))

    bath_range = rx.get("bathRange") or {}
    baths = parse_float(bath_range.get("min")) or parse_float(bath_range.get("max"))

    sqft_range = rx.get("sqftRange") or {}
    sqft = parse_int(sqft_range.get("min")) or parse_int(sqft_range.get("max"))

    photos = []
    pi = hd.get("photosInfo") or {}
    pid = hd.get("propertyId")
    for rg in (pi.get("photoRanges") or []):
        try:
            start = int(rg.get("startPos", 0))
            end = int(rg.get("endPos", start))
            ver = rg.get("version", "1")
        except (TypeError, ValueError):
            continue
        if not pid:
            break
        for i in range(start, min(end, start + 5) + 1):
            photos.append(
                f"https://ssl.cdn-redfin.com/photo/rent/{pid}/genIslnoResize.0_{i}_{ver}.jpg"
            )

    listing = Listing(
        source=NAME,
        listing_url=url,
        address=street,
        city=city or "Virginia Beach",
        state=state or "VA",
        zip=zip_ or extract_zip(street),
        beds=beds,
        baths=baths,
        sqft=sqft,
        rent=rent,
        property_type="single family",
        photos=photos,
        description=rx.get("description"),
        listed_date=rx.get("lastUpdated") or rx.get("freshnessTimestamp"),
    )
    listing.dedup_key = make_dedup_key(listing.address, listing.beds, listing.baths)
    return listing
