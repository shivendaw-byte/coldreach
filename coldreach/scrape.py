"""Faculty directory scraping. Only collects emails the institution publishes."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import net
from .store import now

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.(?:edu|org|com|net|ac\.[a-z]{2})")
OBFUSCATED = [
    (re.compile(r"([A-Za-z0-9._%+\-]+)\s*[\[\(]?\s*at\s*[\]\)]?\s*([A-Za-z0-9.\-]+)\s*[\[\(]?\s*dot\s*[\]\)]?\s*([a-z]{2,4})", re.I), r"\1@\2.\3"),
    (re.compile(r"([A-Za-z0-9._%+\-]+)\s*[\[\(]\s*at\s*[\]\)]\s*([A-Za-z0-9.\-]+\.[a-z]{2,6})", re.I), r"\1@\2"),
]
SKIP_LOCALPARTS = {"info", "contact", "admin", "webmaster", "support", "help",
                   "noreply", "no-reply", "office", "admissions", "media", "press"}
ROLE_ADDRESS = re.compile(
    r"(^|[.\-_])(ugrad|undergrad|grad|gradadmin|dept|department|general|inquir|"
    r"enquir|reception|main|hr|help|info|contact|admin|office|admissions|apply|"
    r"jobs|careers|alumni|events|comms|communications|news|media|press|webmaster|"
    r"support|noreply|no-reply|team|group|seminar|program|staff|faculty|students?)"
    r"([.\-_]|$)", re.I)

PROFILE_HINTS = ("/profile/", "/people/", "/faculty/", "/directory/", "/person/", "/~")
NON_PERSON_SLUG = re.compile(
    r"award|position|news|seminar|event|contact|overview|index|list|directory|"
    r"recruit|program|course|publication|calendar|alumni|student|staff|search|"
    r"login|apply|about|resource|conference|workshop|center|department|admission|"
    r"job-market|placement|emeriti|adjunct-|affiliate|visiting-|all-|browse|"
    r"postdoc|fellows|lecturers|instructors|associates|candidates|visitors", re.I)
NON_PERSON_NAME = re.compile(
    r"\b(faculty|awards?|positions?|news|research|seminars?|events?|directory|"
    r"profiles?|people|department|program|overview|contact|home|publications?|"
    r"center|school|admissions?|apply|search|postdoctoral|fellows|lecturers|"
    r"instructors|associates|candidates|visitors|emeriti|staff|standing|"
    r"find|experts?|view|browse|explore|learn|more|join|team|list)\b", re.I)
PUB_HEADINGS = re.compile(r"^(research|publications?|working papers?|papers|"
                          r"selected publications?|selected works?)\b", re.I)
YEAR_MARK = re.compile(r"\(\s*(?:19|20)\d{2}[a-z]?\s*\)")
CITE_NOISE = re.compile(
    r"Continue Reading|Read More|Download|Working Paper Version|View Abstract|"
    r"Related Links?|Show More|\[PDF\]", re.I)
BIO_MARKERS = re.compile(
    r"\b(he |she |his |her |received|earned|joined|serves as|prior to|"
    r"before joining|teaches|currently|graduated|holds a|award|fellowship)\b", re.I)
CITATION_START = re.compile(r"^\(?\s*(19|20)\d{2}\s*\)?[\s,.:;\-–—]")
TITLE_RE = re.compile(
    r"\b((?:Assistant |Associate |Visiting |Adjunct |Emerit\w+ |Clinical |Practice )?"
    r"Professor(?: of [A-Za-z ,&]+)?|Lecturer|Senior Fellow|Dean)\b")


def email_matches_name(addr: str, name: str) -> bool:
    """Guard against attaching a department's shared inbox to an individual.

    A published faculty address nearly always echoes the person's name
    (anagol@, sberkou@, judd.kessler@, harrij@). An address that echoes nothing
    is far more likely to be a general inbox than a personal alias, and mailing
    the wrong inbox is worse than having no address at all.
    """
    local = addr.split("@")[0].lower()
    if ROLE_ADDRESS.search(local):
        return False
    tokens = [t.lower() for t in re.split(r"[\s.'\-]+", name) if len(t) > 1]
    if not tokens:
        return False
    first, last = tokens[0], tokens[-1]
    stripped = re.sub(r"[^a-z]", "", local)
    candidates = {first, last, first[:1] + last, last + first[:1],
                  first[:4], last[:5], first[:1] + last[:5]}
    if any(c and c in stripped for c in candidates):
        return True
    return any(len(t) > 3 and t[:4] in stripped for t in tokens)


def looks_like_person(name: str) -> bool:
    """Reject nav pages, section headers, and anything that isn't a human name."""
    name = " ".join(name.split())
    if not (4 < len(name) < 60) or NON_PERSON_NAME.search(name):
        return False
    tokens = [t for t in re.split(r"[\s.]+", name) if t]
    if not 2 <= len(tokens) <= 5:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    capitalized = sum(1 for t in tokens if t[:1].isupper())
    return capitalized >= 2


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def find_email(soup: BeautifulSoup, html: str) -> str:
    for a in soup.select('a[href^="mailto:"]'):
        addr = a["href"].split("mailto:", 1)[1].split("?")[0].strip()
        if "@" in addr and addr.split("@")[0].lower() not in SKIP_LOCALPARTS:
            return addr.lower()
    text = soup.get_text(" ", strip=True)
    for pattern, repl in OBFUSCATED:
        text = pattern.sub(repl, text)
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0).lower()
        if addr.split("@")[0] not in SKIP_LOCALPARTS:
            return addr
    return ""


def find_name(soup: BeautifulSoup, url: str) -> str:
    for sel in ("h1", ".profile-name", ".field--name-title", "h2.name"):
        el = soup.select_one(sel)
        if el:
            txt = " ".join(el.get_text(" ", strip=True).split())
            txt = re.split(r"\s*[|,•]\s*", txt)[0]
            if 3 < len(txt) < 60 and not txt.lower().startswith(("faculty", "people")):
                return txt
    if soup.title:
        return re.split(r"\s*[|–-]\s*", soup.title.get_text(strip=True))[0]
    return urlparse(url).path.rstrip("/").split("/")[-1].replace("-", " ").title()


def find_title(soup: BeautifulSoup) -> str:
    m = TITLE_RE.search(soup.get_text(" ", strip=True))
    return m.group(1).strip() if m else ""


def find_interests(soup: BeautifulSoup) -> str:
    text = soup.get_text("\n", strip=True)
    m = re.search(r"(?:Research Interests?|Areas? of (?:Research|Expertise)|Research Areas?)"
                  r"\s*:?\s*\n?\s*([^\n]{5,300})", text, re.I)
    if m:
        val = " ".join(m.group(1).split()).strip(" :;.")
        if val.lower() not in ("links", "overview", "research"):
            return val[:280]
    return ""


def is_citation(txt: str) -> bool:
    """A publication line, not bio prose and not a news blurb."""
    if not (25 < len(txt) < 300):
        return False
    if len(BIO_MARKERS.findall(txt)) >= 2:
        return False
    quoted = re.search(r'["“].{12,}?["”]', txt)
    year = re.search(r"\(\s*(19|20)\d{2}[a-z]?\s*\)", txt)
    return bool(CITATION_START.match(txt) or (quoted and year))


def _section_text(heading, max_chars: int = 14000) -> str:
    from bs4 import NavigableString
    buf, size = [], 0
    for el in heading.next_elements:
        if getattr(el, "name", None) in ("h1", "h2", "h3", "h4"):
            break
        if isinstance(el, NavigableString):
            s = str(el).strip()
            if s:
                buf.append(s)
                size += len(s)
                if size > max_chars:
                    break
    return " ".join(buf)


def citations_from_text(text: str, limit: int) -> list[str]:
    """Split a publications blob into per-citation strings on its (YEAR) markers."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"Abstract\s*:.*?(?=" + YEAR_MARK.pattern + r"|$)", " ", text)
    marks = list(YEAR_MARK.finditer(text))
    out: list[str] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        chunk = CITE_NOISE.split(text[m.start():end])[0]
        chunk = " ".join(chunk.split()).strip(" ,.;")[:300]
        if len(chunk) > 30 and chunk not in out:
            out.append(chunk)
        if len(out) >= limit:
            break
    return out


def find_papers(soup: BeautifulSoup, limit: int = 6) -> list[str]:
    papers: list[str] = []
    for h in soup.find_all(["h2", "h3", "h4"]):
        if not PUB_HEADINGS.match(h.get_text(" ", strip=True).strip()):
            continue
        for cite in citations_from_text(_section_text(h), limit):
            if cite not in papers:
                papers.append(cite)
            if len(papers) >= limit:
                return papers
    if papers:
        return papers

    for el in soup.find_all(["li", "p"], limit=250):
        txt = " ".join(el.get_text(" ", strip=True).split())
        if is_citation(txt) and txt not in papers:
            papers.append(txt)
        if len(papers) >= limit:
            break
    return papers


def find_site(soup: BeautifulSoup, url: str) -> str:
    host = urlparse(url).netloc
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = a.get_text(" ", strip=True).lower()
        if not href.startswith("http"):
            continue
        if urlparse(href).netloc == host:
            continue
        if any(k in label for k in ("personal page", "personal website", "homepage",
                                    "website", "google sites", "cv")):
            return href
        if "sites.google.com" in href or re.search(r"/~", href):
            return href
    return ""


def find_linkedin(soup: BeautifulSoup) -> str:
    for a in soup.find_all("a", href=True):
        if "linkedin.com/in/" in a["href"]:
            return a["href"].split("?")[0]
    return ""


def parse_profile(url: str, org: str, team: str, delay: float,
                  audience: str = "academic", follow_site: bool = True) -> dict | None:
    html = net.get(url, delay=delay)
    if not html:
        return None
    soup = _soup(html)
    name = find_name(soup, url)
    email = find_email(soup, html)
    site = find_site(soup, url)

    if not email and follow_site and site:
        alt = net.get(site, delay=delay)
        if alt:
            email = find_email(_soup(alt), alt)

    note = ""
    if email and not email_matches_name(email, name):
        note = f"discarded non-matching address {email} (likely a shared inbox)"
        email = ""

    parts = name.replace(",", " ").split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""

    return {
        "email": email,
        "name": name,
        "first_name": first,
        "last_name": last,
        "role": find_title(soup),
        "team": team,
        "org": org,
        "focus": find_interests(soup),
        "signals": " | ".join(find_papers(soup)),
        "site": site,
        "linkedin": find_linkedin(soup),
        "profile_url": url,
        "source": urlparse(url).netloc,
        "source_kind": "directory",
        "audience": audience,
        "scraped_at": now(),
        "status": "new" if email else "no_published_email",
        "notes": note,
    }


def profile_links(directory_url: str, delay: float) -> list[str]:
    html = net.get(directory_url, delay=delay)
    if not html:
        return []
    soup = _soup(html)
    host = urlparse(directory_url).netloc
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(directory_url, a["href"].split("#")[0].rstrip("/"))
        if urlparse(href).netloc != host or href in seen:
            continue
        path = urlparse(href).path
        if not any(h in path for h in PROFILE_HINTS):
            continue
        tail = path.rstrip("/").split("/")[-1]
        if not tail or tail in ("profile", "people", "faculty", "directory",
                                "faculty-list", "person"):
            continue
        if len(tail) < 2 or tail.isdigit() or NON_PERSON_SLUG.search(tail):
            continue
        seen.add(href)
        out.append(href)
    return out


def scrape_directory(directory_url: str, org: str, team: str, limit: int = 0,
                     delay: float = 2.0, audience: str = "academic",
                     log=print) -> list[dict]:
    links = profile_links(directory_url, delay)
    if limit:
        links = links[:limit]
    log(f"Found {len(links)} profile link(s) at {directory_url}")
    rows = []
    for i, link in enumerate(links, 1):
        row = parse_profile(link, org, team, delay, audience)
        if not row or not looks_like_person(row["name"]):
            continue
        flag = row["email"] or "(no published email)"
        log(f"[{i}/{len(links)}] {row['name']} — {flag}")
        rows.append(row)
    return rows


def scrape_source(src: dict, limit: int = 0, delay: float = 2.0,
                  log=print) -> list[dict]:
    rows: list[dict] = []
    for url in src.get("directories", []):
        rows += scrape_directory(url, src.get("org", src.get("school", "")),
                                 src.get("team", src.get("dept", "")),
                                 limit, delay, src.get("audience", "academic"), log)
        if limit and len(rows) >= limit:
            break
    return rows[:limit] if limit else rows
