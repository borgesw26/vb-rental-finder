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

Each run writes the same report into two places so it works both locally
and via GitHub Pages:

- `report.html` (repo root) -- sortable, filterable table for local viewing.
  References photos at `docs/photos/<sha1>.jpg`.
- `diff.html` (repo root) -- adds/removes vs the previous run.
- `docs/index.html` -- identical report, but with photo paths re-rooted
  to `photos/<sha1>.jpg` so GitHub Pages can serve it standalone.
- `docs/diff.html`, `docs/styles.css`, `docs/photos/` -- the rest of the
  Pages assets.
- `out/listings_YYYY-MM-DD.csv` -- flat CSV per run (committed for history).
- `out/diff_YYYY-MM-DD.html` -- dated audit copy (references
  `../docs/photos/`).
- `out/run_YYYY-MM-DD.json` -- machine-readable summary (per-source counts,
  diff counts, new/gone URLs). Used by `daily.ps1` and the GitHub workflow
  to build commit messages.
- `listings.db` -- SQLite (gitignored). `runs` table tracks history;
  `listings` keeps every record per run.

The pipeline prunes `docs/photos/` each run so only currently-listed
photos stay on disk -- no unbounded accumulation across runs.

## GitHub Pages

`docs/` is set up to be served by GitHub Pages.

To enable (one-time, in the GitHub UI):

1. Open https://github.com/borgesw26/vb-rental-finder/settings/pages
2. Under **Build and deployment** -> **Source**, select
   **Deploy from a branch**.
3. Branch: **main**, Folder: **/docs**. Save.
4. After ~1 minute the site will be live at:
   `https://borgesw26.github.io/vb-rental-finder/`

The diff page will be at `…/diff.html`.

### Daily refresh via GitHub Actions

`.github/workflows/scrape.yml` runs every day at **11:00 UTC** (= 7am EDT
in summer / 6am EST in winter -- GitHub Actions cron can't honor a
timezone, so we accept the seasonal hour drift). It:

1. Sets up Python 3.11, installs deps, installs Playwright Chromium.
2. Runs `python main.py`.
3. Commits any new files in `docs/` and `out/` with a summary in the
   commit message (`Daily scrape YYYY-MM-DD -- N listings; X new, Y gone`).
4. Pushes back to `main`. The next Pages build picks the change up
   automatically.

Trigger a run on demand from
https://github.com/borgesw26/vb-rental-finder/actions/workflows/scrape.yml
(`Run workflow` button).

> Most listing sites refuse data-center IPs, so a cloud run will mostly
> rely on Redfin (which has a working JSON endpoint) and Craigslist.
> Realtor / Zillow / Homes.com are documented as Very high fragility and
> typically return zero from cloud IPs. The local Task Scheduler run
> from `daily.ps1` produces dramatically more results.

## Daily schedule (Windows Task Scheduler — local alternative)

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

## Sync setup (sharing seen + favorites with another person)

The report normally stores your "seen" and "favorited" markers in
`localStorage` per device. To share state across devices (e.g. you and
your partner), the report can also push state to `state.json` at the
root of this repo.

The setup is documented end-to-end in **[docs/sync-setup.md](docs/sync-setup.md)**.
Short version:

1. In the report header, click the **⚙** chip.
2. Set a display name and paste a fine-grained GitHub PAT scoped to
   **only this repo** with **Contents: Read and write** for ~1 year.
3. Click **Test**, then **Save**.

Without a token the report runs in local-only mode — same UX as before.
With a token, every state change is debounced 2 s and POSTed to GitHub's
Contents API; conflicts (two devices saving simultaneously) are detected
via the file SHA and resolved with a refetch + per-field LWW merge.

State is stored as a single JSON file with the schema documented at the
top of [docs/sync-setup.md](docs/sync-setup.md). Tokens never leave the
browser except as `Authorization` headers to `api.github.com`.

## NEW listings

A listing is flagged **NEW** if its `listing_url` is in the most recent
completed run but not in the immediately preceding one. The flag is computed
in `main.py` before the listings are inserted (see `_mark_new_vs_prior_run`)
and persisted on the `listings.is_new` column, so reloading or regenerating
the report keeps the badges stable.

In the report:

- A small yellow **NEW** pill renders next to the address in the table.
- The map pin turns green (`.pin-new`). Priority order is
  **favorited > seen > new > default**, so a favorited-and-new listing
  shows as gold and a seen-and-new listing shows as gray.
- The **Only NEW** chip in the controls bar filters table rows + map pins
  to just the new ones.

First run ever has no prior run to compare against, so nothing is flagged on
day one — that's deliberate, otherwise every initial listing would scream
"NEW".

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
