"""One entry point for every way of finding people, dispatched by source kind."""
from __future__ import annotations

from pathlib import Path

from . import apollo, harvest, linkedin, scrape, store

ROOT = Path(__file__).resolve().parent.parent


def run_source(src: dict, cfg: dict, limit: int = 0, log=print,
               spend_credits: bool = False) -> dict:
    """Returns {'rows': [...], 'credits': int, 'needs': str|None}."""
    kind = src.get("kind", "directory")
    delay = cfg.get("scrape", {}).get("delay_seconds", 2.0)

    if kind == "directory":
        rows = scrape.scrape_source(src, limit, delay, log)
        return {"rows": rows, "credits": 0, "needs": None}

    if kind == "apollo":
        if not apollo.api_key():
            log("No Apollo API key saved yet.")
            return {"rows": [], "credits": 0, "needs": "apollo_key"}
        query = dict(src.get("query") or {})
        cap = limit or cfg.get("limits", {}).get("apollo_max_enrich", 10)
        if not spend_credits:
            cands = apollo.search(log=log, **query)
            log(f"{len(cands)} candidate(s) found. Apollo hides emails until you "
                f"reveal them, which costs about 1 credit each.")
            return {"rows": [], "credits": 0, "needs": "confirm_credits",
                    "candidates": cands[:cap], "cap": cap}
        rows, spent = apollo.search_and_enrich(
            query, cap, src.get("reveal_personal", False), log)
        for r in rows:
            r["audience"] = src.get("audience", "work")
        return {"rows": rows, "credits": spent, "needs": None}

    if kind == "linkedin":
        path = src.get("path") or ""
        if path and not Path(path).expanduser().exists():
            log(f"That file isn't there any more: {path}")
            path = ""
        path = path or linkedin.find_export()
        if not path:
            log("Couldn't find Connections.csv in Downloads, Desktop, or Documents. "
                "Export it from LinkedIn (Settings & Privacy -> Data privacy -> "
                "Get a copy of your data -> Connections), unzip it, then try again.")
            return {"rows": [], "credits": 0, "needs": "linkedin_file"}
        log(f"Reading {path}")
        rows = linkedin.import_connections(
            path, src.get("only_with_email", True), src.get("company_filter", ""),
            src.get("title_filter", ""), log)
        if limit:
            rows = rows[:limit]
        return {"rows": rows, "credits": 0, "needs": None}

    if kind == "documents":
        folder = src.get("path", "")
        if not folder or not Path(folder).expanduser().is_dir():
            return {"rows": [], "credits": 0, "needs": "folder"}
        rows = harvest.harvest_contacts(Path(folder).expanduser(),
                                        src.get("org", ""), src.get("team", ""))
        return {"rows": rows, "credits": 0, "needs": None}

    log(f"Unknown source kind: {kind}")
    return {"rows": [], "credits": 0, "needs": None}


def run_url(url: str, org: str, team: str, cfg: dict, limit: int = 0,
            audience: str = "academic", log=print) -> list[dict]:
    delay = cfg.get("scrape", {}).get("delay_seconds", 2.0)
    return scrape.scrape_directory(url, org, team, limit, delay, audience, log)


def pending_enrichment(company: str = "", title: str = "") -> list[dict]:
    """People you already have who lack an email but do have a LinkedIn URL."""
    out = []
    for r in store.load_contacts():
        if r.get("email") or not r.get("linkedin"):
            continue
        hay = " ".join([r.get("org", ""), r.get("role", ""), r.get("name", "")]).lower()
        if company and company.lower() not in (r.get("org", "") or "").lower():
            continue
        if title and title.lower() not in (r.get("role", "") or "").lower():
            continue
        out.append(r)
    return out


def enrich_pending(cfg: dict, company: str = "", title: str = "", limit: int = 0,
                   spend_credits: bool = False, log=print) -> dict:
    if not apollo.api_key():
        log("No Apollo API key saved yet.")
        return {"rows": [], "credits": 0, "needs": "apollo_key"}

    targets = pending_enrichment(company, title)
    cap = limit or cfg.get("limits", {}).get("apollo_max_enrich", 10)
    if not targets:
        log("Nobody matches. Import your LinkedIn connections first, or widen the filter.")
        return {"rows": [], "credits": 0, "needs": None}

    if not spend_credits:
        log(f"{len(targets)} connection(s) match and have no email yet. "
            f"Looking them up costs about 1 Apollo credit each.")
        return {"rows": [], "credits": 0, "needs": "confirm_credits",
                "candidates": [{"name": t.get("name"), "org": t.get("org"),
                                "role": t.get("role")} for t in targets[:cap]],
                "cap": min(cap, len(targets)), "mode": "enrich"}

    rows, spent = apollo.enrich_contacts(targets, cap, False, log)
    return {"rows": rows, "credits": spent, "needs": None}


def save(rows: list[dict], log=print) -> tuple[int, int]:
    added, updated = store.merge_contacts(rows)
    with_email = sum(1 for r in rows if r.get("email"))
    log(f"{len(rows)} person/people processed, {with_email} with a usable email. "
        f"{added} new, {updated} updated.")
    if rows and with_email < len(rows):
        log(f"{len(rows) - with_email} had no published email and were kept without one. "
            f"Guessed addresses bounce, and bounces hurt your sender reputation.")
    return added, updated
