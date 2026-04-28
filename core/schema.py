"""Common listing schema used across all scrapers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Listing:
    source: str
    listing_url: str

    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None

    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size: Optional[str] = None
    year_built: Optional[int] = None

    rent: Optional[int] = None
    deposit: Optional[int] = None
    pets_allowed: Optional[bool] = None

    property_type: Optional[str] = None
    mls_number: Optional[str] = None

    photos: list[str] = field(default_factory=list)
    description: Optional[str] = None

    listed_date: Optional[str] = None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    dedup_key: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["photos"] = list(self.photos or [])
        return d
