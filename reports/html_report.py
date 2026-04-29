"""HTML report generation. Vanilla HTML + one CSS file. No build step."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from core.schema import Listing

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "source", "address", "city", "state", "zip",
    "beds", "baths", "sqft", "lot_size", "year_built",
    "rent", "deposit", "pets_allowed",
    "property_type", "mls_number",
    "listing_url", "description", "listed_date", "scraped_at",
    "photos", "lat", "lng",
]


def stable_id(listing: Listing) -> str:
    """Stable, URL-safe id derived from dedup_key (or listing_url fallback).
    Survives across runs — used by F4 to track seen/favorited state."""
    seed = listing.dedup_key or listing.listing_url or ""
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def write_csv(listings: Iterable[Listing], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for l in listings:
            w.writerow([
                l.source, l.address, l.city, l.state, l.zip,
                l.beds, l.baths, l.sqft, l.lot_size, l.year_built,
                l.rent, l.deposit,
                "" if l.pets_allowed is None else ("yes" if l.pets_allowed else "no"),
                l.property_type, l.mls_number,
                l.listing_url, l.description, l.listed_date, l.scraped_at,
                "|".join(l.photos or []),
                l.lat, l.lng,
            ])


def write_report(
    listings: list[Listing],
    out_path: Path,
    *,
    title: str = "Virginia Beach Rentals",
    extra_meta: str = "",
    css_src: Path | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if css_src is None:
        css_src = Path(__file__).parent / "styles.css"
    css_dest = out_path.parent / "styles.css"
    if css_src.resolve() != css_dest.resolve():
        shutil.copyfile(css_src, css_dest)

    sources_count: dict[str, int] = {}
    for l in listings:
        sources_count[l.source] = sources_count.get(l.source, 0) + 1

    ids = [stable_id(l) for l in listings]
    rows = [_listing_row(l, sid=sid) for l, sid in zip(listings, ids)]
    sources = sorted(sources_count.items())

    map_data = [
        {
            "id": sid,
            "lat": l.lat,
            "lng": l.lng,
            "address": l.address or "",
            "zip": l.zip or "",
            "rent": l.rent or 0,
            "beds": l.beds or 0,
            "baths": l.baths or 0,
            "sqft": l.sqft or 0,
            "source": l.source,
            "url": l.listing_url,
            "photo": l.local_photo or (l.photos[0] if l.photos else None),
        }
        for l, sid in zip(listings, ids)
        if l.lat is not None and l.lng is not None
    ]

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    chips = "\n".join(
        f'<button class="chip" data-source="{html.escape(s)}" aria-pressed="true">'
        f'{html.escape(s)} <span class="count">{c}</span></button>'
        for s, c in sources
    )

    body = _RENDER.format(
        title=html.escape(title),
        meta=html.escape(extra_meta or f"Generated {now} • {len(listings)} listings"),
        chips=chips,
        rows="\n".join(rows),
        empty='<tr class="empty-row"><td colspan="9"><div class="empty">No listings matched filters.</div></td></tr>' if not rows else "",
        script=_SCRIPT,
        map_count=len(map_data),
        map_data=json.dumps(map_data, separators=(",", ":")),
    )
    out_path.write_text(body, encoding="utf-8")


def write_diff(
    current: list[Listing],
    previous: list[dict],
    out_path: Path,
    *,
    css_src: Path | None = None,
) -> tuple[int, int, list[str], list[str]]:
    """Diff by listing_url. Returns (new_count, gone_count, new_urls, gone_urls)."""
    cur_by_url = {l.listing_url: l for l in current}
    prev_by_url = {p["listing_url"]: p for p in previous if p.get("listing_url")}

    new_urls = sorted(set(cur_by_url) - set(prev_by_url))
    gone_urls = sorted(set(prev_by_url) - set(cur_by_url))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if css_src is None:
        css_src = Path(__file__).parent / "styles.css"
    css_dest = out_path.parent / "styles.css"
    if css_src.resolve() != css_dest.resolve():
        shutil.copyfile(css_src, css_dest)

    new_rows = [_listing_row(cur_by_url[u], extra_class="row-new") for u in new_urls]
    gone_rows = [_dict_row(prev_by_url[u], extra_class="row-gone") for u in gone_urls]

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    summary = f"{len(new_urls)} new • {len(gone_urls)} gone • generated {now}"

    body = _DIFF_RENDER.format(
        summary=html.escape(summary),
        new_count=len(new_urls),
        gone_count=len(gone_urls),
        new_rows="\n".join(new_rows) or '<tr><td colspan="9"><div class="empty">No new listings.</div></td></tr>',
        gone_rows="\n".join(gone_rows) or '<tr><td colspan="9"><div class="empty">Nothing dropped off.</div></td></tr>',
    )
    out_path.write_text(body, encoding="utf-8")
    return len(new_urls), len(gone_urls), new_urls, gone_urls


def _listing_row(l: Listing, extra_class: str = "", sid: Optional[str] = None) -> str:
    photo = l.local_photo or (l.photos or [None])[0]
    if photo:
        thumb = f'<a href="{html.escape(l.listing_url)}" target="_blank" rel="noopener"><span class="thumb" style="background-image:url(\'{html.escape(photo)}\')"></span></a>'
    else:
        thumb = '<span class="thumb-empty"></span>'
    addr = l.address or "—"
    zip_part = f' <span class="zip">{html.escape(l.zip)}</span>' if l.zip else ""
    rent = f"${l.rent:,}" if l.rent else "—"
    listed = _format_listed_date(l.listed_date)
    sid = sid or stable_id(l)

    return _ROW.format(
        cls=extra_class,
        sid=html.escape(sid),
        source=html.escape(l.source),
        thumb=thumb,
        addr=html.escape(addr),
        url=html.escape(l.listing_url),
        zip_part=zip_part,
        photo_path=html.escape(photo or ""),
        beds=html.escape(_clean_num(l.beds) if l.beds is not None else "—"),
        baths=html.escape(_clean_num(l.baths) if l.baths is not None else "—"),
        sqft=html.escape(f"{int(l.sqft):,}" if l.sqft else "—"),
        rent=html.escape(rent),
        rent_val=l.rent or 0,
        beds_val=l.beds or 0,
        baths_val=l.baths or 0,
        sqft_val=l.sqft or 0,
        listed_val=html.escape(_iso_date_key(l.listed_date)),
        listed=html.escape(listed),
    )


def _dict_row(d: dict, extra_class: str = "") -> str:
    photos = []
    if d.get("photos"):
        photos = d["photos"] if isinstance(d["photos"], list) else []
    photo = d.get("local_photo") or (photos[0] if photos else None)
    sid = hashlib.sha1(
        (d.get("dedup_key") or d.get("listing_url") or "").encode("utf-8")
    ).hexdigest()[:12]
    if photo:
        thumb = f'<a href="{html.escape(d.get("listing_url",""))}" target="_blank" rel="noopener"><span class="thumb" style="background-image:url(\'{html.escape(photo)}\')"></span></a>'
    else:
        thumb = '<span class="thumb-empty"></span>'
    bb = _format_beds_baths(d.get("beds"), d.get("baths"), d.get("sqft"))
    rent = f"${int(d['rent']):,}" if d.get("rent") else "—"
    listed_raw = d.get("listed_date") or ""
    return _ROW.format(
        cls=extra_class,
        sid=html.escape(sid),
        source=html.escape(str(d.get("source", ""))),
        thumb=thumb,
        addr=html.escape(str(d.get("address") or "—")),
        url=html.escape(str(d.get("listing_url", ""))),
        zip_part=f' <span class="zip">{html.escape(str(d.get("zip","")))}</span>' if d.get("zip") else "",
        photo_path=html.escape(str(photo or "")),
        beds=html.escape(_clean_num(d.get("beds")) if d.get("beds") is not None else "—"),
        baths=html.escape(_clean_num(d.get("baths")) if d.get("baths") is not None else "—"),
        sqft=html.escape(f"{int(d.get('sqft')):,}" if d.get("sqft") else "—"),
        rent=html.escape(rent),
        rent_val=int(d.get("rent") or 0),
        beds_val=float(d.get("beds") or 0),
        baths_val=float(d.get("baths") or 0),
        sqft_val=int(d.get("sqft") or 0),
        listed_val=html.escape(_iso_date_key(listed_raw)),
        listed=html.escape(_format_listed_date(listed_raw)),
    )


def _clean_num(x) -> str:
    try:
        f = float(x)
        return f"{int(f)}" if f.is_integer() else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(x)


def _iso_date_key(s) -> str:
    """Return a sort-friendly date string. Empty stays empty so unsorted
    rows stay grouped at the top/bottom predictably."""
    if not s:
        return ""
    return str(s)


def _format_listed_date(s) -> str:
    """Display 'YYYY-MM-DD' instead of the full ISO timestamp; tolerates
    None / empty / non-ISO strings."""
    if not s:
        return ""
    s = str(s)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


_ROW = """\
<tr class="{cls}" data-id="{sid}" data-source="{source}" data-rent="{rent_val}" data-beds="{beds_val}" data-baths="{baths_val}" data-sqft="{sqft_val}" data-listed="{listed_val}" data-photo="{photo_path}" data-url="{url}">
  <td>{thumb}</td>
  <td><span class="source">{source}</span></td>
  <td class="address">
    <a class="listing-link" href="{url}" target="_blank" rel="noopener">{addr}</a>{zip_part}
    <button class="fav" data-id="{sid}" aria-pressed="false" title="Toggle favorite" aria-label="Toggle favorite">&#9734;</button>
    <span class="seen-badge" hidden>&#10003; seen</span>
  </td>
  <td class="num">{beds}</td>
  <td class="num">{baths}</td>
  <td class="num">{sqft}</td>
  <td class="rent">{rent}</td>
  <td class="listed">{listed}</td>
</tr>"""


_RENDER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="styles.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="">
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
  <div class="controls">
    <input type="search" id="q" placeholder="Filter address, source, type…" autocomplete="off">
    <input type="number" id="rent-min" placeholder="min $" style="width: 90px">
    <input type="number" id="rent-max" placeholder="max $" style="width: 90px">
    <span style="margin-left: 8px; color: var(--muted)">Sources:</span>
    {chips}
    <button class="chip" id="map-toggle" aria-pressed="true" title="Show/hide map">Map <span class="count">{map_count}</span></button>
    <button class="chip chip-state" id="hide-seen" aria-pressed="false" title="Hide listings you've already clicked">Hide seen</button>
    <button class="chip chip-state" id="only-favs" aria-pressed="false" title="Show only favorited">Only &#9733;</button>
    <span class="summary" id="summary"></span>
  </div>
</header>
<section id="map-section" aria-label="Listings map">
  <div id="map"></div>
</section>
<main>
<table id="t">
  <thead>
    <tr>
      <th data-key="thumb" style="width: 110px"></th>
      <th data-key="source" data-type="str">Source</th>
      <th data-key="address" data-type="str">Address</th>
      <th data-key="beds" data-type="num-beds" style="width: 56px">Beds</th>
      <th data-key="baths" data-type="num-baths" style="width: 60px">Baths</th>
      <th data-key="sqft" data-type="num-sqft" style="width: 80px">Sqft</th>
      <th data-key="rent" data-type="num-rent" style="width: 90px">Rent</th>
      <th data-key="listed" data-type="num-date" data-default-sort="desc" style="width: 110px">Listed</th>
    </tr>
  </thead>
  <tbody>
{rows}{empty}
  </tbody>
</table>
<section id="ghost-favorites" hidden>
  <h2>Favorites no longer listed <span id="ghost-count" class="count"></span></h2>
  <table class="ghost-table">
    <thead>
      <tr><th style="width: 110px"></th><th>Source</th><th>Address</th><th>Beds</th><th>Baths</th><th>Sqft</th><th>Rent</th><th>Last seen</th><th></th></tr>
    </thead>
    <tbody id="ghost-tbody"></tbody>
  </table>
</section>
</main>
<footer>
  vb-rental-finder · personal use, no redistribution &nbsp;·&nbsp;
  <a href="#" id="clear-state">Clear seen / favorites</a>
</footer>
<script>window.__listings = {map_data};</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
<script>{script}</script>
</body>
</html>
"""


_SCRIPT = """
(function() {
  const tbody = document.querySelector('#t tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const chips = Array.from(document.querySelectorAll('.chip[data-source]'));
  const q = document.getElementById('q');
  const rentMin = document.getElementById('rent-min');
  const rentMax = document.getElementById('rent-max');
  const summary = document.getElementById('summary');
  let activeSources = new Set(chips.map(c => c.dataset.source));

  // ---- Persistent state (seen + favorites) ----
  const SEEN_KEY = 'vbrf_seen';
  const FAVS_KEY = 'vbrf_favs';

  function loadJSON(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) || fallback; }
    catch (e) { return fallback; }
  }
  let seen = new Set(loadJSON(SEEN_KEY, []));
  let favs = loadJSON(FAVS_KEY, {});

  function saveSeen() { localStorage.setItem(SEEN_KEY, JSON.stringify([...seen])); }
  function saveFavs() { localStorage.setItem(FAVS_KEY, JSON.stringify(favs)); }

  function snapshotFromRow(row) {
    return {
      id: row.dataset.id,
      address: row.querySelector('.listing-link').innerText,
      zip: (row.querySelector('.zip') || {}).innerText || '',
      url: row.dataset.url,
      photo: row.dataset.photo || '',
      source: row.dataset.source,
      rent: +row.dataset.rent || 0,
      beds: +row.dataset.beds || 0,
      baths: +row.dataset.baths || 0,
      sqft: +row.dataset.sqft || 0,
      listed: row.dataset.listed || '',
      capturedAt: new Date().toISOString(),
    };
  }

  function snapshotFromMapData(d) {
    return {
      id: d.id, address: d.address || '', zip: d.zip || '', url: d.url || '',
      photo: d.photo || '', source: d.source || '',
      rent: d.rent || 0, beds: d.beds || 0, baths: d.baths || 0, sqft: d.sqft || 0,
      listed: '', capturedAt: new Date().toISOString(),
    };
  }

  // ---- Map state — declared early so state setters can reach it ----
  const mapData = window.__listings || [];
  const markersById = {};
  let map = null;

  // ---- Pin appearance ----
  function pinState(id) {
    if (favs[id]) return 'fav';
    if (seen.has(id)) return 'seen';
    return 'default';
  }

  function makeIcon(state) {
    const cls = state === 'fav' ? 'pin-fav'
              : state === 'seen' ? 'pin-seen'
              : 'pin-default';
    const inner = state === 'fav' ? '<span class="pin-star">&#9733;</span>' : '';
    const big = state === 'fav';
    const size = big ? 28 : 22;
    return L.divIcon({
      className: 'pin ' + cls,
      html: '<div class="pin-body">' + inner + '</div>',
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      popupAnchor: [0, -size / 2],
    });
  }

  function renderPopupHTML(id) {
    const d = mapData.find(l => l.id === id);
    if (!d) return '';
    const photo = d.photo
      ? '<img src="' + d.photo + '" style="width:100%;max-width:200px;border-radius:4px;display:block;margin-bottom:6px">'
      : '';
    const meta = [];
    if (d.beds) meta.push(d.beds + ' bd');
    if (d.baths) meta.push(d.baths + ' ba');
    if (d.sqft) meta.push(d.sqft.toLocaleString() + ' sqft');
    const isFav = !!favs[id];
    return (
      photo +
      '<strong>' + (d.address || '') + '</strong><br>' +
      (d.zip ? d.zip + ' &middot; ' : '') +
      '<span style="color:#047857;font-weight:600">$' + (d.rent || 0).toLocaleString() + '</span><br>' +
      '<small>' + meta.join(' · ') + ' &middot; ' + d.source + '</small>' +
      '<div class="popup-actions">' +
        '<a class="popup-link" data-id="' + id + '" href="' + d.url + '" target="_blank" rel="noopener">view listing &rarr;</a>' +
        '<button class="popup-fav" data-id="' + id + '" aria-pressed="' + isFav + '">' +
          (isFav ? '&#9733; favorited' : '&#9734; favorite') +
        '</button>' +
      '</div>'
    );
  }

  // ---- Centralized state setters ----
  function syncRowState(id) {
    const row = tbody.querySelector('tr[data-id="' + id + '"]');
    if (!row) return;
    const isSeen = seen.has(id);
    const isFav = !!favs[id];
    row.classList.toggle('row-seen', isSeen);
    row.classList.toggle('row-fav', isFav);
    const badge = row.querySelector('.seen-badge');
    if (badge) badge.hidden = !isSeen;
    const btn = row.querySelector('.fav');
    if (btn) {
      btn.setAttribute('aria-pressed', String(isFav));
      btn.innerHTML = isFav ? '&#9733;' : '&#9734;';
    }
  }

  function syncPinState(id) {
    const m = markersById[id];
    if (!m) return;
    m.setIcon(makeIcon(pinState(id)));
    if (m.isPopupOpen && m.isPopupOpen()) {
      const popup = m.getPopup();
      if (popup) popup.setContent(renderPopupHTML(id));
    }
  }

  function setSeen(id) {
    if (!id || seen.has(id)) return;
    seen.add(id);
    saveSeen();
    syncRowState(id);
    syncPinState(id);
    applyFilters();
  }

  function toggleFav(id) {
    if (!id) return;
    if (favs[id]) {
      delete favs[id];
    } else {
      const row = tbody.querySelector('tr[data-id="' + id + '"]');
      if (row) {
        favs[id] = snapshotFromRow(row);
      } else {
        const d = mapData.find(l => l.id === id);
        if (d) favs[id] = snapshotFromMapData(d);
      }
    }
    saveFavs();
    syncRowState(id);
    syncPinState(id);
    applyFilters();
    renderGhosts();
  }

  function applyFilters() {
    const term = (q.value || '').toLowerCase().trim();
    const lo = parseInt(rentMin.value || '0', 10) || 0;
    const hi = parseInt(rentMax.value || '0', 10) || Infinity;
    const hideSeen = document.getElementById('hide-seen').getAttribute('aria-pressed') === 'true';
    const onlyFavs = document.getElementById('only-favs').getAttribute('aria-pressed') === 'true';
    let visible = 0;
    for (const r of rows) {
      const id = r.dataset.id;
      const src = r.dataset.source;
      const rent = parseInt(r.dataset.rent || '0', 10);
      const text = r.innerText.toLowerCase();
      let ok = activeSources.has(src);
      if (ok && term && !text.includes(term)) ok = false;
      if (ok && (rent < lo || rent > hi)) ok = false;
      // "Hide seen" matches what's visually gray — favorited (gold) listings
      // stay visible even if they're also flagged as seen.
      if (ok && hideSeen && seen.has(id) && !favs[id]) ok = false;
      if (ok && onlyFavs && !favs[id]) ok = false;
      r.classList.toggle('hidden', !ok);
      const m = markersById[id];
      if (m) {
        const el = m.getElement();
        if (el) el.style.display = ok ? '' : 'none';
      }
      if (ok) visible++;
    }
    summary.textContent = visible + ' of ' + rows.length + ' shown';
  }

  // Apply initial state to rows (badges, fav button label)
  rows.forEach(r => syncRowState(r.dataset.id));

  // ---- Source chips ----
  chips.forEach(c => c.addEventListener('click', () => {
    const pressed = c.getAttribute('aria-pressed') === 'true';
    c.setAttribute('aria-pressed', String(!pressed));
    if (pressed) activeSources.delete(c.dataset.source);
    else activeSources.add(c.dataset.source);
    applyFilters();
  }));
  q.addEventListener('input', applyFilters);
  rentMin.addEventListener('input', applyFilters);
  rentMax.addEventListener('input', applyFilters);

  document.querySelectorAll('.chip-state').forEach(c => {
    c.addEventListener('click', () => {
      const pressed = c.getAttribute('aria-pressed') === 'true';
      c.setAttribute('aria-pressed', String(!pressed));
      applyFilters();
    });
  });

  // Row link click → mark seen
  rows.forEach(r => {
    const link = r.querySelector('.listing-link');
    if (link) link.addEventListener('click', () => setSeen(r.dataset.id));
    const btn = r.querySelector('.fav');
    if (btn) btn.addEventListener('click', e => {
      e.stopPropagation();
      toggleFav(r.dataset.id);
    });
  });

  // Clear-state link in footer
  const clear = document.getElementById('clear-state');
  if (clear) clear.addEventListener('click', e => {
    e.preventDefault();
    if (!confirm('Clear all seen + favorites?')) return;
    seen = new Set();
    favs = {};
    saveSeen();
    saveFavs();
    location.reload();
  });

  // Ghost favorites: render any favorited listings that are NOT in the current set.
  function renderGhosts() {
    const currentIds = new Set(rows.map(r => r.dataset.id));
    const ghosts = Object.values(favs).filter(f => !currentIds.has(f.id));
    const section = document.getElementById('ghost-favorites');
    const tbody = document.getElementById('ghost-tbody');
    const count = document.getElementById('ghost-count');
    if (!section || !tbody) return;
    if (!ghosts.length) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    count.textContent = '(' + ghosts.length + ')';
    tbody.innerHTML = '';
    ghosts.forEach(g => {
      const tr = document.createElement('tr');
      tr.className = 'row-ghost row-fav';
      const thumbHtml = g.photo
        ? '<a href="' + g.url + '" target="_blank" rel="noopener"><span class="thumb" style="background-image:url(\\'' + g.photo + '\\')"></span></a>'
        : '<span class="thumb-empty"></span>';
      const captured = (g.capturedAt || '').slice(0, 10);
      tr.innerHTML =
        '<td>' + thumbHtml + '</td>' +
        '<td><span class="source">' + g.source + '</span></td>' +
        '<td class="address"><a class="listing-link" href="' + g.url + '" target="_blank" rel="noopener">' + g.address + '</a> ' +
          (g.zip ? '<span class="zip">' + g.zip + '</span>' : '') + '</td>' +
        '<td class="num">' + (g.beds || '—') + '</td>' +
        '<td class="num">' + (g.baths || '—') + '</td>' +
        '<td class="num">' + (g.sqft ? g.sqft.toLocaleString() : '—') + '</td>' +
        '<td class="rent">' + (g.rent ? '$' + g.rent.toLocaleString() : '—') + '</td>' +
        '<td class="listed">' + captured + '</td>' +
        '<td><button class="fav" data-ghost-id="' + g.id + '" aria-pressed="true" title="Remove from favorites">&#9733;</button></td>';
      tbody.appendChild(tr);
    });
    // Wire ghost remove buttons
    tbody.querySelectorAll('button.fav').forEach(b => {
      b.addEventListener('click', () => {
        const id = b.dataset.ghostId;
        delete favs[id];
        saveFavs();
        renderGhosts();
      });
    });
  }
  renderGhosts();

  // Sortable columns
  const headers = Array.from(document.querySelectorAll('thead th[data-key]'));
  const NUM_TYPES = {
    'num-rent': 'rent',
    'num-beds': 'beds',
    'num-baths': 'baths',
    'num-sqft': 'sqft',
  };
  let sortKey = null, sortDir = 'asc';

  function applySort(key, dir) {
    const h = headers.find(x => x.dataset.key === key);
    if (!h) return;
    sortKey = key;
    sortDir = dir;
    headers.forEach(x => x.removeAttribute('data-sort-dir'));
    h.setAttribute('data-sort-dir', dir);
    const type = h.dataset.type || 'str';
    const numField = NUM_TYPES[type];
    rows.sort((a, b) => {
      let av, bv;
      if (numField) {
        av = +a.dataset[numField];
        bv = +b.dataset[numField];
      } else if (type === 'num-date') {
        av = a.dataset.listed || '';
        bv = b.dataset.listed || '';
        // Empty dates sink to the bottom regardless of direction
        if (!av && bv) return 1;
        if (av && !bv) return -1;
      } else {
        av = a.cells[headers.indexOf(h)].innerText.toLowerCase();
        bv = b.cells[headers.indexOf(h)].innerText.toLowerCase();
      }
      if (av < bv) return dir === 'asc' ? -1 : 1;
      if (av > bv) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    rows.forEach(r => tbody.appendChild(r));
  }

  headers.forEach(h => h.addEventListener('click', () => {
    const key = h.dataset.key;
    if (!key || key === 'thumb') return;
    const dir = (sortKey === key && sortDir === 'asc') ? 'desc' : 'asc';
    applySort(key, dir);
  }));

  // Default sort: whichever header has data-default-sort.
  const defaultHeader = headers.find(h => h.dataset.defaultSort);
  if (defaultHeader) {
    applySort(defaultHeader.dataset.key, defaultHeader.dataset.defaultSort);
  }

  applyFilters();

  // ---- Map (Leaflet + OpenStreetMap) ----
  const mapSection = document.getElementById('map-section');
  const mapToggle = document.getElementById('map-toggle');
  const mapEl = document.getElementById('map');

  function initMap() {
    if (map || !mapData.length || typeof L === 'undefined') return;
    map = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    const bounds = [];
    mapData.forEach(d => {
      if (d.lat == null || d.lng == null) return;
      const m = L.marker([d.lat, d.lng], {
        icon: makeIcon(pinState(d.id)),
        riseOnHover: true,
      }).addTo(map);
      // Popup content is rebuilt each time it opens so it reflects latest state.
      m.bindPopup(() => renderPopupHTML(d.id));
      m.on('click', () => focusRow(d.id));
      markersById[d.id] = m;
      bounds.push([d.lat, d.lng]);
    });

    // Delegate clicks on popup buttons. Using event delegation on the map
    // container handles popups that get refreshed via setContent without
    // needing to re-wire individual elements.
    mapEl.addEventListener('click', e => {
      const link = e.target.closest('.popup-link');
      if (link && link.dataset.id) {
        setSeen(link.dataset.id);
        return;
      }
      const fav = e.target.closest('.popup-fav');
      if (fav && fav.dataset.id) {
        toggleFav(fav.dataset.id);
      }
    });

    if (bounds.length) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
    } else {
      map.setView([36.85, -76.05], 11);
    }
    setTimeout(() => {
      map.invalidateSize();
      // Now that markers exist, sync visibility with current filter state.
      applyFilters();
    }, 50);
  }

  function focusRow(id) {
    const row = tbody.querySelector('tr[data-id="' + id + '"]');
    if (!row) return;
    rows.forEach(r => r.classList.remove('row-active'));
    row.classList.add('row-active');
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function focusPin(id) {
    const m = markersById[id];
    if (!m || !map) return;
    map.setView(m.getLatLng(), Math.max(map.getZoom(), 14), { animate: true });
    m.openPopup();
  }

  rows.forEach(r => {
    r.addEventListener('click', e => {
      // ignore clicks on the listing link itself
      if (e.target.closest('a')) return;
      const id = r.dataset.id;
      rows.forEach(x => x.classList.remove('row-active'));
      r.classList.add('row-active');
      focusPin(id);
    });
  });

  mapToggle.addEventListener('click', () => {
    const pressed = mapToggle.getAttribute('aria-pressed') === 'true';
    mapToggle.setAttribute('aria-pressed', String(!pressed));
    mapSection.classList.toggle('collapsed', pressed);
    if (!pressed && map) setTimeout(() => map.invalidateSize(), 50);
  });

  // Defer map init until Leaflet is loaded.
  if (typeof L !== 'undefined') initMap();
  else window.addEventListener('load', initMap);
})();
"""


_DIFF_RENDER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Listing Diff — Virginia Beach Rentals</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header>
  <h1>Listing Diff</h1>
  <div class="meta">{summary}</div>
</header>
<main>
  <section class="diff-section">
    <h2>New ({new_count})</h2>
    <table>
      <thead>
        <tr><th style="width: 110px"></th><th>Source</th><th>Address</th><th>Beds</th><th>Baths</th><th>Sqft</th><th>Rent</th><th>Listed</th></tr>
      </thead>
      <tbody>
{new_rows}
      </tbody>
    </table>
  </section>
  <section class="diff-section">
    <h2>Gone ({gone_count})</h2>
    <table>
      <thead>
        <tr><th style="width: 110px"></th><th>Source</th><th>Address</th><th>Beds</th><th>Baths</th><th>Sqft</th><th>Rent</th><th>Listed</th></tr>
      </thead>
      <tbody>
{gone_rows}
      </tbody>
    </table>
  </section>
</main>
<footer>vb-rental-finder · personal use, no redistribution</footer>
</body>
</html>
"""
