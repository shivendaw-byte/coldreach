"""Import your own LinkedIn connections from LinkedIn's official CSV export.

How to get the file (2 minutes, no scraping, no ToS problem):
  LinkedIn -> Me -> Settings & Privacy -> Data privacy
    -> Get a copy of your data -> pick "Connections" -> Request archive
  LinkedIn emails you a zip within ~10 minutes. Inside is Connections.csv.
  Drop that file anywhere and point the app at it.

The export includes First Name, Last Name, URL, Email Address, Company,
Position, Connected On. Email Address is populated only for connections who
allow it — usually a minority. Everyone else still imports as a warm contact
you can reach on LinkedIn instead.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .store import now

HEADER_HINTS = ("first name", "last name", "url", "company", "position")


def _rows(path: Path) -> list[dict]:
    """LinkedIn prefixes the file with a few 'Notes:' lines before the header."""
    raw = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    start = 0
    for i, line in enumerate(raw[:15]):
        low = line.lower()
        if sum(1 for h in HEADER_HINTS if h in low) >= 3:
            start = i
            break
    return list(csv.DictReader(io.StringIO("\n".join(raw[start:]))))


def _get(row: dict, *names: str) -> str:
    for key, val in row.items():
        if key and key.strip().lower() in names:
            return (val or "").strip()
    return ""


def import_connections(path: str | Path, only_with_email: bool = False,
                       company_filter: str = "", title_filter: str = "",
                       log=print) -> list[dict]:
    path = Path(path).expanduser()
    if not path.exists():
        raise RuntimeError(f"File not found: {path}")

    out = []
    for row in _rows(path):
        first = _get(row, "first name", "firstname")
        last = _get(row, "last name", "lastname")
        if not (first or last):
            continue
        email = _get(row, "email address", "email").lower()
        company = _get(row, "company", "organization")
        position = _get(row, "position", "title")
        url = _get(row, "url", "profile url", "linkedin url")
        connected = _get(row, "connected on")

        if only_with_email and not email:
            continue
        if company_filter and company_filter.lower() not in company.lower():
            continue
        if title_filter and title_filter.lower() not in position.lower():
            continue

        out.append({
            "email": email,
            "name": " ".join(x for x in [first, last] if x),
            "first_name": first,
            "last_name": last,
            "role": position,
            "org": company,
            "team": "",
            "focus": "",
            "signals": "",
            "site": "",
            "linkedin": url,
            "profile_url": url,
            "source": "linkedin-export",
            "source_kind": "linkedin",
            "audience": "warm",
            "scraped_at": now(),
            "status": "new" if email else "linkedin_only",
            "notes": f"connected {connected}" if connected else "",
        })

    with_email = sum(1 for r in out if r["email"])
    log(f"Read {len(out)} connection(s); {with_email} have an email address in the export.")
    if out and not with_email:
        log("None of these expose an email. They still import as warm contacts — "
            "message those on LinkedIn rather than guessing an address.")
    return out


def find_export(search_roots: list[str] | None = None) -> str:
    """Look for Connections.csv in the usual download spots."""
    roots = [Path(p).expanduser() for p in (search_roots or [
        "~/Downloads", "~/OneDrive/Desktop", "~/Desktop", "~/Documents"])]
    best, best_mtime = "", 0.0
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.glob("**/Connections.csv"):
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m > best_mtime:
                best, best_mtime = str(p), m
    return best
