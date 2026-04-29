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
    local_photo: Optional[str] = None  # relative path from repo root, e.g. out/photos/<sha1>.jpg
    description: Optional[str] = None

    listed_date: Optional[str] = None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    dedup_key: Optional[str] = None

    @classmethod
    def from_db_row(cls, row: dict) -> "Listing":
        photos = row.get("photos") or []
        if isinstance(photos, str):
            import json as _j
            try:
                photos = _j.loads(photos)
            except Exception:
                photos = []
        return cls(
            source=row.get("source") or "",
            listing_url=row.get("listing_url") or "",
            address=row.get("address"),
            city=row.get("city"),
            state=row.get("state"),
            zip=row.get("zip"),
            beds=row.get("beds"),
            baths=row.get("baths"),
            sqft=row.get("sqft"),
            lot_size=row.get("lot_size"),
            year_built=row.get("year_built"),
            rent=row.get("rent"),
            deposit=row.get("deposit"),
            pets_allowed=bool(row.get("pets_allowed")) if row.get("pets_allowed") is not None else None,
            property_type=row.get("property_type"),
            mls_number=row.get("mls_number"),
            photos=list(photos) if photos else [],
            description=row.get("description"),
            listed_date=row.get("listed_date"),
            scraped_at=row.get("scraped_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            dedup_key=row.get("dedup_key"),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["photos"] = list(self.photos or [])
        return d
