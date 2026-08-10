"""Read a LinkedIn data export folder and build the 'who you are' profile from it.

Everything here stays on your machine. Nothing in the export is uploaded, and
none of it is written anywhere except your local config overlay.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

YEAR_NAMES = ["first-year", "sophomore", "junior", "senior"]
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    # LinkedIn prefixes some files with a "Notes:" preamble and a quoted sentence.
    # The header is the first line that is neither. Single-column files (Skills.csv)
    # have no comma at all, so don't require one.
    start = 0
    for i, line in enumerate(raw[:15]):
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("notes") or stripped.startswith('"'):
            continue
        start = i
        break
    try:
        return list(csv.DictReader(io.StringIO("\n".join(raw[start:]))))
    except csv.Error:
        return []


def _parse_month_year(text: str) -> date | None:
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{4})", text or "")
    if not m:
        m2 = re.search(r"\b(\d{4})\b", text or "")
        return date(int(m2.group(1)), 6, 1) if m2 else None
    return date(int(m.group(2)), MONTHS.get(m.group(1), 6), 1)


def find_export(start: str | Path | None = None) -> str:
    """Locate a LinkedIn export folder (one containing Profile.csv)."""
    if start:
        p = Path(start).expanduser()
        if (p / "Profile.csv").exists():
            return str(p)
    roots = [Path(p).expanduser() for p in
             ("~/OneDrive/Desktop", "~/Desktop", "~/Downloads", "~/Documents")]
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.glob("**/Profile.csv"):
            return str(candidate.parent)
    return ""


def read_export(folder: str | Path) -> dict:
    """Pull the structured facts out of the export. No guessing, no invention."""
    f = Path(folder).expanduser()
    profile = (_read(f / "Profile.csv") or [{}])[0]
    education = _read(f / "Education.csv")
    positions = _read(f / "Positions.csv")
    skills = [r.get("Name", "") for r in _read(f / "Skills.csv") if r.get("Name")]
    languages = _read(f / "Languages.csv")
    emails = _read(f / "Email Addresses.csv")
    resumes = [r.get("Private Identity Asset Raw Text", "")
               for r in _read(f / "Private_identity_asset.csv")]

    degree = None
    for row in education:
        start = _parse_month_year(row.get("Start Date", ""))
        end = _parse_month_year(row.get("End Date", ""))
        if end and end >= date.today() and start:
            if degree is None or start < degree["start"]:
                degree = {"school": row.get("School Name", ""), "start": start,
                          "end": end, "notes": row.get("Notes", ""),
                          "degree": row.get("Degree Name", "")}
    if degree is None and education:
        row = education[0]
        degree = {"school": row.get("School Name", ""),
                  "start": _parse_month_year(row.get("Start Date", "")) or date.today(),
                  "end": _parse_month_year(row.get("End Date", "")) or date.today(),
                  "notes": row.get("Notes", ""), "degree": row.get("Degree Name", "")}

    current, past = [], []
    for row in positions:
        entry = {"org": row.get("Company Name", ""), "role": row.get("Title", ""),
                 "desc": " ".join((row.get("Description") or "").split()),
                 "start": _parse_month_year(row.get("Started On", "")),
                 "end": _parse_month_year(row.get("Finished On", ""))}
        (current if not row.get("Finished On") else past).append(entry)
    current.sort(key=lambda e: e["start"] or date.min, reverse=True)
    past.sort(key=lambda e: e["end"] or date.min, reverse=True)

    return {
        "first_name": profile.get("First Name", ""),
        "last_name": profile.get("Last Name", ""),
        "headline": profile.get("Headline", ""),
        "summary": " ".join((profile.get("Summary") or "").split()),
        "website": (profile.get("Websites") or "").strip("[]").split(":")[-1].strip("]"),
        "linkedin_email": (emails[0].get("Email Address", "") if emails else ""),
        "degree": degree or {},
        "current_roles": current,
        "past_roles": past,
        "skills": skills,
        "languages": [(r.get("Name", ""), r.get("Proficiency", "")) for r in languages],
        "resume_text": max(resumes, key=len) if resumes else "",
    }


def school_year(degree: dict, today: date | None = None) -> str:
    start = degree.get("start")
    if not start:
        return "student"
    today = today or date.today()
    elapsed = (today.year - start.year) + (1 if today.month >= 8 else 0)
    idx = max(0, min(len(YEAR_NAMES) - 1, elapsed - (1 if today.month >= 8 else 0)))
    return YEAR_NAMES[idx]


def _major(facts: dict) -> str:
    text = facts.get("resume_text") or facts.get("headline") or ""
    m = re.search(r"Bachelor of (?:Arts|Science) in ([A-Za-z&,\s]+?)(?:\||\(|$|\n)", text)
    if m:
        return " ".join(m.group(1).split()).rstrip(" ,").lower()
    m = re.search(r"(Mathematical Economics[^|\n]*)", text)
    return " ".join(m.group(1).split()).lower() if m else ""


def _short_school(name: str) -> str:
    name = name.replace("The ", "")
    if "University of Pennsylvania" in name:
        return "Penn"
    return re.sub(r"\s*(University|College|School)\s*$", "", name).strip() or name


def suggest_background(facts: dict) -> str:
    """A first draft he edits — deliberately concrete, no adjectives about himself."""
    bits: list[str] = []

    # Resume columns are separated by runs of spaces, so stop at the first one —
    # otherwise the coursework list runs straight into the next resume section.
    coursework = ""
    for source in (facts.get("degree", {}).get("notes", ""), facts.get("resume_text", "")):
        m = re.search(r"Coursework:?\s*(.{10,180}?)(?:\s{2,}|\n|\|)", source or "")
        if m:
            coursework = " ".join(m.group(1).split()).rstrip(" ,.")
            break
    if coursework:
        bits.append(f"Coursework so far includes {coursework}")

    tech = [s for s in facts.get("skills", []) if s.lower() in
            {"sql", "python", "stata", "r", "excel", "econometrics",
             "statistical data analysis", "data science"}]
    if tech:
        bits.append("I work in " + ", ".join(dict.fromkeys(tech[:4])))

    # A research/analyst TITLE is a much stronger credential than a description that
    # merely mentions research, so rank title matches first.
    roles = facts.get("current_roles", []) + facts.get("past_roles", [])
    pattern = re.compile(r"research|analyst|econom|quantitat", re.I)
    research = sorted(
        [r for r in roles if pattern.search(r["role"] + " " + r["desc"])],
        key=lambda r: 0 if pattern.search(r["role"]) else 1)
    if research:
        r = research[0]
        detail = re.split(r"\s{2,}|;", r["desc"])[0][:140].rstrip(" ,.:") if r["desc"] else ""
        who = re.sub(r"\s*\((.*?)\)\s*$", "", r["role"]).strip()
        under = re.search(r"\(([^)]*Professor[^)]*)\)", r["role"])
        line = f"I've worked as a {who} at {r['org']}"
        if under:
            line += f" under {under.group(1)}"
        if detail:
            line += f", {detail[0].lower() + detail[1:]}"
        bits.append(line)

    return ". ".join(bits) + "." if bits else ""


def to_profile(facts: dict, preferred_email: str = "") -> dict:
    degree = facts.get("degree", {})
    school = _short_school(degree.get("school", ""))
    name = " ".join(x for x in [facts.get("first_name", ""), facts.get("last_name", "")] if x)

    email = preferred_email
    if not email:
        m = re.search(r"[\w.\-]+@[\w.\-]+\.edu", facts.get("resume_text", ""))
        email = m.group(0) if m else facts.get("linkedin_email", "")

    return {
        "name": name,
        "first": facts.get("first_name", ""),
        "email": email,
        "year": school_year(degree),
        "institution": school,
        "major": _major(facts),
        "background": suggest_background(facts),
        "signature_line": f"{degree.get('school', school)} | {email}" if email else school,
    }


def summarize(facts: dict) -> list[str]:
    d = facts.get("degree", {})
    out = [f"Name: {facts.get('first_name')} {facts.get('last_name')}",
           f"School: {d.get('school', '?')} ({school_year(d)})",
           f"Current roles: {len(facts.get('current_roles', []))}",
           f"Past roles: {len(facts.get('past_roles', []))}",
           f"Skills listed: {len(facts.get('skills', []))}"]
    if facts.get("resume_text"):
        out.append(f"Resume text found: {len(facts['resume_text'].split())} words")
    return out
