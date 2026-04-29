"""HTML report generation. Vanilla HTML + one CSS file. No build step."""
from __future__ import annotations

import csv
import html
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from core.schema import Listing

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "source", "address", "city", "state", "zip",
    "beds", "baths", "sqft", "lot_size", "year_built",
    "rent", "deposit", "pets_allowed",
    "property_type", "mls_number",
    "listing_url", "description", "listed_date", "scraped_at",
    "photos",
]


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

    rows = [_listing_row(l) for l in listings]
    sources = sorted(sources_count.items())

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
        empty='<tr class="empty-row"><td colspan="7"><div class="empty">No listings matched filters.</div></td></tr>' if not rows else "",
        script=_SCRIPT,
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
        new_rows="\n".join(new_rows) or '<tr><td colspan="7"><div class="empty">No new listings.</div></td></tr>',
        gone_rows="\n".join(gone_rows) or '<tr><td colspan="7"><div class="empty">Nothing dropped off.</div></td></tr>',
    )
    out_path.write_text(body, encoding="utf-8")
    return len(new_urls), len(gone_urls), new_urls, gone_urls


def _listing_row(l: Listing, extra_class: str = "") -> str:
    photo = (l.photos or [None])[0]
    if photo:
        thumb = f'<a href="{html.escape(l.listing_url)}" target="_blank" rel="noopener"><span class="thumb" style="background-image:url(\'{html.escape(photo)}\')"></span></a>'
    else:
        thumb = '<span class="thumb-empty"></span>'
    addr = l.address or "—"
    zip_part = f' <span class="zip">{html.escape(l.zip)}</span>' if l.zip else ""
    bb = _format_beds_baths(l.beds, l.baths, l.sqft)
    rent = f"${l.rent:,}" if l.rent else "—"
    listed = l.listed_date or ""

    return _ROW.format(
        cls=extra_class,
        source=html.escape(l.source),
        thumb=thumb,
        addr=html.escape(addr),
        url=html.escape(l.listing_url),
        zip_part=zip_part,
        bb=html.escape(bb),
        rent=html.escape(rent),
        rent_val=l.rent or 0,
        beds_val=l.beds or 0,
        baths_val=l.baths or 0,
        sqft_val=l.sqft or 0,
        listed=html.escape(str(listed)),
    )


def _dict_row(d: dict, extra_class: str = "") -> str:
    photos = []
    if d.get("photos"):
        photos = d["photos"] if isinstance(d["photos"], list) else []
    photo = photos[0] if photos else None
    if photo:
        thumb = f'<a href="{html.escape(d.get("listing_url",""))}" target="_blank" rel="noopener"><span class="thumb" style="background-image:url(\'{html.escape(photo)}\')"></span></a>'
    else:
        thumb = '<span class="thumb-empty"></span>'
    bb = _format_beds_baths(d.get("beds"), d.get("baths"), d.get("sqft"))
    rent = f"${int(d['rent']):,}" if d.get("rent") else "—"
    return _ROW.format(
        cls=extra_class,
        source=html.escape(str(d.get("source", ""))),
        thumb=thumb,
        addr=html.escape(str(d.get("address") or "—")),
        url=html.escape(str(d.get("listing_url", ""))),
        zip_part=f' <span class="zip">{html.escape(str(d.get("zip","")))}</span>' if d.get("zip") else "",
        bb=html.escape(bb),
        rent=html.escape(rent),
        rent_val=int(d.get("rent") or 0),
        beds_val=float(d.get("beds") or 0),
        baths_val=float(d.get("baths") or 0),
        sqft_val=int(d.get("sqft") or 0),
        listed=html.escape(str(d.get("listed_date") or "")),
    )


def _format_beds_baths(beds, baths, sqft) -> str:
    parts = []
    if beds is not None:
        parts.append(f"{_clean_num(beds)} bd")
    if baths is not None:
        parts.append(f"{_clean_num(baths)} ba")
    if sqft:
        parts.append(f"{int(sqft):,} sqft")
    return " · ".join(parts) if parts else "—"


def _clean_num(x) -> str:
    try:
        f = float(x)
        return f"{int(f)}" if f.is_integer() else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(x)


_ROW = """\
<tr class="{cls}" data-source="{source}" data-rent="{rent_val}" data-beds="{beds_val}" data-baths="{baths_val}" data-sqft="{sqft_val}">
  <td>{thumb}</td>
  <td><span class="source">{source}</span></td>
  <td class="address"><a href="{url}" target="_blank" rel="noopener">{addr}</a>{zip_part}</td>
  <td class="bb">{bb}</td>
  <td class="rent">{rent}</td>
  <td>{listed}</td>
</tr>"""


_RENDER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="styles.css">
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
    <span class="summary" id="summary"></span>
  </div>
</header>
<main>
<table id="t">
  <thead>
    <tr>
      <th data-key="thumb" style="width: 110px"></th>
      <th data-key="source" data-type="str">Source</th>
      <th data-key="address" data-type="str">Address</th>
      <th data-key="bb" data-type="num-beds">Beds · Baths · Sqft</th>
      <th data-key="rent" data-type="num-rent">Rent</th>
      <th data-key="listed" data-type="str">Listed</th>
    </tr>
  </thead>
  <tbody>
{rows}{empty}
  </tbody>
</table>
</main>
<footer>vb-rental-finder · personal use, no redistribution</footer>
<script>{script}</script>
</body>
</html>
"""


_SCRIPT = """
(function() {
  const tbody = document.querySelector('#t tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const chips = Array.from(document.querySelectorAll('.chip'));
  const q = document.getElementById('q');
  const rentMin = document.getElementById('rent-min');
  const rentMax = document.getElementById('rent-max');
  const summary = document.getElementById('summary');
  let activeSources = new Set(chips.map(c => c.dataset.source));

  function applyFilters() {
    const term = (q.value || '').toLowerCase().trim();
    const lo = parseInt(rentMin.value || '0', 10) || 0;
    const hi = parseInt(rentMax.value || '0', 10) || Infinity;
    let visible = 0;
    for (const r of rows) {
      const src = r.dataset.source;
      const rent = parseInt(r.dataset.rent || '0', 10);
      const text = r.innerText.toLowerCase();
      let ok = activeSources.has(src);
      if (ok && term && !text.includes(term)) ok = false;
      if (ok && (rent < lo || rent > hi)) ok = false;
      r.classList.toggle('hidden', !ok);
      if (ok) visible++;
    }
    summary.textContent = visible + ' of ' + rows.length + ' shown';
  }

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

  // Sortable columns
  const headers = document.querySelectorAll('thead th[data-key]');
  let sortKey = null, sortDir = 'asc';
  headers.forEach(h => h.addEventListener('click', () => {
    const key = h.dataset.key;
    if (!key || key === 'thumb') return;
    if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else { sortKey = key; sortDir = 'asc'; }
    headers.forEach(x => x.removeAttribute('data-sort-dir'));
    h.setAttribute('data-sort-dir', sortDir);
    const type = h.dataset.type || 'str';
    rows.sort((a, b) => {
      let av, bv;
      if (type === 'num-rent') { av = +a.dataset.rent; bv = +b.dataset.rent; }
      else if (type === 'num-beds') { av = +a.dataset.beds; bv = +b.dataset.beds; }
      else {
        av = a.cells[Array.from(headers).indexOf(h)].innerText.toLowerCase();
        bv = b.cells[Array.from(headers).indexOf(h)].innerText.toLowerCase();
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    rows.forEach(r => tbody.appendChild(r));
  }));
  applyFilters();
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
        <tr><th style="width: 110px"></th><th>Source</th><th>Address</th><th>Beds · Baths · Sqft</th><th>Rent</th><th>Listed</th></tr>
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
        <tr><th style="width: 110px"></th><th>Source</th><th>Address</th><th>Beds · Baths · Sqft</th><th>Rent</th><th>Listed</th></tr>
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
