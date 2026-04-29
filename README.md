# vb-rental-finder

A personal-use Python aggregator that pulls active rental listings for
**single-family houses** in **Virginia Beach, VA** between **$2,300-$3,300/mo**
from Realtor.com, Zillow, Redfin, Homes.com, and Hampton Roads Craigslist,
deduplicates them, and emits a sortable HTML report plus a daily CSV.

> Personal use, no redistribution. Be polite -- 1 request / 2 seconds per
> domain, realistic User-Agent, no bypassing logins or paid walls.

## Setup (Windows / PowerShell)

Requires Python 3.11+ on `PATH`.

```powershell
.\run.ps1
```

That script:

1. Creates `.venv` if missing.
2. `pip install -r requirements.txt`.
3. `playwright install chromium` (one-time ~170 MB download).
4. Runs `main.py`.
5. Opens `report.html` in your default browser.

Subsequent runs:

```powershell
.\run.ps1 -SkipInstall              # skip pip / playwright install
.\run.ps1 -Only realtor,craigslist  # subset of scrapers
.\run.ps1 -LogLevel DEBUG -NoOpen   # verbose, don't auto-open report
```

## Manual setup (no PowerShell)

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
.venv/Scripts/python.exe main.py
```

## Outputs

- `report.html` -- sortable, filterable table with photo previews and source
  chips. Open in any browser. Pairs with `styles.css`.
- `diff.html` -- adds/removes vs the previous run, also under `report.html`'s
  styles.
- `out/listings_YYYY-MM-DD.csv` -- flat CSV per run.
- `out/diff_YYYY-MM-DD.html` -- dated copy of the diff (rendered with its
  own `styles.css` next to it).
- `out/run_YYYY-MM-DD.json` -- machine-readable summary (per-source counts,
  diff counts, new/gone URLs). Used by `daily.ps1` to build commit messages.
- `listings.db` -- SQLite. `runs` table tracks history; `listings` keeps
  every record per run (source, normalized fields, dedup key, photos JSON).

## Daily schedule (Windows Task Scheduler)

`daily.ps1` runs `main.py`, commits any changes in `out/` (CSV + diff +
run JSON) with a summary in the message, pushes to `origin/main`, and shows
a Windows toast notification with the new/gone counts.

One-time registration with Task Scheduler:

```powershell
.\register-schedule.ps1                       # daily at 08:00 local
.\register-schedule.ps1 -At "06:30"           # custom time
.\register-schedule.ps1 -Unregister           # remove the task
```

The task runs **only when you're logged in** (Interactive logon) so the
toast lands in your session and `git push` uses your stored credentials.
If your machine is asleep at the trigger time, the task fires whenever you
next wake (`-StartWhenAvailable`).

Manual / dry-run invocation:

```powershell
.\daily.ps1                       # full flow: run, commit, push, toast
.\daily.ps1 -NoPush -NoToast      # local commit only
.\daily.ps1 -NoPull               # skip the leading git pull --rebase
```

Logs go to `out/daily.log` (gitignored). If the run fails or push fails,
the toast title says so and the log has the trace.

> Note: cloud `/schedule` is not used. Most listing sites refuse cloud /
> data-center IPs, so a residential machine produces dramatically more
> results than any cloud sandbox would.

## How it filters

A listing is kept if **all** of these hold:

- Address resolves to Virginia Beach (city match, address substring, or one of
  the configured zip codes).
- `rent` is between `$2,300` and `$3,300` (inclusive, configurable).
- Property type is plausibly a single-family house. We allow `single family`,
  `house`, `detached` etc., and reject `townhouse`, `condo`, `apartment`,
  `duplex`, `mobile`, `manufactured`, `multi-family`, `co-op`, and any
  description with sub-unit markers.

If the source omits a property type, we keep the listing tentatively unless
the address or description contains a denied token.

## Deduplication

Listings are grouped by `(normalized address, beds, baths)`. Address
normalization uses [`usaddress`](https://github.com/datamade/usaddress)
to canonicalize street suffixes and directions. On conflict:

1. The MLS-numbered record wins.
2. Otherwise the source-priority list in `core/dedup.py` decides
   (`realtor > redfin > zillow > homesdotcom > craigslist`).
3. The winner inherits any photos and missing fields from the loser.

Listings without a derivable dedup key are passed through (we'd rather
double-count than drop).

## Source notes & fragility

| Source         | Transport                          | Fragility | Notes |
|----------------|------------------------------------|-----------|-------|
| Redfin         | httpx + JSON API                   | Low       | Calls `/stingray/api/v1/search/rentals` once per VB zip code. Region IDs (`region_type=2`) are pre-resolved in `scrapers/redfin.py`; unknown zips fall back to scraping the listings page for the `region_id` once. Reliable, returns rich `rentalExtension` payloads with rent, beds, baths, sqft, photos. |
| Craigslist     | httpx + JSON-LD / RSS              | Low       | Hits Hampton Roads CL with `housing_type=6` (house). Quality is mixed (user-posted). The 8-mile radius around 23454 catches a sliver of Norfolk; we tag everything as Virginia Beach and let the rent + denied-token filter sort. |
| Realtor.com    | httpx -> Playwright fallback       | **High**  | Pulls `__NEXT_DATA__` from the SSR page. Realtor returns 429 to non-residential IPs more often than not; the Playwright fallback may also be challenged. Expect 0 results from data-center / VPN IPs. |
| Zillow         | Playwright stealth                 | **Very high** | Aggressively rejects same-IP / headless traffic. Expect 0 results sometimes -- that's the site, not the code. Try `playwright.headless: false` in `config.yaml` and solve the challenge by hand. |
| Homes.com      | Playwright stealth                 | **Very high** | Cloudflare turnstile gates the listings page. Expect frequent zero-result runs. Same workaround as Zillow. |

> The fragile scrapers fail **gracefully** -- a 0-result run from one source
> never blocks the others. Check the per-source row in the run summary table.

Verified on a real run on 2026-04-28: Redfin returned 64 single-family
rentals across 13 VB zip codes in the $2.3-3.3k band, Craigslist returned
3. Realtor / Zillow / Homes.com returned 0 in the same run from a
residential Windows machine -- consistent with the fragility ratings above.

## Adding a new scraper

1. Create `scrapers/<name>.py` exposing:
   ```python
   NAME = "mysource"
   def scrape(cfg, http, get_pw, log) -> list[Listing]: ...
   ```
   - `cfg` is the parsed `config.yaml`.
   - `http` is the rate-limited httpx client (1 req / 2 s per domain).
   - `get_pw()` lazily returns a `PlaywrightFetcher` (or `None` if Playwright
     isn't installed). Don't call it unless you need a real browser.
   - Each `Listing` should populate `address`, `rent`, `beds`, `baths` and a
     `listing_url`. Set `dedup_key` via `make_dedup_key(address, beds, baths)`
     or let `main.py` set it.
2. Register the module in `SCRAPERS` in `main.py`.
3. Add a `sources.<name>.enabled: true` entry in `config.yaml`.

## Configuration

`config.yaml` knobs:

- `rent.min` / `rent.max` -- band in dollars.
- `zips` -- additional VB postal codes; used for membership tests when the
  source doesn't expose `city`.
- `http.rate_limit_seconds` -- per-domain spacing.
- `http.user_agent` -- change if you fork this.
- `playwright.headless` -- set `false` to watch the browser drive itself
  (handy for debugging Zillow / Homes.com captchas).
- `sources.<name>.enabled` -- toggle sources without code changes.

## Legal / ToS

This project is for **personal use** to surface listings the user can already
see in a browser. It does not redistribute scraped content, does not
hammer endpoints, identifies itself with a contactable User-Agent, and
respects each site's robots posture for the public listing index pages we
fetch. If you fork this and use it commercially, you're on your own.

Apartments.com, REIN MLS direct, Trulia, Rent.com, HotPads, and Facebook
Marketplace are intentionally **not** scraped -- either ToS-restrictive,
duplicative of an aggregator already in the list, or behind login walls.

## Phase 2 (not yet built)

- Apartments.com (Phase 2 -- ToS check first)
- Local property managers: Rose & Womble, Howard Hanna, BHHS Towne

These are stubbed in concept only; add them as new modules in `scrapers/`
following the contract above.

## Project layout

```
vb-rental-finder/
|-- config.yaml
|-- main.py
|-- run.ps1
|-- requirements.txt
|-- core/
|   |-- config.py        # YAML loader
|   |-- schema.py        # Listing dataclass
|   |-- http_client.py   # Rate-limited httpx with retries
|   |-- normalize.py     # usaddress-backed dedup keys
|   |-- filters.py       # SFH + city + rent band rules
|   |-- dedup.py         # MLS-preferred merger
|   `-- db.py            # SQLite (runs + listings)
|-- scrapers/
|   |-- base.py          # __NEXT_DATA__, JSON-LD helpers
|   |-- json_walk.py     # Listing-shape detection in arbitrary JSON
|   |-- playwright_fetcher.py
|   |-- realtor.py
|   |-- zillow.py
|   |-- redfin.py
|   |-- homesdotcom.py
|   `-- craigslist.py
`-- reports/
    |-- html_report.py   # report.html, diff.html, CSV
    `-- styles.css
```

## Troubleshooting

- **0 results from Zillow / Homes.com** -- that's the norm on a fresh IP.
  Run again later, or try `playwright.headless: false` in `config.yaml` and
  solve the challenge manually.
- **`playwright.sync_api.Error: Browser closed`** -- the headless launch
  broke. Re-run `python -m playwright install chromium`.
- **`usaddress` parse warnings** -- harmless; we fall back to a regex
  normalizer.
- **Empty `diff.html`** -- only generated after the second successful run.
