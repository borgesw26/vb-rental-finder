"""Send an email notification listing the houses flagged as new in the latest run.

Reads is_new=1 rows from the most recent finished run in listings.db. If there
are none, exits silently (no email). Otherwise composes a plain-text + HTML
email and sends it via SMTP.

Required env vars (skips silently if any are missing — keeps local dev quiet):
  SMTP_HOST            e.g. smtp.gmail.com
  SMTP_PORT            e.g. 587
  SMTP_USER            full email used to authenticate
  SMTP_PASSWORD        Gmail app password (not the account password)
  NOTIFY_RECIPIENTS    comma-separated list of recipient emails

Optional:
  SMTP_FROM            "From:" header (defaults to SMTP_USER)
  REPORT_URL           link to the public report (added to email footer)
  DB_PATH              defaults to listings.db
"""
from __future__ import annotations

import logging
import os
import smtplib
import sqlite3
import sys
from email.message import EmailMessage
from html import escape
from pathlib import Path

log = logging.getLogger("notify")


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else v


def _new_listings_for_latest_run(db_path: Path) -> list[dict]:
    if not db_path.exists():
        log.info("DB %s not found; nothing to send.", db_path)
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT id FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return []
        rows = conn.execute(
            "SELECT * FROM listings WHERE run_id = ? AND is_new = 1 "
            "ORDER BY rent IS NULL, rent ASC",
            (latest["id"],),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _fmt_money(n) -> str:
    try:
        return f"${int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(n) -> str:
    if n is None:
        return "—"
    try:
        f = float(n)
        return str(int(f)) if f.is_integer() else f"{f:g}"
    except (TypeError, ValueError):
        return str(n)


def _summary_line(l: dict) -> str:
    parts = [
        _fmt_money(l.get("rent")) + "/mo",
        f"{_fmt_num(l.get('beds'))} bd",
        f"{_fmt_num(l.get('baths'))} ba",
    ]
    if l.get("sqft"):
        parts.append(f"{int(l['sqft']):,} sqft")
    return " • ".join(parts)


def _build_text(listings: list[dict], report_url: str | None) -> str:
    lines = [f"{len(listings)} new Virginia Beach rental(s) found:\n"]
    for i, l in enumerate(listings, 1):
        lines.append(f"{i}. {l.get('address') or 'Unknown address'}")
        lines.append(f"   {_summary_line(l)}  [{l.get('source') or '?'}]")
        if l.get("listing_url"):
            lines.append(f"   {l['listing_url']}")
        lines.append("")
    if report_url:
        lines.append(f"Full report: {report_url}")
    return "\n".join(lines)


def _build_html(listings: list[dict], report_url: str | None) -> str:
    items = []
    for l in listings:
        url = l.get("listing_url") or "#"
        addr = escape(l.get("address") or "Unknown address")
        items.append(
            "<li style=\"margin-bottom:14px\">"
            f"<a href=\"{escape(url)}\" style=\"font-weight:600;text-decoration:none\">{addr}</a><br>"
            f"<span style=\"color:#444\">{escape(_summary_line(l))}</span>"
            f"<span style=\"color:#888\"> &middot; {escape(l.get('source') or '?')}</span>"
            "</li>"
        )
    body = (
        f"<p>{len(listings)} new Virginia Beach rental(s) found.</p>"
        f"<ol>{''.join(items)}</ol>"
    )
    if report_url:
        body += (
            f"<p style=\"margin-top:18px;color:#666;font-size:13px\">"
            f"Full report: <a href=\"{escape(report_url)}\">{escape(report_url)}</a></p>"
        )
    return (
        "<html><body style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif\">"
        f"{body}</body></html>"
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    host = _env("SMTP_HOST")
    port = _env("SMTP_PORT")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    recipients_raw = _env("NOTIFY_RECIPIENTS")

    if not all([host, port, user, password, recipients_raw]):
        log.info("SMTP env vars not set — skipping notification.")
        return 0

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        log.info("NOTIFY_RECIPIENTS is empty — skipping.")
        return 0

    db_path = Path(_env("DB_PATH") or "listings.db")
    new_listings = _new_listings_for_latest_run(db_path)
    if not new_listings:
        log.info("No new listings in the latest run — no email sent.")
        return 0

    sender = _env("SMTP_FROM") or user
    report_url = _env("REPORT_URL")
    subject = (
        f"{len(new_listings)} new Virginia Beach rental"
        f"{'s' if len(new_listings) != 1 else ''}"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(_build_text(new_listings, report_url))
    msg.add_alternative(_build_html(new_listings, report_url), subtype="html")

    log.info("Sending notification to %s about %d new listing(s)…",
             ", ".join(recipients), len(new_listings))
    with smtplib.SMTP(host, int(port)) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    log.info("Email sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
