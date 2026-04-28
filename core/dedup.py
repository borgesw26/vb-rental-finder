"""Deduplication. MLS-sourced records win on conflict; merge photo URLs."""
from __future__ import annotations

import logging
from typing import Iterable

from .normalize import make_dedup_key
from .schema import Listing

log = logging.getLogger(__name__)

# Source preference. Lower index = preferred (when MLS-equivalent).
_SOURCE_PRIORITY = [
    "realtor",      # MLS feed via NAR
    "redfin",
    "zillow",
    "homesdotcom",
    "craigslist",
]


def _priority(source: str) -> int:
    s = (source or "").lower()
    if s in _SOURCE_PRIORITY:
        return _SOURCE_PRIORITY.index(s)
    return len(_SOURCE_PRIORITY) + 1


def _has_mls(l: Listing) -> bool:
    return bool(l.mls_number)


def deduplicate(listings: Iterable[Listing]) -> list[Listing]:
    """Group by dedup_key. Keep MLS record on conflict; merge photos+description.

    Listings without a dedup_key are passed through unchanged (they cannot be
    grouped, so we err toward keeping them).
    """
    keyed: dict[str, Listing] = {}
    unkeyed: list[Listing] = []

    for l in listings:
        if not l.dedup_key:
            l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
        if not l.dedup_key:
            unkeyed.append(l)
            continue

        existing = keyed.get(l.dedup_key)
        if existing is None:
            keyed[l.dedup_key] = l
            continue

        winner, loser = _pick_winner(existing, l)
        # Merge photos (preserve order, drop dupes)
        merged_photos = list(dict.fromkeys((winner.photos or []) + (loser.photos or [])))
        winner.photos = merged_photos
        # Fill in any missing fields on the winner from the loser
        for field_name in (
            "description", "year_built", "sqft", "lot_size",
            "deposit", "pets_allowed", "listed_date", "mls_number",
            "property_type",
        ):
            if getattr(winner, field_name) in (None, "") and getattr(loser, field_name) not in (None, ""):
                setattr(winner, field_name, getattr(loser, field_name))
        keyed[l.dedup_key] = winner

    return list(keyed.values()) + unkeyed


def _pick_winner(a: Listing, b: Listing) -> tuple[Listing, Listing]:
    a_mls = _has_mls(a)
    b_mls = _has_mls(b)
    if a_mls and not b_mls:
        return a, b
    if b_mls and not a_mls:
        return b, a
    # Otherwise, source priority decides.
    if _priority(a.source) <= _priority(b.source):
        return a, b
    return b, a
