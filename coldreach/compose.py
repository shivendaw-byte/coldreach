"""Draft composition + the deliverability linter."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, timedelta
from pathlib import Path

from .store import max_similarity

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"

SPAM_TERMS = [
    "act now", "limited time", "risk free", "risk-free", "100% free", "click here",
    "guarantee", "guaranteed", "no obligation", "special promotion", "dear friend",
    "opportunity of a lifetime", "urgent", "congratulations", "winner", "cash bonus",
    "make money", "unsubscribe", "this is not spam", "call now", "order now",
]
TRACKER_MARKERS = ["<img", "track.", "click.", "bit.ly", "tinyurl", "utm_source",
                   "mailtrack", "1x1.gif", "open.php", "pixel"]
URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def load_template(name: str) -> tuple[str, str]:
    path = TEMPLATES / f"{name}.txt"
    if not path.exists():
        raise SystemExit(f"No template '{name}'. Available: "
                         f"{[p.stem for p in TEMPLATES.glob('*.txt')]}")
    raw = path.read_text(encoding="utf-8-sig").lstrip("﻿")
    subject_line, body = raw.split("\n", 1)
    return subject_line.replace("Subject:", "", 1).strip(), body.strip()


def fit_subject(subject: str, cap: int = 62) -> str:
    subject = " ".join(subject.split()).rstrip(" ,.;:-")
    if len(subject) <= cap:
        return subject
    out: list[str] = []
    for word in subject.split():
        if len(" ".join(out + [word])) > cap:
            break
        out.append(word)
    return (" ".join(out) or subject[:cap]).rstrip(" ,.;:-")


JOURNALISH = re.compile(
    r"\b(journal|review|econometrica|quarterly|proceedings|annals|studies|"
    r"letters|science|nature|working paper|nber|ssrn|forthcoming|press|mimeo)\b", re.I)
PROSE_MARKERS = re.compile(
    r"\b(he |she |his |her |received|earned|joined|serves as|teaches|"
    r"graduated|prior to|before joining)\b", re.I)


def _looks_like_journal(chunk: str) -> bool:
    words = chunk.split()
    if not 0 < len(words) <= 8:
        return False
    if JOURNALISH.search(chunk):
        return True
    caps = sum(1 for w in words if w[:1].isupper())
    return caps >= max(1, len(words) - 2)


def _clean_paper(raw: str) -> str:
    txt = re.sub(r"^\(?\s*(19|20)\d{2}[a-z]?\s*\)?[\s,.:;\-–—]*", "", raw.strip())
    m = re.search(r'["“](.{10,}?)["”]', txt)
    if m:
        return " ".join(m.group(1).split()).rstrip(" ,.;")
    txt = re.split(r"\s+[-–—]\s+|\s*\|\s*", txt)[0]
    txt = re.sub(r"\s*\((19|20)\d{2}[a-z]?\).*$", "", txt)
    txt = re.split(r"\s*\(\s*\)|,\s*\d+\s*\(|\bpp\.\s|\bvol\.\s", txt)[0]
    parts = [p.strip() for p in txt.split(",") if p.strip()]
    while len(parts) > 1 and _looks_like_journal(parts[-1]):
        parts.pop()
    return " ".join(", ".join(parts).split())[:140].rstrip(" ,.;")


def best_signal(contact: dict) -> str:
    scored = []
    for p in (contact.get("signals") or contact.get("papers") or "").split(" | "):
        if not p.strip():
            continue
        yr = max((int(y) for y in re.findall(r"(?:19|20)\d{2}", p)), default=0)
        scored.append((yr, _clean_paper(p)))
    scored.sort(reverse=True)
    for _, title in scored:
        if len(title) < 15 or len(title) > 140:
            continue
        if PROSE_MARKERS.search(title) or title.count(" ") < 2:
            continue
        return title
    return ""


def shorten(text: str, max_chars: int = 42) -> str:
    """Trim an anchor to something that fits in a subject line."""
    text = " ".join(text.split()).rstrip(" ,.;:")
    text = re.sub(r"^(the|a|an|on|evidence from)\s+", "", text, flags=re.I)
    if len(text) <= max_chars:
        return text
    out = []
    for word in text.split():
        if len(" ".join(out + [word])) > max_chars:
            break
        out.append(word)
    return " ".join(out) or text[:max_chars]


def _interest_phrase(contact: dict) -> str:
    raw = (contact.get("focus") or contact.get("interests") or "").strip(" .")
    if not raw:
        return ""
    parts = [p.strip() for p in re.split(r"[,;]| and ", raw) if 3 < len(p.strip()) < 60]
    return parts[0].lower() if parts else raw[:60].lower()


def meeting_date(days_out: int = 8) -> str:
    d = date.today() + timedelta(days=days_out)
    while d.weekday() > 3:            # land Mon-Thu
        d += timedelta(days=1)
    return f"{d:%A}, {d:%B} {d.day}"


# Only usable when the person has a real focus area — "work on associate" is nonsense.
FOCUS_HOOKS = [
    "I've been following what {org} is doing, and you're the person there whose "
    "work on {focus} lines up with what I'm trying to learn.",
    "I've been reading about {org} for a while, and the {focus} side of it is where "
    "I have the most questions.",
]
ROLE_HOOKS = [
    "You came up when I was digging into {org}, and what you do as {role_article} is "
    "close to the problem I've been trying to understand properly.",
    "I've been reading about {org} for a while, and your side of it — the "
    "{role_lower} side — is the part I have the most questions about.",
]
ORG_HOOKS = [
    "I've been following {org} for a while and wanted to write to someone actually "
    "doing the work rather than send a form into the void.",
    "{org} keeps coming up in what I read, and you're on the side of it I'm most "
    "curious about.",
]
WARM_HOOKS = [
    "We're connected on LinkedIn but have never actually talked, and that seems "
    "like a waste given you're at {org}.",
    "We connected on LinkedIn a while back — I've been watching what you're doing "
    "at {org} since, and wanted to actually reach out.",
]
PAPER_HOOKS = [
    'I read "{paper}" last week and it is the closest thing I have found to the '
    'question I keep circling back to.',
    'Your paper "{paper}" is what prompted this email — I read it twice and I am '
    'still turning over the identification strategy.',
    'I came to your work through "{paper}", and it reframed something I had been '
    'thinking about badly.',
    'I spent a while with "{paper}" and it is the first thing I have read that '
    'takes the question seriously rather than gesturing at it.',
]
INTEREST_HOOKS = [
    "Your work on {interest} is why I am writing — it lines up almost exactly with "
    "what I have been reading on my own this year.",
    "I have been reading around {interest} for a few months, and your name kept "
    "showing up in the papers I found most useful.",
    "{interest_cap} is the area I have been trying to get properly oriented in, and "
    "your work is where I keep landing.",
]


def _pick(value, seed: str):
    """Config fields may be a single string or a list of variants."""
    if isinstance(value, (list, tuple)) and value:
        return value[int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(value)]
    return value or ""


def build_slots(contact: dict, me: dict, campaign: dict) -> dict:
    signal = best_signal(contact)
    interest = _interest_phrase(contact)
    seed = (contact.get("email") or contact.get("linkedin")
            or contact.get("name") or "x").lower()
    org = contact.get("org", "")
    role = contact.get("role", "")
    audience = campaign.get("audience") or contact.get("audience") or "academic"

    # Lowercase the whole role for mid-sentence use, but leave acronyms (VP, PM) alone.
    role_lower = " ".join(w if len(w) > 1 and w.isupper() else w.lower()
                          for w in role.split())
    ctx = {"paper": signal, "interest": interest,
           "interest_cap": interest[:1].upper() + interest[1:] if interest else "",
           "org": org or "your team", "role": role,
           "role_lower": role_lower or "your work",
           "role_article": (("an " if role_lower[:1].lower() in "aeiou" else "a ") + role_lower)
                           if role_lower else "your work",
           "focus": interest}

    if signal:
        hook, anchor = _pick(PAPER_HOOKS, seed).format(**ctx), signal
    elif audience == "warm" and org:
        hook, anchor = _pick(WARM_HOOKS, seed + "w").format(**ctx), org
    elif interest and audience == "academic":
        hook, anchor = _pick(INTEREST_HOOKS, seed + "i").format(**ctx), interest
    elif interest and org:
        hook, anchor = _pick(FOCUS_HOOKS, seed + "x").format(**ctx), interest
    elif role and org:
        hook, anchor = _pick(ROLE_HOOKS, seed + "r").format(**ctx), f"{role} at {org}"
    elif org:
        hook, anchor = _pick(ORG_HOOKS, seed + "o").format(**ctx), org
    else:
        hook = ("I came across your work and wanted to write to you directly "
                "rather than send something generic.")
        anchor = contact.get("team", "")

    fit = _pick(campaign.get("fit"), seed + "f").format(**me)
    ask = _pick(campaign.get("ask"), seed + "a").format(
        meeting_date=meeting_date(campaign.get("meeting_days_out", 8)),
        org=org or "your team", **me)

    parts = (contact.get("name") or "").split()
    slots = {
        "last_name": contact.get("last_name") or (parts[-1] if parts else "there"),
        "first_name": contact.get("first_name") or (parts[0] if parts else "there"),
        "name": contact.get("name", ""),
        "greeting_name": (contact.get("last_name") or (parts[-1] if parts else "there"))
                         if audience == "academic"
                         else (contact.get("first_name") or (parts[0] if parts else "there")),
        "org": org,
        "team": contact.get("team", ""),
        "role": role,
        "signal": signal,
        "paper": signal,
        "interest": interest,
        "anchor": anchor,
        # anchor drives the specificity check; anchor_short goes in subject lines,
        # so it must never repeat the org a subject template already names.
        "anchor_short": shorten(signal or interest or role or org) or "your work",
        "salutation": _pick(campaign.get("salutation") or (
            "Dear Professor {last_name}," if audience == "academic" else "Hi {first_name},"),
            seed + "g"),
        "signoff": _pick(campaign.get("signoff") or "Best", seed + "z"),
        "audience": audience,
        "hook": hook,
        "fit": fit,
        "ask": ask,
        "meeting_date": meeting_date(campaign.get("meeting_days_out", 8)),
        **me,
    }
    slots["salutation"] = slots["salutation"].format(**slots)
    return slots


STANDARD_BODY = """{salutation}

{hook}

{fit}

{ask}

{signoff},
{name}
{signature_line}"""


def render_template(campaign_name: str, campaign: dict, slots: dict,
                    seed: str) -> tuple[str, str]:
    """Campaign config drives everything; a templates/<name>.txt file overrides."""
    path = TEMPLATES / f"{campaign_name}.txt"
    if path.exists():
        subject_tpl, body_tpl = load_template(campaign_name)
    else:
        subject_tpl = _pick(campaign.get("subject") or "{anchor_short}", seed + "s")
        body_tpl = STANDARD_BODY

    subject = fit_subject(subject_tpl.format(**slots))
    body = re.sub(r"\n{3,}", "\n\n", body_tpl.format(**slots)).strip()
    return subject, body


LLM_SYSTEM = """You write short cold emails on behalf of a college student. The
recipient may be a professor, a founder, a consultant, a product manager, or an
existing LinkedIn connection — match the register to whoever it is.

Hard rules — every one is non-negotiable:
- Plain text only. No markdown, no HTML, no bullet lists, no em dashes as decoration.
- 110-170 words in the body, not counting the greeting or signature.
- Zero links. Zero attachments. Never mention an attachment.
- Open with something specific and verifiable about THIS person. Never open with
  "I hope this email finds you well" or any variant.
- Use "Dear Professor X," for academics and "Hi <first name>," for everyone else.
- One clear ask, and it must be the ask you are given. Do not invent a different one.
- No flattery inflation ("groundbreaking", "world-renowned", "brilliant").
- No sales register: no "reach out", "circle back", "touch base", "synergy",
  "opportunity of a lifetime", "I'd love to pick your brain".
- Include a graceful out ("no worries at all if you're not taking students").
- Sound like a sharp 18-year-old who read the paper, not like a template.
- Vary sentence structure and opening from anything you have written before.

Return exactly two lines of output:
SUBJECT: <subject line, under 60 characters, lowercase-ish, no exclamation marks>
---
<body, starting with "Dear Professor X," and ending with the sender's first and last name>"""


def llm_compose(contact: dict, me: dict, campaign: dict, slots: dict) -> tuple[str, str] | None:
    try:
        import anthropic
    except ImportError:
        print("  [llm] `pip install anthropic` to use --llm; using template")
        return None
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        print("  [llm] ANTHROPIC_API_KEY not set; using template")
        return None

    prompt = f"""RECIPIENT
Name: {contact.get('name')}
Role: {contact.get('role') or '(unknown)'}
Organization / team: {contact.get('org') or '(unknown)'} / {contact.get('team') or '-'}
Focus areas: {contact.get('focus') or '(not listed)'}
Recent work or signals: {contact.get('signals') or '(not listed)'}
Audience type: {slots.get('audience')}  (academic = professor; work = industry; warm = existing LinkedIn connection)

SENDER
{me.get('name')}, {me.get('year')} at {me.get('institution')}, {me.get('major')}.
Background: {me.get('background')}
Why this person: {slots['anchor'] or 'organization fit'}

THE ASK (use this exact ask, adapted to natural prose)
{campaign.get('ask', '').format(meeting_date=slots['meeting_date'])}

Write the email."""

    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model="claude-opus-5",
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=LLM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"  [llm] {type(exc).__name__}: {exc}; using template")
        return None

    if resp.stop_reason == "refusal":
        print("  [llm] model declined; using template")
        return None

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if "---" not in text:
        return None
    head, body = text.split("---", 1)
    subject = head.replace("SUBJECT:", "", 1).strip()
    return subject, body.strip()


def lint(subject: str, body: str, contact: dict, slots: dict,
         prior_bodies: list[str], sim_threshold: float = 0.60) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    low = body.lower()
    words = len(body.split())

    if len(subject) > 65:
        issues.append(("error", f"subject is {len(subject)} chars (keep under 65)"))
    if "!" in subject:
        issues.append(("error", "exclamation mark in subject"))
    if EMOJI_RE.search(subject) or EMOJI_RE.search(body):
        issues.append(("error", "emoji present"))
    if re.match(r"^\s*(re|fwd)\s*:", subject, re.I):
        issues.append(("error", "fake Re:/Fwd: prefix — a classic spam signal"))
    for word in subject.split():
        alpha = re.sub(r"[^A-Za-z]", "", word)
        if len(alpha) > 3 and alpha.isupper():
            issues.append(("warn", f"ALL-CAPS word in subject: {word}"))
            break

    if words < 85:
        issues.append(("warn", f"body is {words} words (thin; aim 110-170)"))
    if words > 210:
        issues.append(("error", f"body is {words} words (too long; aim 110-170)"))

    links = URL_RE.findall(body)
    if len(links) > 1:
        issues.append(("error", f"{len(links)} links — first contact should have 0 or 1"))
    for marker in TRACKER_MARKERS:
        if marker in low:
            issues.append(("error", f"tracking/redirect marker '{marker}' present"))
    for term in SPAM_TERMS:
        if term in low:
            issues.append(("error", f"spam-filter trigger phrase: '{term}'"))
    if re.search(r"\battach(ed|ment)\b", low):
        issues.append(("error", "mentions an attachment — do not attach on first contact"))
    if "i hope this email finds you well" in low:
        issues.append(("warn", "opens with the most-templated sentence in existence"))
    if "<" in body and ">" in body and re.search(r"<[a-z/][^>]*>", low):
        issues.append(("error", "HTML markup detected — send plain text"))

    anchor = (slots.get("anchor") or "").lower()
    if anchor:
        tokens = [t for t in re.findall(r"[a-z]{4,}", anchor)][:5]
        if tokens and not any(t in low for t in tokens):
            issues.append(("error", "nothing specific to this person in the body — reads as a blast"))
    else:
        issues.append(("warn", "no signal, focus, or org found for this person; personalization is weak"))
    if not slots.get("signal") and not slots.get("interest"):
        issues.append(("warn", "anchored only on job title/company — add a real detail "
                               "before sending, or this is generic"))

    sim = max_similarity(body, prior_bodies)
    if sim >= sim_threshold:
        issues.append(("error", f"{sim:.0%} similar to a previous draft — rewrite or it "
                                f"fingerprints as bulk mail"))
    elif sim >= sim_threshold - 0.15:
        issues.append(("warn", f"{sim:.0%} similar to a previous draft"))

    return issues


def compose_one(contact: dict, me: dict, campaign: dict, campaign_name: str,
                prior_bodies: list[str], use_llm: bool,
                sim_threshold: float = 0.60) -> dict:
    slots = build_slots(contact, me, campaign)
    seed = (contact.get("email") or contact.get("linkedin")
            or contact.get("name") or "x").lower()
    subject = body = ""
    engine = "template"

    if use_llm:
        out = llm_compose(contact, me, campaign, slots)
        if out:
            subject, body = fit_subject(out[0]), out[1]
            engine = "claude-opus-5"
    if not body:
        subject, body = render_template(campaign_name, campaign, slots, seed)

    issues = lint(subject, body, contact, slots, prior_bodies, sim_threshold)
    return {
        "email": contact.get("email", ""),
        "name": contact.get("name", ""),
        "org": contact.get("org", ""),
        "role": contact.get("role", ""),
        "campaign": campaign_name,
        "subject": subject,
        "body": body,
        "engine": engine,
        "anchor": slots.get("anchor", ""),
        "issues": [f"{lvl}: {msg}" for lvl, msg in issues],
        "blocked": any(lvl == "error" for lvl, _ in issues),
        "pushed": False,
    }
