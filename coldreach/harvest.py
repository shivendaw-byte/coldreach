"""Pull text, contacts, and research hooks out of local documents.

Two modes:
  contacts  -> extract name/email/paper-titles into contacts.csv
  notes     -> dump clean plain text per file into data/notes/ (and optionally clipboard)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .scrape import EMAIL_RE, OBFUSCATED, ROLE_ADDRESS, SKIP_LOCALPARTS
from .store import DATA, now

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm"}
NAME_RE = re.compile(r"\b([A-Z][a-z]{1,15})\s+(?:[A-Z]\.\s+)?([A-Z][a-zA-Z'\-]{1,20})\b")
PAPER_RE = re.compile(r'["“](.{15,160}?)["”]')


def read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        print(f"  [skip] {path.name}: pip install pypdf")
        return ""
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    except Exception as exc:
        print(f"  [skip] {path.name}: {exc}")
        return ""


def read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        print(f"  [skip] {path.name}: pip install python-docx")
        return ""
    try:
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    except Exception as exc:
        print(f"  [skip] {path.name}: {exc}")
        return ""


def read_html(path: Path) -> str:
    from bs4 import BeautifulSoup
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        return BeautifulSoup(raw, "lxml").get_text("\n", strip=True)
    except Exception:
        return BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)


def read_any(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return read_pdf(path)
    if ext == ".docx":
        return read_docx(path)
    if ext in (".html", ".htm"):
        return read_html(path)
    if ext in TEXT_EXT:
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def emails_in(text: str) -> list[str]:
    for pattern, repl in OBFUSCATED:
        text = pattern.sub(repl, text)
    seen, out = set(), []
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0).lower().rstrip(".")
        local = addr.split("@")[0]
        if addr in seen or local in SKIP_LOCALPARTS or ROLE_ADDRESS.search(local):
            continue
        seen.add(addr)
        out.append(addr)
    return out


def name_near(text: str, addr: str) -> str:
    idx = text.lower().find(addr)
    if idx < 0:
        return ""
    window = text[max(0, idx - 220):idx]
    matches = NAME_RE.findall(window)
    if matches:
        return " ".join(matches[-1])
    local = addr.split("@")[0]
    if "." in local:
        return " ".join(p.capitalize() for p in local.split(".")[:2])
    return ""


def harvest_contacts(folder: Path, school: str = "", dept: str = "") -> list[dict]:
    rows = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXT | {".pdf", ".docx"}:
            continue
        text = clean(read_any(path))
        if not text:
            continue
        addrs = emails_in(text)
        papers = " | ".join(list(dict.fromkeys(PAPER_RE.findall(text)))[:6])
        print(f"  {path.name}: {len(addrs)} email(s), {len(text.split())} words")
        for addr in addrs:
            name = name_near(text, addr)
            parts = name.split()
            rows.append({
                "email": addr, "name": name,
                "first_name": parts[0] if parts else "",
                "last_name": parts[-1] if len(parts) > 1 else "",
                "role": "", "team": dept, "org": school,
                "focus": "", "signals": papers, "site": "", "linkedin": "",
                "profile_url": "", "source": f"doc:{path.name}",
                "source_kind": "document", "audience": "academic",
                "scraped_at": now(), "status": "new",
                "notes": f"harvested from {path.name}",
            })
    return rows


def to_clipboard(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except ImportError:
        pass
    try:
        subprocess.run("clip", input=text.encode("utf-16le"), check=True)
        return True
    except Exception:
        return False


def harvest_notes(folder: Path, clip: bool = False) -> list[Path]:
    out_dir = DATA / "notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    written, blob = [], []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXT | {".pdf", ".docx"}:
            continue
        text = clean(read_any(path))
        if not text:
            continue
        dest = out_dir / (path.stem + ".txt")
        dest.write_text(text, encoding="utf-8")
        written.append(dest)
        blob.append(f"===== {path.name} =====\n{text}")
        print(f"  {path.name} -> {dest.relative_to(DATA.parent)} ({len(text.split())} words)")
    if clip and blob:
        joined = "\n\n".join(blob)
        print("  copied to clipboard" if to_clipboard(joined)
              else "  clipboard unavailable (pip install pyperclip)")
    return written
