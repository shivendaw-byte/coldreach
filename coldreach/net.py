"""Polite HTTP: robots.txt, per-host rate limiting, on-disk cache."""
from __future__ import annotations

import hashlib
import time
import urllib.robotparser as robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / ".cache"

USER_AGENT = (
    "coldreach/1.0 (+student research outreach; contact: sdawda@sas.upenn.edu)"
)

_last_hit: dict[str, float] = {}
_robots: dict[str, robotparser.RobotFileParser | None] = {}
_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    return _session


def _robots_for(url: str) -> robotparser.RobotFileParser | None:
    host = urlparse(url).netloc
    if host in _robots:
        return _robots[host]
    rp = robotparser.RobotFileParser()
    rp.set_url(urljoin(url, "/robots.txt"))
    try:
        raw = session().get(urljoin(url, "/robots.txt"), timeout=15)
        rp.parse(raw.text.splitlines() if raw.ok else [])
    except Exception:
        rp = None
    _robots[host] = rp
    return rp


def allowed(url: str) -> bool:
    rp = _robots_for(url)
    if rp is None:
        return True
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _throttle(url: str, delay: float) -> None:
    host = urlparse(url).netloc
    elapsed = time.time() - _last_hit.get(host, 0.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_hit[host] = time.time()


def _cache_path(url: str) -> Path:
    return CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")


def get(url: str, delay: float = 2.0, ttl_hours: float = 168.0,
        use_cache: bool = True) -> str | None:
    """Fetch a page as text. Returns None if disallowed, failed, or non-HTML."""
    cp = _cache_path(url)
    if use_cache and cp.exists():
        age_h = (time.time() - cp.stat().st_mtime) / 3600
        if age_h < ttl_hours:
            return cp.read_text(encoding="utf-8", errors="replace")

    if not allowed(url):
        print(f"  [robots] disallowed: {url}")
        return None

    _throttle(url, delay)
    try:
        r = session().get(url, timeout=25, allow_redirects=True)
    except Exception as exc:
        print(f"  [net] {type(exc).__name__}: {url}")
        return None
    if not r.ok or "html" not in r.headers.get("Content-Type", "").lower():
        return None

    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(r.text, encoding="utf-8", errors="replace")
    return r.text
