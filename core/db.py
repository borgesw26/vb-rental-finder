"""SQLite persistence layer."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .schema import Listing

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    listing_count INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    listing_url TEXT NOT NULL,
    address TEXT,
    city TEXT,
    state TEXT,
    zip TEXT,
    beds REAL,
    baths REAL,
    sqft INTEGER,
    lot_size TEXT,
    year_built INTEGER,
    rent INTEGER,
    deposit INTEGER,
    pets_allowed INTEGER,
    property_type TEXT,
    mls_number TEXT,
    photos_json TEXT,
    description TEXT,
    listed_date TEXT,
    scraped_at TEXT,
    dedup_key TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_listings_dedup ON listings(dedup_key);
CREATE INDEX IF NOT EXISTS idx_listings_run ON listings(run_id);
CREATE INDEX IF NOT EXISTS idx_listings_url ON listings(listing_url);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def start_run(self, notes: str = "") -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, notes) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), notes),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, listing_count: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, listing_count=? WHERE id=?",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    listing_count,
                    run_id,
                ),
            )

    def insert_listings(self, run_id: int, listings: Iterable[Listing]) -> int:
        rows = []
        for l in listings:
            rows.append((
                run_id,
                l.source,
                l.listing_url,
                l.address,
                l.city,
                l.state,
                l.zip,
                l.beds,
                l.baths,
                l.sqft,
                l.lot_size,
                l.year_built,
                l.rent,
                l.deposit,
                int(l.pets_allowed) if l.pets_allowed is not None else None,
                l.property_type,
                l.mls_number,
                json.dumps(list(l.photos or [])),
                l.description,
                l.listed_date,
                l.scraped_at,
                l.dedup_key,
            ))
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO listings (
                    run_id, source, listing_url, address, city, state, zip,
                    beds, baths, sqft, lot_size, year_built, rent, deposit,
                    pets_allowed, property_type, mls_number, photos_json,
                    description, listed_date, scraped_at, dedup_key
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
        return len(rows)

    def latest_two_runs(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 2"
            ).fetchall()
        return [r["id"] for r in rows]

    def listings_for_run(self, run_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM listings WHERE run_id = ?", (run_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["photos"] = json.loads(d.pop("photos_json") or "[]")
            except json.JSONDecodeError:
                d["photos"] = []
            out.append(d)
        return out
