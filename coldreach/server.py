"""Local web app. Nothing leaves your machine except the searches you ask for.

Started by "Start coldreach.bat" — binds to 127.0.0.1 only, so nothing on your
network or the internet can reach it.
"""
from __future__ import annotations

import json
import socket
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import apollo, compose, find, linkedin, network, profile_import, settings, store

ROOT = Path(__file__).resolve().parent.parent
UI = Path(__file__).resolve().parent / "ui.html"
NETWORK_UI = Path(__file__).resolve().parent / "network.html"
_NET = {"at": 0.0, "data": None}


def net_people(fresh: bool = False) -> list[dict]:
    """Rebuilding reads 6k+ contacts and the message export (~1s), so cache briefly."""
    import time
    if fresh or not _NET["data"] or time.time() - _NET["at"] > 60:
        _NET.update(at=time.time(), data=network.build())
    return _NET["data"]["people"]

JOB = {"running": False, "label": "", "lines": [], "result": None, "error": None}
LOCK = threading.Lock()


cfg = settings.load


def log(msg: str) -> None:
    with LOCK:
        JOB["lines"].append(str(msg))
        JOB["lines"][:] = JOB["lines"][-400:]
    print(msg, flush=True)


def start_job(label: str, fn) -> bool:
    with LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, label=label, lines=[], result=None, error=None)

    def wrap():
        try:
            JOB["result"] = fn()
        except Exception as exc:
            JOB["error"] = f"{type(exc).__name__}: {exc}"
            log(f"Stopped: {JOB['error']}")
        finally:
            JOB["running"] = False

    threading.Thread(target=wrap, daemon=True).start()
    return True


# ── actions ──────────────────────────────────────────────────────────────────

def act_find(body: dict) -> dict:
    c = cfg()
    limit = int(body.get("limit") or 0)
    rows: list[dict] = []
    credits = 0
    needs = None

    if body.get("url"):
        rows = find.run_url(body["url"], body.get("org", ""), body.get("team", ""),
                            c, limit, body.get("audience", "academic"), log)
    else:
        for name in body.get("sources", []):
            src = next((s for s in c.get("sources", []) if s["name"] == name), None)
            if not src:
                log(f"No source named {name}")
                continue
            log(f"--- {name} ---")
            out = find.run_source(src, c, limit, log, bool(body.get("spend_credits")))
            rows += out["rows"]
            credits += out["credits"]
            needs = needs or out.get("needs")
            if out.get("needs") == "confirm_credits":
                return {"needs": "confirm_credits", "candidates": out.get("candidates", []),
                        "cap": out.get("cap"), "source": name}

    added, updated = find.save(rows, log) if rows else (0, 0)
    return {"added": added, "updated": updated, "credits": credits, "needs": needs}


def act_enrich(body: dict) -> dict:
    c = cfg()
    out = find.enrich_pending(c, body.get("company", ""), body.get("title", ""),
                              int(body.get("limit") or 0),
                              bool(body.get("spend_credits")), log)
    if out["rows"]:
        find.save(out["rows"], log)
    return out


def act_import_linkedin(body: dict) -> dict:
    """Read the export folder: fill in the profile, then load the connections."""
    c = cfg()
    folder = body.get("folder") or profile_import.find_export()
    if not folder:
        log("Couldn't find a LinkedIn export folder (one containing Profile.csv).")
        return {"needs": "export_folder"}

    log(f"Reading {folder}")
    facts = profile_import.read_export(folder)
    for line in profile_import.summarize(facts):
        log("  " + line)

    result: dict = {"folder": folder}
    if body.get("apply_profile", True):
        suggested = profile_import.to_profile(facts, c.get("me", {}).get("email", ""))
        settings.set_profile(suggested)
        result["profile"] = suggested
        log("Filled in your profile from the export. Check step 1 and edit the "
            "background until it sounds like you.")

    conn = Path(folder) / "Connections.csv"
    if conn.exists():
        rows = linkedin.import_connections(conn, only_with_email=False, log=log)
        added, updated = find.save(rows, log)
        result.update(added=added, updated=updated, connections=len(rows))
        no_email = sum(1 for r in rows if not r["email"])
        if no_email:
            log(f"{no_email} of them don't publish an email. That's normal — LinkedIn "
                f"hides it. Use 'Look up work emails' below to resolve the ones you "
                f"actually want.")
    return result


def act_compose(body: dict) -> dict:
    c = cfg()
    name = body.get("campaign") or "research_assistant"
    campaign = c["campaigns"][name]
    cap = c.get("limits", {}).get("drafts_per_day", 8)
    limit = min(int(body.get("limit") or 5), cap)
    sim = c.get("limits", {}).get("similarity_threshold", 0.60)

    contacts = store.load_contacts()
    seen = store.already_contacted()
    pool = [x for x in contacts if x.get("email") and x["email"].lower() not in seen]
    if body.get("audience"):
        pool = [x for x in pool if (x.get("audience") or "academic") == body["audience"]]
    if body.get("filter"):
        f = body["filter"].lower()
        pool = [x for x in pool
                if f in " ".join([x.get("org", ""), x.get("team", ""),
                                  x.get("role", ""), x.get("name", "")]).lower()]
    pool.sort(key=lambda x: (0 if x.get("signals") else 1, 0 if x.get("focus") else 1))
    targets = pool[:limit]

    if not targets:
        log("No eligible people. Find some first, or loosen the filter.")
        return {"made": 0, "blocked": 0}

    prior = [d["body"] for d in store.load_drafts()]
    made = blocked = 0
    for t in targets:
        d = compose.compose_one(t, c["me"], campaign, name, prior,
                                use_llm=bool(body.get("llm")), sim_threshold=sim)
        if d["blocked"]:
            log(f"BLOCKED {d['name']}: {'; '.join(d['issues'])}")
            blocked += 1
            continue
        store.append_draft(d)
        prior.append(d["body"])
        made += 1
        log(f"Drafted {d['name']} — {d['subject']}")
    log(f"{made} draft(s) ready, {blocked} blocked.")
    return {"made": made, "blocked": blocked}


def act_push(body: dict) -> dict:
    from . import gmail_api
    c = cfg()
    sender = c["me"]["email"]
    all_drafts = store.load_drafts()
    ids = set(body.get("ids") or [])
    queue = [d for d in all_drafts if not d.get("pushed")
             and (not ids or d.get("email") in ids)]
    queue = queue[:c.get("limits", {}).get("drafts_per_day", 8)]
    if not queue:
        log("Nothing queued.")
        return {"pushed": 0}

    log("Opening Google sign-in if this is the first run...")
    svc = gmail_api.service()
    pushed = 0
    for d in queue:
        try:
            did = gmail_api.create_draft(svc, sender, d["email"], d["subject"], d["body"])
        except Exception as exc:
            log(f"FAILED {d['name']}: {exc}")
            continue
        d["pushed"] = True
        pushed += 1
        store.append_log({
            "email": d["email"], "name": d["name"], "org": d.get("org", ""),
            "campaign": d["campaign"], "subject": d["subject"],
            "drafted_at": store.now(), "draft_id": did,
            "followup_due": str(date.fromordinal(
                date.today().toordinal() + c.get("limits", {}).get("followup_days", 9))),
            "status": "drafted"})
        log(f"Created draft for {d['name']}")
    store.write_drafts(all_drafts)
    log(f"{pushed} Gmail draft(s) created. Open Gmail and look in Drafts.")
    return {"pushed": pushed}


# ── state ────────────────────────────────────────────────────────────────────

def state() -> dict:
    c = cfg()
    contacts = store.load_contacts()
    drafts = store.load_drafts()
    seen = store.already_contacted()
    pool = [x for x in contacts if x.get("email") and x["email"].lower() not in seen]
    today = date.today().isoformat()
    due = [r for r in store.load_log()
           if r.get("status") == "drafted" and r.get("followup_due", "9999") <= today]
    return {
        "me": c.get("me", {}),
        "campaigns": [{"name": k, "audience": v.get("audience", "academic")}
                      for k, v in c.get("campaigns", {}).items()],
        "sources": [{"name": s["name"], "kind": s.get("kind", "directory"),
                     "audience": s.get("audience", ""), "enabled": s.get("enabled", False)}
                    for s in c.get("sources", [])],
        "counts": {"contacts": len(contacts),
                   "with_email": sum(1 for x in contacts if x.get("email")),
                   "untouched": len(pool),
                   "queued": sum(1 for d in drafts if not d.get("pushed")),
                   "followups_due": len(due)},
        "queued": [{"email": d.get("email"), "name": d.get("name"), "org": d.get("org", ""),
                    "subject": d.get("subject"), "body": d.get("body"),
                    "issues": d.get("issues", []), "engine": d.get("engine"),
                    "anchor": d.get("anchor", "")}
                   for d in drafts if not d.get("pushed")],
        "followups": due[:20],
        "apollo_key": bool(apollo.api_key()),
        "linkedin_export": linkedin.find_export(),
        "linkedin_folder": profile_import.find_export(),
        "pending_enrichment": len(find.pending_enrichment()),
        "job": {"running": JOB["running"], "label": JOB["label"],
                "lines": JOB["lines"][-200:], "error": JOB["error"],
                "result": JOB["result"]},
    }


# ── http ─────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, payload, ctype="application/json"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, state())
        if path == "/network":
            return self._send(200, NETWORK_UI.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/network":
            from urllib.parse import parse_qs
            qs = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            people = net_people()
            firm = qs.get("firm") or None
            results = network.search(people, qs["q"]) if qs.get("q") else (
                [p for p in people if p["firm"] == firm] if firm else [])
            return self._send(200, {
                "analytics": network.analytics(people),
                "picks": [network.public(p) for p in network.picks(people)],
                "followups": [network.public(p) for p in network.followups(people)[:12]],
                "referrals": [network.public(p) for p in network.referral_candidates(people, firm)[:20]],
                "results": [network.public(p) for p in results[:80]],
                "targets": sorted(network.almanac_targets()),
                "has_messages": _NET["data"]["has_messages"],
            })
        if path == "/api/network/person":
            from urllib.parse import parse_qs
            pid_ = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            p = next((x for x in net_people() if x["id"] == pid_), None)
            if not p:
                return self._send(404, {"error": "no such person"})
            modes = {"new": ["cold"], "messaged": ["nudge"], "replied": ["book"],
                     "call_scheduled": ["referral", "thanks"], "call_done": ["referral", "thanks"],
                     "referral_asked": ["thanks"], "referred": ["thanks"]}[p["stage"]]
            return self._send(200, {"person": network.public(p),
                                    "drafts": [network.draft_message(p, m) for m in modes]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")

        if path == "/api/profile":
            settings.set_profile(body)
            return self._send(200, {"ok": True})

        if path == "/api/apollo_key":
            apollo.save_key(body.get("key", ""))
            return self._send(200, {"ok": True})

        if path == "/api/source_toggle":
            settings.set_source_enabled(body.get("name", ""), body.get("enabled"))
            return self._send(200, {"ok": True})

        if path == "/api/save_source":
            settings.upsert_source(body)
            return self._send(200, {"ok": True})

        if path == "/api/network/event":
            ev = network.add_event(body["id"], body["kind"], body.get("text", ""))
            net_people(fresh=True)
            return self._send(200, ev)
        if path == "/api/network/debrief":
            ev = network.debrief(body["id"], body.get("transcript", ""))
            net_people(fresh=True)
            return self._send(200, ev)
        if path == "/api/network/sync_almanac":
            return self._send(200, {"message": network.sync_almanac(net_people(fresh=True))})

        if path == "/api/discard":
            drafts = store.load_drafts()
            keep = [d for d in drafts if d.get("pushed") or d.get("email") != body.get("email")]
            store.write_drafts(keep)
            return self._send(200, {"ok": True})

        jobs = {"/api/find": ("Finding people", act_find),
                "/api/enrich": ("Looking up work emails", act_enrich),
                "/api/import_linkedin": ("Reading your LinkedIn export", act_import_linkedin),
                "/api/compose": ("Writing drafts", act_compose),
                "/api/push": ("Creating Gmail drafts", act_push)}
        if path in jobs:
            label, fn = jobs[path]
            if not start_job(label, lambda: fn(body)):
                return self._send(409, {"error": "Something else is still running."})
            return self._send(200, {"started": True})

        self._send(404, {"error": "not found"})


def free_port(preferred: int = 8765) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


def main() -> None:
    port = free_port()
    import os
    url = f"http://127.0.0.1:{port}/" + os.environ.get("COLDREACH_START", "").lstrip("/")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("=" * 62)
    print("  coldreach is running.")
    print(f"  If your browser didn't open, go to:  {url}")
    print("  Close this black window when you're done.")
    print("=" * 62)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
