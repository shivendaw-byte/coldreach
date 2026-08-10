"""Apollo.io: find people by title/company/location, then reveal emails.

Two stages, deliberately separated because they cost different things:

  search()  -> free. Returns first name, title, org, Apollo id. Apollo
               obfuscates last names and returns NO email here.
  enrich()  -> 1 credit per person that resolves. This is the only way to get
               a real email out of Apollo.

Nothing in this module spends a credit unless you call enrich() explicitly.
Get an API key at apollo.io -> Settings -> Integrations -> API.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from .store import now

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "data" / ".apollo_key"
SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
MATCH_URL = "https://api.apollo.io/api/v1/people/match"

MASKED = ("email_not_unlocked", "domain.com", "not_unlocked")


def api_key() -> str:
    return (os.getenv("APOLLO_API_KEY")
            or (KEY_FILE.read_text(encoding="utf-8").strip()
                if KEY_FILE.exists() else ""))


def save_key(key: str) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip(), encoding="utf-8")


def _headers() -> dict:
    key = api_key()
    if not key:
        raise RuntimeError("No Apollo API key. Paste one in the app, or set APOLLO_API_KEY.")
    return {"Content-Type": "application/json", "Cache-Control": "no-cache",
            "x-api-key": key}


def _post(url: str, payload: dict) -> dict:
    r = requests.post(url, headers=_headers(), data=json.dumps(payload), timeout=40)
    if r.status_code == 401:
        raise RuntimeError("Apollo rejected the API key (401). Check it in Settings.")
    if r.status_code == 403:
        raise RuntimeError("Apollo returned 403 — your plan may not allow this endpoint.")
    if r.status_code == 429:
        raise RuntimeError("Apollo rate limit hit (429). Wait a minute and retry.")
    if not r.ok:
        raise RuntimeError(f"Apollo error {r.status_code}: {r.text[:200]}")
    return r.json()


def search(titles: list[str] | None = None, companies: list[str] | None = None,
           locations: list[str] | None = None, seniorities: list[str] | None = None,
           keywords: str = "", per_page: int = 25, page: int = 1,
           log=print) -> list[dict]:
    """Free. Returns candidates WITHOUT emails — last names are obfuscated."""
    payload: dict = {"page": page, "per_page": min(per_page, 100)}
    if titles:
        payload["person_titles"] = titles
    if companies:
        payload["q_organization_domains_list"] = companies
    if locations:
        payload["person_locations"] = locations
    if seniorities:
        payload["person_seniorities"] = seniorities
    if keywords:
        payload["q_keywords"] = keywords

    data = _post(SEARCH_URL, payload)
    people = data.get("people") or data.get("contacts") or []
    log(f"Apollo returned {len(people)} candidate(s) of {data.get('total_entries', '?')} total.")

    out = []
    for p in people:
        org = (p.get("organization") or {})
        out.append({
            "apollo_id": p.get("id", ""),
            "first_name": p.get("first_name", ""),
            "last_name": p.get("last_name") or p.get("last_name_obfuscated", ""),
            "name": " ".join(x for x in [p.get("first_name", ""),
                                         p.get("last_name") or ""] if x).strip(),
            "role": p.get("title", ""),
            "org": org.get("name", "") or p.get("organization_name", ""),
            "domain": org.get("primary_domain", "") or org.get("website_url", ""),
            "linkedin": p.get("linkedin_url", "") or "",
            "has_email": bool(p.get("has_email") or p.get("email")),
        })
    return out


def enrich(candidate: dict, reveal_personal: bool = False) -> dict | None:
    """COSTS 1 APOLLO CREDIT when it resolves. Returns a contact row or None."""
    payload = {k: v for k, v in {
        "id": candidate.get("apollo_id"),
        "first_name": candidate.get("first_name"),
        "last_name": candidate.get("last_name"),
        "organization_name": candidate.get("org"),
        "domain": candidate.get("domain"),
        "linkedin_url": candidate.get("linkedin"),
    }.items() if v}
    if reveal_personal:
        payload["reveal_personal_emails"] = True

    data = _post(MATCH_URL, payload)
    p = data.get("person") or {}
    email = (p.get("email") or "").strip().lower()
    if not email or any(m in email for m in MASKED):
        return None

    org = (p.get("organization") or {})
    first = p.get("first_name", "") or candidate.get("first_name", "")
    last = p.get("last_name", "") or ""
    return {
        "email": email,
        "name": " ".join(x for x in [first, last] if x).strip() or candidate.get("name", ""),
        "first_name": first,
        "last_name": last,
        "role": p.get("title", "") or candidate.get("role", ""),
        "org": org.get("name", "") or candidate.get("org", ""),
        "team": p.get("departments", [""])[0] if p.get("departments") else "",
        "focus": ", ".join(p.get("functions", [])[:3]) if p.get("functions") else "",
        "signals": "",
        "site": org.get("website_url", "") or "",
        "linkedin": p.get("linkedin_url", "") or candidate.get("linkedin", ""),
        "profile_url": "",
        "source": "apollo.io",
        "source_kind": "apollo",
        "audience": "work",
        "scraped_at": now(),
        "status": "new",
        "notes": "",
    }


def enrich_contacts(rows: list[dict], max_enrich: int, reveal_personal: bool = False,
                    log=print) -> tuple[list[dict], int]:
    """Look up work emails for people you already have (e.g. LinkedIn connections).

    A LinkedIn profile URL is the highest-quality match key Apollo accepts, so this
    resolves far more reliably than a name+company guess. COSTS ~1 CREDIT EACH.
    """
    out, spent = [], 0
    for row in rows[:max_enrich]:
        candidate = {"first_name": row.get("first_name"), "last_name": row.get("last_name"),
                     "org": row.get("org"), "linkedin": row.get("linkedin"),
                     "name": row.get("name")}
        try:
            found = enrich(candidate, reveal_personal)
        except RuntimeError as exc:
            log(f"Stopped: {exc}")
            break
        spent += 1
        if found:
            merged = {**row, **{k: v for k, v in found.items() if v}}
            merged["source_kind"] = "linkedin+apollo"
            merged["audience"] = row.get("audience") or "warm"
            merged["status"] = "new"
            out.append(merged)
            log(f"{merged['name']} — {merged['email']}")
        else:
            log(f"No email on file for {row.get('name')}")
        time.sleep(0.4)
    log(f"Resolved {len(out)} of {min(len(rows), max_enrich)}; about {spent} credit(s) used.")
    return out, spent


def search_and_enrich(query: dict, max_enrich: int, reveal_personal: bool = False,
                      log=print) -> tuple[list[dict], int]:
    """Returns (contact rows, credits actually spent)."""
    candidates = search(log=log, **query)
    if not candidates:
        return [], 0

    ordered = sorted(candidates, key=lambda c: 0 if c.get("has_email") else 1)
    rows, spent = [], 0
    for c in ordered[:max_enrich]:
        try:
            row = enrich(c, reveal_personal)
        except RuntimeError as exc:
            log(f"Stopped: {exc}")
            break
        spent += 1
        if row:
            rows.append(row)
            log(f"Found {row['name']} — {row['email']}")
        else:
            log(f"No email available for {c.get('name') or c.get('first_name')}")
        time.sleep(0.4)
    log(f"Enriched {len(rows)} contact(s); about {spent} Apollo credit(s) used.")
    return rows, spent
