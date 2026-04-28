"""Filtering rules — single-family houses in Virginia Beach within rent band."""
from __future__ import annotations

import logging
from typing import Optional

from .schema import Listing

log = logging.getLogger(__name__)

# Tokens that disqualify a listing.
_DENY_TOKENS = (
    "townhouse", "townhome", "town home", "town house",
    "condo", "condominium",
    "apartment", "apt ", "apts ",
    "duplex", "triplex", "fourplex", "quadplex",
    "mobile home", "manufactured",
    "multi-family", "multi family", "multifamily",
    "co-op", "co op", "cooperative",
    " unit ", " #",  # likely sub-unit listing
)

_ALLOW_TYPES = {
    "single_family", "single-family", "single family",
    "house", "single family residence", "sfr", "sfh",
    "detached",
}


def is_single_family_house(listing: Listing) -> bool:
    """Return True if listing is plausibly a single-family house."""
    pt = (listing.property_type or "").lower().strip()
    if pt:
        if any(a in pt for a in _ALLOW_TYPES):
            return True
        # Explicit denylist hit on property_type
        if any(d.strip() in pt for d in _DENY_TOKENS if d.strip()):
            return False
        # Property type provided but not on allow list — be conservative.
        return False

    # Fall back to text heuristics.
    blob = " ".join(
        x for x in (
            listing.description,
            listing.address,
        ) if x
    ).lower()
    if any(d in blob for d in _DENY_TOKENS):
        return False
    # No contradicting signal & no positive type — accept tentatively.
    return True


def in_rent_band(listing: Listing, lo: int, hi: int) -> bool:
    if listing.rent is None:
        return False
    return lo <= listing.rent <= hi


def in_city(listing: Listing, city: str, state: str, zips: Optional[list[str]] = None) -> bool:
    city_lc = city.lower().strip()
    if listing.city and listing.city.lower().strip() == city_lc:
        return True
    if listing.address and city_lc in listing.address.lower():
        return True
    if zips and listing.zip and listing.zip in zips:
        return True
    return False


def passes_all(
    listing: Listing,
    *,
    city: str,
    state: str,
    zips: list[str],
    rent_min: int,
    rent_max: int,
) -> tuple[bool, str]:
    """Return (ok, reason_if_rejected)."""
    if not in_city(listing, city, state, zips):
        return False, "not in city"
    if not in_rent_band(listing, rent_min, rent_max):
        return False, f"rent {listing.rent} out of band"
    if not is_single_family_house(listing):
        return False, "not single-family house"
    return True, ""
