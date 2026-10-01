"""Network: Recap-style relationship engine on top of coldreach's data.

Recap (recap.network) offers: an alumni directory, natural-language search, daily
picks, email finding, AI-personalized batch outreach, call recording + scoring,
thank-you drafts, a per-contact timeline, follow-up reminders, "who can refer
me?", and analytics. This module does the same for Shiven, from data he already
owns:

  directory     data/contacts.csv (6,600+ LinkedIn connections + scraped/Apollo rows)
  timeline      LinkedIn export messages.csv (real conversation history)
                + data/network_events.jsonl (calls, replies, referrals logged here)
                + data/outreach_log.csv (coldreach email drafts)
  targets       Almanac's config/opportunities.yaml + applications.yaml (consulting firms)

What it deliberately does NOT do, and why:
  - It doesn't send anything. Messages are copied for LinkedIn, and emails go to Gmail drafts.
  - It doesn't record calls. Paste notes or a transcript (Zoom/Meet/Otter export) instead.
    Recording other people needs their consent and is two-party in PA.
  - It has no shared alumni database. Recap's directory is their data. Yours comes
    from your export, Penn Grabber, and Apollo, and for consulting firms your
    connections are deeper than any shared list (BCG 135, McKinsey 133, Bain 90).

Everything stays in data/ (gitignored). Only firm-level counts, never names,
are written out to Almanac.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import linkedin, store

ROOT = Path(__file__).resolve().parent.parent
EVENTS = store.DATA / "network_events.jsonl"
ALMANAC = Path.home() / "OneDrive" / "Desktop" / "almanac"
ME = "Shiven Dawda"

STAGES = ["new", "messaged", "replied", "call_scheduled", "call_done", "referral_asked", "referred"]
STAGE_LABEL = {"new": "Not contacted", "messaged": "Messaged", "replied": "Replied",
               "call_scheduled": "Call scheduled", "call_done": "Had a call",
               "referral_asked": "Referral asked", "referred": "Referred"}

# Firm name normalization: "Deloitte Consulting", "Deloitte" → "Deloitte".
FIRM_ALIASES = {
    "deloitte": "Deloitte", "fti": "FTI Consulting", "l.e.k": "L.E.K. Consulting", "lek consulting": "L.E.K. Consulting",
    "brattle": "The Brattle Group", "mckinsey": "McKinsey", "boston consulting": "BCG", "bcg": "BCG",
    "bain": "Bain", "oliver wyman": "Oliver Wyman", "accenture": "Accenture", "kpmg": "KPMG",
    "pwc": "PwC", "strategy&": "PwC", "ernst": "EY", "kearney": "Kearney", "analysis group": "Analysis Group",
    "cornerstone research": "Cornerstone Research", "charles river": "Charles River Associates",
    "compass lexecon": "Compass Lexecon", "alvarez": "Alvarez & Marsal", "zs associates": "ZS",
    "guidehouse": "Guidehouse", "huron": "Huron", "simon-kucher": "Simon-Kucher", "alphasights": "AlphaSights",
}


def firm_of(org: str) -> str:
    o = (org or "").lower()
    for k, v in FIRM_ALIASES.items():
        if k in o:
            return v
    return (org or "").strip()


def pid(row: dict) -> str:
    key = (row.get("linkedin") or row.get("email") or row.get("name", "")).lower().rstrip("/")
    return hashlib.sha1(key.encode()).hexdigest()[:10]


# ── data loading ─────────────────────────────────────────────────────────────

def load_messages() -> list[dict]:
    """LinkedIn export messages.csv → [{with, date, from_me, text}] (1:1 threads only)."""
    try:
        root = Path(linkedin.find_export())
    except Exception:  # noqa: BLE001
        return []
    path = (root if root.is_dir() else root.parent) / "messages.csv"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            frm, to = r.get("FROM", "").strip(), [t.strip() for t in r.get("TO", "").split(",") if t.strip()]
            if len(to) != 1:
                continue  # group threads aren't relationship signal
            other = to[0] if frm == ME else frm
            out.append({"with": other, "date": r.get("DATE", "")[:16], "from_me": frm == ME,
                        "text": (r.get("CONTENT") or "").strip()})
    return out


def load_events() -> list[dict]:
    if not EVENTS.exists():
        return []
    return [json.loads(l) for l in EVENTS.read_text(encoding="utf-8").splitlines() if l.strip()]


def add_event(person_id: str, kind: str, text: str = "", **extra) -> dict:
    ev = {"id": person_id, "kind": kind, "text": text, "at": datetime.now().isoformat(timespec="minutes"), **extra}
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def almanac_targets() -> dict[str, dict]:
    """Firms Shiven is recruiting for, from Almanac (consulting only)."""
    out: dict[str, dict] = {}
    try:
        import yaml
        opp = yaml.safe_load((ALMANAC / "config" / "opportunities.yaml").read_text(encoding="utf-8"))
        for p in opp.get("programs", []):
            for org in re.split(r"\s*·\s*", p["org"]):
                f = firm_of(org)
                if f and "alumni" not in f.lower():
                    out.setdefault(f, {"deadline": p.get("deadline"), "summer": p.get("summer")})
    except Exception:  # noqa: BLE001
        pass
    return out


# ── people + stage inference ─────────────────────────────────────────────────

CALL_RX = re.compile(r"\b(call|chat|zoom|phone|my number|\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|gcal|calendar invite|free (tmr|tomorrow|monday|tuesday|wednesday|thursday|friday))", re.I)


def build() -> dict:
    contacts = store.load_contacts()
    msgs = load_messages()
    events = load_events()
    by_name: dict[str, list] = defaultdict(list)
    for m in msgs:
        by_name[m["with"].lower()].append(m)
    ev_by: dict[str, list] = defaultdict(list)
    for e in events:
        ev_by[e["id"]].append(e)
    log = {r.get("email", "").lower(): r for r in store.load_log()}
    targets = almanac_targets()

    people = []
    for c in contacts:
        if c.get("source_kind") == "directory" and c.get("audience") == "academic":
            kind = "academic"
        else:
            kind = "work"
        p_id = pid(c)
        thread = sorted(by_name.get(c["name"].lower(), []), key=lambda m: m["date"])
        evs = ev_by.get(p_id, [])
        stage = "new"
        if thread:
            stage = "messaged"
            if any(not m["from_me"] for m in thread):
                stage = "replied"
            if any(not m["from_me"] and CALL_RX.search(m["text"]) for m in thread):
                stage = "call_scheduled"
        if c.get("email", "").lower() in log:
            stage = max(stage, "messaged", key=STAGES.index)
        for e in evs:
            if e["kind"] in STAGES:
                stage = max(stage, e["kind"], key=STAGES.index)
        last = max([m["date"] for m in thread] + [e["at"] for e in evs] + [""])
        firm = firm_of(c.get("org", ""))
        people.append({
            "id": p_id, "name": c["name"], "first": c.get("first_name") or c["name"].split()[0],
            "role": c.get("role", ""), "org": c.get("org", ""), "firm": firm, "email": c.get("email", ""),
            "linkedin": c.get("linkedin") or c.get("profile_url", ""), "kind": kind,
            "connected": (c.get("notes", "").replace("connected ", "") if c.get("source_kind") == "linkedin" else ""),
            "stage": stage, "last": last, "target": firm in targets,
            "thread": thread[-12:], "events": evs,
            "debrief": next((e for e in reversed(evs) if e["kind"] == "debrief"), None),
        })
    return {"people": people, "targets": targets, "has_messages": bool(msgs)}


# ── search ("bain boston", typos and all) ────────────────────────────────────

def _haystack(p: dict) -> str:
    return f"{p['name']} {p['role']} {p['org']} {p['firm']} {STAGE_LABEL[p['stage']]}".lower()


def search(people: list[dict], q: str, limit: int = 60) -> list[dict]:
    terms = [t for t in re.split(r"\s+", q.lower().strip()) if t]
    if not terms:
        return []
    vocab_cache: dict[str, list[str]] = {}
    scored = []
    for p in people:
        hay = _haystack(p)
        words = vocab_cache.setdefault(p["id"], re.findall(r"[a-z0-9&.]+", hay))
        score = 0.0
        for t in terms:
            if t in hay:
                score += 2
            else:
                best = difflib.get_close_matches(t, words, n=1, cutoff=0.78)
                if not best:
                    score = -1
                    break
                score += 1
        if score > 0:
            score += 0.5 * p["target"] + 0.3 * (p["stage"] in ("replied", "call_scheduled", "call_done"))
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:limit]]


# ── today's picks + follow-ups + referrals ──────────────────────────────────

RELEVANT_ROLE = re.compile(r"consult|strategy|analyst|associate|intern|economist|manager|advis", re.I)
JUNIOR = re.compile(r"intern|incoming|analyst|associate|summer", re.I)


def picks(people: list[dict], n: int = 6, today: date | None = None) -> list[dict]:
    """Daily, deterministic: target-firm connections never messaged, juniors first
    (closest to his path and most likely to answer), rotated by date so it changes daily."""
    today = today or date.today()
    pool = [p for p in people if p["target"] and p["stage"] == "new" and p["kind"] == "work"
            and RELEVANT_ROLE.search(p["role"]) and p["linkedin"]]
    pool.sort(key=lambda p: (not re.search(r"strategy|consult", p["role"], re.I), not JUNIOR.search(p["role"]),
                             hashlib.sha1((p["id"] + today.isoformat()).encode()).hexdigest()))
    out, per_firm = [], Counter()
    for p in pool:
        if per_firm[p["firm"]] >= 2:
            continue
        per_firm[p["firm"]] += 1
        out.append(p)
        if len(out) >= n:
            break
    return out


def followups(people: list[dict], days: int = 7) -> list[dict]:
    """Messaged, no reply, last touch older than `days`, and only one nudge ever."""
    cut = (datetime.now() - timedelta(days=days)).isoformat()
    out = []
    for p in people:
        if p["stage"] != "messaged" or not p["last"] or p["last"] > cut:
            continue
        mine = [m for m in p["thread"] if m["from_me"]]
        nudges = len(mine) - 1 + sum(e["kind"] == "nudged" for e in p["events"])
        if nudges < 1:
            out.append(p)
    return sorted(out, key=lambda p: (not p["target"], p["last"]))


def referral_candidates(people: list[dict], firm: str | None = None) -> list[dict]:
    """'Who can refer me?': people you've actually talked to, at the firm."""
    rank = {"referred": 0, "referral_asked": 1, "call_done": 2, "call_scheduled": 3, "replied": 4}
    out = [p for p in people if p["stage"] in rank and (not firm or p["firm"] == firm)]
    return sorted(out, key=lambda p: (rank[p["stage"]], p["last"]), reverse=False)


# ── analytics (Recap's dashboard) ────────────────────────────────────────────

def analytics(people: list[dict], weekly_goal: int = 15) -> dict:
    touched = [p for p in people if p["stage"] != "new"]
    replied = [p for p in touched if STAGES.index(p["stage"]) >= STAGES.index("replied")]
    calls = [p for p in touched if STAGES.index(p["stage"]) >= STAGES.index("call_scheduled")]
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    this_week = sum(1 for p in people for m in p["thread"] if m["from_me"] and m["date"] >= week_ago) \
        + sum(1 for p in people for e in p["events"] if e["kind"] == "messaged" and e["at"] >= week_ago)
    firms: dict[str, Counter] = defaultdict(Counter)
    for p in people:
        if p["target"]:
            firms[p["firm"]]["connections"] += 1
            firms[p["firm"]][p["stage"]] += 1
    scores = [p["debrief"]["score"] for p in people if p["debrief"] and p["debrief"].get("score") is not None]
    return {
        "messaged": len(touched), "replied": len(replied), "calls": len(calls),
        "reply_rate": round(100 * len(replied) / len(touched)) if touched else 0,
        "call_rate": round(100 * len(calls) / len(touched)) if touched else 0,
        "this_week": this_week, "weekly_goal": weekly_goal,
        "avg_call_score": round(sum(scores) / len(scores), 1) if scores else None,
        "firms": {f: dict(c) for f, c in sorted(firms.items(), key=lambda x: -x[1]["connections"])},
    }


# ── drafting (his voice) ─────────────────────────────────────────────────────

# Facts are chosen to echo the person's world, per his rule: sentence 2 starts
# "I'm super interested in…", then a "Fun facts about me:" pair that echoes it.
FACTS = {
    "econ": ["Research assistant at VCU using 50K+ CPS records and IV methods to measure post-WWII trade shocks",
             "Benjamin Franklin Scholar studying Math Econ with a Wharton Stats & Data Science minor"],
    "public": ["Redesigned a small-business portal in a VA delegate's office, cutting $15K and 32% of applicant time",
               "Class VP at Penn and on the UA, managing a $3.1M budget across 500+ orgs"],
    "strategy": ["Built a go-to-market strategy that won the top pitch among 150 interns (22% ROI)",
                 "Ran cases on Jollibee market entry, CityRose channel strategy (+15%) and NoMatch pricing"],
    "finance": ["2nd place at the Wharton IBEC pitch competition with a Halliburton long thesis",
                "Vice Chair of Economic Analysis at Wharton IBEC"],
}


def _lane(p: dict) -> str:
    r = (p["role"] + " " + p["org"]).lower()
    if re.search(r"econom|brattle|cornerstone|analysis group|charles river|compass|forensic|litigation|transfer pricing|data|analytics|risk", r):
        return "econ"
    if re.search(r"gov|public|gps|federal|policy", r):
        return "public"
    if re.search(r"restructuring|corporate finance|m&a|transaction|valuation", r):
        return "finance"
    return "strategy"


def _a(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _hook(p: dict) -> str:
    """A noun phrase that fits 'I'm super interested in ___'."""
    role = re.sub(r"\s+at\s+.*$", "", p["role"]).strip()
    role = re.sub(r"^incoming\s+", "", role, flags=re.I)
    firm = p["firm"] or p["org"]
    if re.search(r"intern", role, re.I):
        return f"how you landed the {role} role at {firm} as an undergrad"
    if re.search(r"incoming", p["role"], re.I):
        return f"what made you choose {firm} for your {role} role"
    if re.fullmatch(r"(senior )?(analyst|consultant|associate)", role, re.I):
        return f"what your day-to-day as {_a(role)} {role} at {firm} actually looks like"
    team = re.split(r"\s*[,–—-]\s*", role, maxsplit=1)
    if len(team) == 2 and team[1]:
        return f"your work in {team[1]} at {firm}"   # "Senior Consultant, Strategy & Analytics"
    return f"your work as {_a(role)} {role} at {firm}" if role else f"your path to {firm}"


def draft_message(p: dict, mode: str = "cold") -> dict:
    """LinkedIn message in his voice. mode: cold | nudge | book | referral | thanks."""
    first, firm = p["first"], p["firm"] or p["org"]
    referrer = next((m.group(1) for t in p.get("thread", []) if t["from_me"]
                     for m in [re.search(r"\b([A-Z][a-z]+) recommended", t["text"])] if m), None)
    if mode == "nudge" and referrer:
        body = (f"Hi {first}, following up on my note. {referrer} suggested I reach out. I'm applying to "
                f"{firm}'s sophomore programs this fall and would really value 15 minutes on your path there. "
                f"Any time next week works on my end.")
    elif mode == "nudge":
        body = (f"Hi {first}, bumping this in case LinkedIn buried it. I'm applying to {firm}'s "
                f"sophomore programs this fall and would really value 15 minutes on your experience. "
                f"Any time next week works on my end.")
    elif mode == "book":
        body = (f"Hi {first}, thanks for getting back to me! Would 15 minutes on Tuesday or Thursday "
                f"afternoon next week work? Happy to work around your schedule, and I'll send a calendar invite.")
    elif mode == "referral":
        body = (f"Hi {first}, thanks again for chatting with me this summer. It shaped how I'm approaching "
                f"recruiting. I'm now applying to {firm}'s Summer 2027 internship, and since you know my "
                f"background, would you be comfortable referring me or pointing me to the right recruiter? "
                f"Happy to send my resume and a two-line summary to make it easy.")
    elif mode == "thanks":
        note = (p.get("debrief") or {}).get("highlight") or "what you said about the work"
        body = (f"Hi {first}, thank you for the time today. I especially appreciated {note}. "
                f"I'll take your advice and keep you posted on how recruiting goes.")
    else:
        a, b = FACTS[_lane(p)]
        body = (f"Hi {first}, I'm Shiven, a sophomore at Penn studying Mathematical Economics. "
                f"I'm super interested in {_hook(p)}. Fun facts about me:\n- {a}\n- {b}\n"
                f"Would you be open to a quick 15-min chat sometime next week?")
    return {"id": p["id"], "mode": mode, "text": body, "chars": len(body), "url": p["linkedin"]}


# ── call debrief (Recap's call scoring, from notes/transcript) ───────────────

def debrief(person_id: str, transcript: str, my_name: str = "Shiven") -> dict:
    """Mechanical metrics from a pasted transcript. Claude adds the qualitative score.

    Works with 'Name: text' speaker-labelled transcripts (Zoom, Meet, Otter, Granola).
    """
    me_words = them_words = 0
    my_qs, open_qs = [], 0
    first_line = ""
    for line in transcript.splitlines():
        m = re.match(r"^\s*(?:\[?[\d:]+\]?\s*)?([A-Za-z][\w .'-]{0,40}):\s*(.+)$", line)
        if not m:
            continue
        who, text = m.group(1).strip(), m.group(2)
        n = len(text.split())
        if who.lower().startswith(my_name.lower()) or who.lower() in ("me", "you"):
            me_words += n
            first_line = first_line or text
            for q in re.findall(r"[^.?!]*\?", text):
                my_qs.append(q.strip())
                if re.match(r"\s*(how|why|what|tell me|walk me|could you describe)", q, re.I):
                    open_qs += 1
        else:
            them_words += n
    total = me_words + them_words
    metrics = {
        "airtime_pct": round(100 * me_words / total) if total else None,
        "questions": len(my_qs), "open_questions": open_qs,
        "opening": first_line[:200],
        "airtime_note": ("Good, you let them talk." if total and me_words / total <= 0.35 else
                         "You talked more than a third of the time. Ask more, pitch less." if total else
                         "No speaker labels found. Paste a transcript as 'Name: text' lines for metrics."),
    }
    ev = add_event(person_id, "debrief", transcript[:4000], metrics=metrics, score=None, highlight="")
    add_event(person_id, "call_done", "")
    return ev


# ── Almanac bridge (firm-level only — no names leave this machine) ───────────

def sync_almanac(people: list[dict]) -> str:
    """Update Almanac's applications.yaml with firm-level networking progress.

    Writes only counts ("3 talked to, 1 referral candidate"), never a person, because
    Almanac's site is reachable by URL.
    """
    import yaml
    path = ALMANAC / "config" / "applications.yaml"
    if not path.exists():
        return "Almanac not found"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    apps = doc.get("applications") or []
    a = analytics(people)
    changed = 0
    for firm, c in a["firms"].items():
        talked = sum(c.get(s, 0) for s in ("call_scheduled", "call_done", "referral_asked", "referred"))
        reached = sum(c.get(s, 0) for s in STAGES if s != "new")
        if not reached:
            continue
        note = f"Network: {reached} messaged, {talked} talked to, {c.get('referred', 0)} referred"
        row = next((x for x in apps if firm_of(x.get("org", "")) == firm), None)
        if row is None:
            apps.append({"org": firm, "name": "Networking", "stage": "Networking",
                         "updated": date.today().isoformat(), "note": note})
            changed += 1
        elif row.get("note") != note:
            row["note"] = note
            row["updated"] = date.today().isoformat()
            if row.get("stage") == "Interested":
                row["stage"] = "Networking"
            changed += 1
    if changed:
        header = "".join(l + "\n" for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("#"))
        path.write_text(header + yaml.safe_dump({"applications": apps}, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")
    return f"{changed} firm(s) updated in Almanac"


def public(p: dict) -> dict:
    """What the UI needs (drops nothing sensitive — it's local-only anyway)."""
    return {k: p[k] for k in ("id", "name", "first", "role", "org", "firm", "email", "linkedin",
                              "connected", "stage", "last", "target", "thread", "events", "debrief")}
