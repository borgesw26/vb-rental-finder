"""Run all enabled scrapers, dedupe, persist, and emit CSV + HTML reports."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from core.config import load_config
from core.db import Database
from core.dedup import deduplicate
from core.filters import passes_all
from core.http_client import RateLimitedClient
from core.normalize import make_dedup_key
from core.schema import Listing
from reports.html_report import write_csv, write_diff, write_report
from scrapers import craigslist, homesdotcom, realtor, redfin, zillow
from scrapers.playwright_fetcher import PlaywrightFetcher

console = Console()


SCRAPERS = {
    "realtor": realtor,
    "zillow": zillow,
    "redfin": redfin,
    "homesdotcom": homesdotcom,
    "craigslist": craigslist,
}


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def _make_pw_factory(cfg: dict):
    state = {"fetcher": None, "tried": False, "failed": False}
    pw_cfg = cfg.get("playwright", {})
    http_cfg = cfg.get("http", {})

    def get_pw():
        if state["failed"]:
            return None
        if state["fetcher"] is not None:
            return state["fetcher"]
        if state["tried"]:
            return None
        state["tried"] = True
        try:
            state["fetcher"] = PlaywrightFetcher(
                headless=pw_cfg.get("headless", True),
                slow_mo_ms=pw_cfg.get("slow_mo_ms", 0),
                default_timeout_ms=pw_cfg.get("default_timeout_ms", 45000),
                rate_limit_seconds=http_cfg.get("rate_limit_seconds", 2.0),
                user_agent=http_cfg.get("user_agent"),
            )
            return state["fetcher"]
        except Exception as e:
            logging.warning("Playwright init failed: %s", e)
            state["failed"] = True
            return None

    def shutdown():
        if state["fetcher"]:
            try:
                state["fetcher"].close()
            except Exception:
                pass

    return get_pw, shutdown


def run(cfg_path: str = "config.yaml", only: list[str] | None = None) -> int:
    cfg = load_config(cfg_path)
    paths = cfg.get("paths", {})
    out_dir = Path(paths.get("out_dir", "out"))
    out_dir.mkdir(parents=True, exist_ok=True)

    db = Database(paths.get("db", "listings.db"))
    run_id = db.start_run(notes=f"argv={sys.argv}")

    sources_cfg = cfg.get("sources", {})
    enabled = [
        name for name, mod in SCRAPERS.items()
        if sources_cfg.get(name, {}).get("enabled", True)
        and (only is None or name in only)
    ]
    console.print(f"[bold]Enabled sources:[/bold] {', '.join(enabled)}")

    http_cfg = cfg.get("http", {})
    http = RateLimitedClient(
        rate_limit_seconds=http_cfg.get("rate_limit_seconds", 2.0),
        timeout_seconds=http_cfg.get("timeout_seconds", 30),
        max_retries=http_cfg.get("max_retries", 3),
        user_agent=http_cfg.get("user_agent", "vb-rental-finder/0.1"),
    )
    get_pw, pw_shutdown = _make_pw_factory(cfg)

    raw: list[Listing] = []
    per_source: dict[str, dict] = {}

    for name in enabled:
        mod = SCRAPERS[name]
        console.rule(f"[bold cyan]{name}[/bold cyan]")
        per_source[name] = {"fetched": 0, "filtered": 0, "kept": 0, "error": None}
        try:
            listings = mod.scrape(cfg, http, get_pw, log=logging.getLogger(name))
        except Exception as e:
            logging.exception("scraper %s crashed", name)
            per_source[name]["error"] = str(e)
            continue
        per_source[name]["fetched"] = len(listings)

        kept = []
        for l in listings:
            ok, reason = passes_all(
                l,
                city=cfg["city"],
                state=cfg["state"],
                zips=cfg.get("zips", []),
                rent_min=cfg["rent"]["min"],
                rent_max=cfg["rent"]["max"],
            )
            if not ok:
                per_source[name]["filtered"] += 1
                logging.debug("[%s] dropped (%s) %s", name, reason, l.address)
                continue
            if not l.dedup_key:
                l.dedup_key = make_dedup_key(l.address, l.beds, l.baths)
            kept.append(l)
        per_source[name]["kept"] = len(kept)
        raw.extend(kept)
        console.print(
            f"[green]{name}[/green]: fetched={per_source[name]['fetched']}, "
            f"filtered={per_source[name]['filtered']}, kept={per_source[name]['kept']}"
        )

    pw_shutdown()
    http.close()

    deduped = deduplicate(raw)
    console.print(f"\n[bold]After dedup:[/bold] {len(deduped)} unique listings (from {len(raw)})")

    db.insert_listings(run_id, deduped)
    db.finish_run(run_id, len(deduped))

    today = datetime.now().strftime("%Y-%m-%d")
    csv_path = out_dir / f"listings_{today}.csv"
    write_csv(deduped, csv_path)
    console.print(f"[blue]CSV:[/blue] {csv_path}")

    report_path = Path("report.html")
    source_summary = ", ".join(
        "{}={}".format(k, v["kept"]) for k, v in per_source.items()
    )
    meta = (
        f"Generated {datetime.now().isoformat(timespec='seconds')} • "
        f"{len(deduped)} unique listings • "
        f"sources: {source_summary}"
    )
    write_report(deduped, report_path, extra_meta=meta)
    console.print(f"[blue]Report:[/blue] {report_path}")

    new_count = gone_count = 0
    new_urls: list[str] = []
    gone_urls: list[str] = []
    runs = db.latest_two_runs()
    if len(runs) == 2:
        prev_listings = db.listings_for_run(runs[1])
        diff_path = Path("diff.html")
        new_count, gone_count, new_urls, gone_urls = write_diff(
            deduped, prev_listings, diff_path
        )
        console.print(
            f"[blue]Diff:[/blue] {diff_path} "
            f"({new_count} new, {gone_count} gone)"
        )
        # Dated copy for the audit trail (writes its own styles.css next to it).
        write_diff(deduped, prev_listings, out_dir / f"diff_{today}.html")
    else:
        console.print("[dim]No prior run; skipping diff.html[/dim]")

    # Machine-readable run summary for the daily commit script
    summary_json = out_dir / f"run_{today}.json"
    summary_json.write_text(
        json.dumps({
            "date": today,
            "run_id": run_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "total_unique": len(deduped),
            "total_raw": len(raw),
            "per_source": per_source,
            "diff": {
                "new": new_count,
                "gone": gone_count,
                "new_urls": new_urls,
                "gone_urls": gone_urls,
            },
        }, indent=2),
        encoding="utf-8",
    )
    console.print(f"[blue]Run JSON:[/blue] {summary_json}")

    _print_summary(per_source, len(raw), len(deduped))
    return 0


def _print_summary(per_source: dict[str, dict], total_raw: int, total_unique: int) -> None:
    table = Table(title="Run summary", show_lines=False)
    table.add_column("Source")
    table.add_column("Fetched", justify="right")
    table.add_column("Dropped", justify="right")
    table.add_column("Kept", justify="right")
    table.add_column("Error")
    for name, stats in per_source.items():
        table.add_row(
            name,
            str(stats["fetched"]),
            str(stats["filtered"]),
            str(stats["kept"]),
            (stats["error"] or "")[:60],
        )
    table.add_section()
    table.add_row("TOTAL", "", "", str(total_raw))
    table.add_row("UNIQUE", "", "", str(total_unique))
    console.print(table)


def main():
    p = argparse.ArgumentParser(description="Virginia Beach rental aggregator")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--only", nargs="*", help="Run only the named scrapers")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()
    _setup_logging(args.log_level)
    sys.exit(run(args.config, only=args.only))


if __name__ == "__main__":
    main()
