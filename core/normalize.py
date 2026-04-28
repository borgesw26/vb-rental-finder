"""Address normalization and dedup-key construction."""
from __future__ import annotations

import logging
import re
from typing import Optional

try:
    import usaddress
except ImportError:  # pragma: no cover
    usaddress = None

log = logging.getLogger(__name__)

_STREET_TYPE_MAP = {
    "street": "st", "st.": "st", "st": "st",
    "avenue": "ave", "ave.": "ave", "av": "ave", "ave": "ave",
    "boulevard": "blvd", "blvd.": "blvd", "blvd": "blvd",
    "road": "rd", "rd.": "rd", "rd": "rd",
    "drive": "dr", "dr.": "dr", "dr": "dr",
    "lane": "ln", "ln.": "ln", "ln": "ln",
    "court": "ct", "ct.": "ct", "ct": "ct",
    "place": "pl", "pl.": "pl", "pl": "pl",
    "terrace": "ter", "ter.": "ter", "ter": "ter",
    "circle": "cir", "cir.": "cir", "cir": "cir",
    "parkway": "pkwy", "pkwy.": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy.": "hwy", "hwy": "hwy",
    "trail": "trl", "trl.": "trl", "trl": "trl",
    "way": "way",
    "square": "sq", "sq.": "sq", "sq": "sq",
}

_DIRECTION_MAP = {
    "north": "n", "n.": "n",
    "south": "s", "s.": "s",
    "east": "e", "e.": "e",
    "west": "w", "w.": "w",
    "northeast": "ne", "n.e.": "ne", "n.e": "ne",
    "northwest": "nw", "n.w.": "nw",
    "southeast": "se", "s.e.": "se",
    "southwest": "sw", "s.w.": "sw",
}


def _basic_clean(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[#,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_address(address: Optional[str]) -> Optional[str]:
    """Best-effort canonical address string for dedup."""
    if not address:
        return None
    raw = _basic_clean(address)
    if not raw:
        return None

    # Strip apt/unit suffixes for SFH dedup
    raw = re.sub(
        r"\b(apt|apartment|unit|ste|suite|#)\.?\s*[\w-]+$",
        "",
        raw,
    ).strip()

    if usaddress is None:
        return _heuristic_normalize(raw)

    try:
        tagged, _ = usaddress.tag(raw)
    except Exception:
        return _heuristic_normalize(raw)

    parts = []
    if "AddressNumber" in tagged:
        parts.append(tagged["AddressNumber"])
    if "StreetNamePreDirectional" in tagged:
        d = tagged["StreetNamePreDirectional"].lower().rstrip(".")
        parts.append(_DIRECTION_MAP.get(d, d))
    if "StreetName" in tagged:
        parts.append(tagged["StreetName"].lower())
    if "StreetNamePostType" in tagged:
        t = tagged["StreetNamePostType"].lower().rstrip(".")
        parts.append(_STREET_TYPE_MAP.get(t, t))
    if "StreetNamePostDirectional" in tagged:
        d = tagged["StreetNamePostDirectional"].lower().rstrip(".")
        parts.append(_DIRECTION_MAP.get(d, d))

    street = " ".join(parts).strip()
    return street or _heuristic_normalize(raw)


def _heuristic_normalize(raw: str) -> str:
    tokens = []
    for t in raw.split():
        t = t.rstrip(".,")
        if t in _STREET_TYPE_MAP:
            tokens.append(_STREET_TYPE_MAP[t])
        elif t in _DIRECTION_MAP:
            tokens.append(_DIRECTION_MAP[t])
        else:
            tokens.append(t)
    return " ".join(tokens)


def make_dedup_key(
    address: Optional[str],
    beds: Optional[float],
    baths: Optional[float],
) -> Optional[str]:
    norm = normalize_address(address)
    if not norm:
        return None
    b = f"{beds:.1f}" if beds is not None else "?"
    ba = f"{baths:.1f}" if baths is not None else "?"
    return f"{norm}|{b}|{ba}"


def parse_money(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = re.sub(r"[^\d.]", "", str(value))
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = re.sub(r"[^\d]", "", str(value))
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d.]", "", str(value))
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def extract_zip(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", address)
    return m.group(1) if m else None
