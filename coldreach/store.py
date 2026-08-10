"""CSV/JSONL persistence, dedupe, and body-similarity scoring.

The schema is deliberately domain-neutral: a contact is a person at an org with
a role, some focus areas, and 'signals' (recent things they did that you can
open an email with). A professor's signals are papers; a founder's are launches;
a PM's are shipped features. Same pipeline either way.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONTACTS = DATA / "contacts.csv"
DRAFTS = DATA / "drafts.jsonl"
LOG = DATA / "outreach_log.csv"

FIELDS = [
    "email", "name", "first_name", "last_name", "role", "org", "team",
    "focus", "signals", "site", "linkedin", "profile_url", "source",
    "source_kind", "audience", "scraped_at", "status", "notes",
]

LOG_FIELDS = ["email", "name", "org", "campaign", "subject", "drafted_at",
              "draft_id", "followup_due", "status"]

# Older versions of this tool used academia-specific column names.
LEGACY = {"title": "role", "school": "org", "dept": "team",
          "interests": "focus", "papers": "signals"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(row: dict) -> dict:
    for old, new in LEGACY.items():
        if row.get(old) and not row.get(new):
            row[new] = row[old]
    return {k: row.get(k, "") for k in FIELDS}


def load_contacts() -> list[dict]:
    if not CONTACTS.exists():
        return []
    with CONTACTS.open(newline="", encoding="utf-8") as f:
        return [_migrate(dict(r)) for r in csv.DictReader(f)]


def save_contacts(rows: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with CONTACTS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def merge_contacts(new: list[dict]) -> tuple[int, int]:
    """Upsert by email, else LinkedIn URL, else profile URL."""
    existing = load_contacts()
    index = {}
    for r in existing:
        index[_key(r)] = r

    added = updated = 0
    for raw in new:
        r = _migrate(raw)
        key = _key(r)
        if not key:
            continue
        if key in index:
            tgt = index[key]
            for k, v in r.items():
                if v and not tgt.get(k):
                    tgt[k] = v
            updated += 1
        else:
            r["status"] = r.get("status") or "new"
            r["scraped_at"] = r.get("scraped_at") or now()
            existing.append(r)
            index[key] = r
            added += 1
    save_contacts(existing)
    return added, updated


def _key(r: dict) -> str:
    return (r.get("email") or r.get("linkedin") or r.get("profile_url") or "").lower().rstrip("/")


def load_drafts() -> list[dict]:
    if not DRAFTS.exists():
        return []
    out = []
    for line in DRAFTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_draft(d: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with DRAFTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")


def write_drafts(drafts: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    DRAFTS.write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in drafts),
        encoding="utf-8")


def append_log(row: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    fresh = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LOG_FIELDS})


def load_log() -> list[dict]:
    if not LOG.exists():
        return []
    with LOG.open(newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def already_contacted() -> set[str]:
    seen = {d["email"].lower() for d in load_drafts() if d.get("email")}
    for r in load_log():
        if r.get("email"):
            seen.add(r["email"].lower())
    return seen


_WORD = re.compile(r"[a-z0-9']+")


def shingles(text: str, n: int = 5) -> set[str]:
    words = _WORD.findall(text.lower())
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def max_similarity(body: str, prior_bodies: list[str]) -> float:
    return max((similarity(body, p) for p in prior_bodies), default=0.0)
