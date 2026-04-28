"""Generic helper to find listing-shaped objects inside large JSON blobs.

Site-rendered Next.js / React payloads change layout often, so rather than
hard-coding the path we walk the tree and pick objects that look like a rental
listing (have an address, a rent-ish number, and beds/baths).
"""
from __future__ import annotations

from typing import Any, Iterator


def walk(obj: Any) -> Iterator[Any]:
    """Yield every node in a nested dict/list."""
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def looks_like_listing(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    keys = {k.lower() for k in node.keys()}
    has_address = bool(keys & {
        "address", "streetaddress", "addressline", "fulladdress",
        "addresswithoutunit", "street_address",
    }) or ("address" in keys)
    has_rent = bool(keys & {
        "price", "rent", "rent_min", "rentprice", "list_price",
        "rentestimate", "rentalprice", "monthly_rent",
    })
    has_url = bool(keys & {"url", "detailurl", "permalink", "href"})
    return has_address and (has_rent or has_url)
