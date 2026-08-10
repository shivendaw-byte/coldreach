"""Merged config: config.yaml (documented, hand-editable) + data/settings.json.

The app only ever writes to settings.json. config.yaml keeps its comments, so it
stays readable as the place you go to add a campaign or a source by hand.
Anything in settings.json wins.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
EXAMPLE = ROOT / "config.example.yaml"
OVERLAY = ROOT / "data" / "settings.json"


def _overlay() -> dict:
    if not OVERLAY.exists():
        return {}
    try:
        return json.loads(OVERLAY.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_overlay(data: dict) -> None:
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    OVERLAY.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load() -> dict:
    # config.yaml is gitignored (it holds your details), so a fresh clone starts
    # from the shared example.
    if not CONFIG.exists():
        if not EXAMPLE.exists():
            raise SystemExit(f"Missing both {CONFIG.name} and {EXAMPLE.name}")
        CONFIG.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    ov = _overlay()

    cfg.setdefault("me", {}).update(ov.get("me", {}))
    cfg.setdefault("limits", {}).update(ov.get("limits", {}))

    enabled = ov.get("sources_enabled", {})
    extra_by_name = {s["name"]: s for s in ov.get("sources", [])}
    for src in cfg.get("sources", []):
        if src["name"] in enabled:
            src["enabled"] = enabled[src["name"]]
        if src["name"] in extra_by_name:
            src.update(extra_by_name.pop(src["name"]))
    cfg.setdefault("sources", []).extend(extra_by_name.values())
    return cfg


def set_profile(fields: dict) -> None:
    allowed = {"name", "first", "email", "year", "institution", "major",
               "background", "signature_line"}
    ov = _overlay()
    me = ov.setdefault("me", {})
    me.update({k: v for k, v in fields.items() if k in allowed})
    _write_overlay(ov)


def set_source_enabled(name: str, enabled: bool) -> None:
    ov = _overlay()
    ov.setdefault("sources_enabled", {})[name] = bool(enabled)
    _write_overlay(ov)


def upsert_source(src: dict) -> None:
    """Add or update a source created from the app (e.g. a pasted directory URL)."""
    ov = _overlay()
    sources = ov.setdefault("sources", [])
    for i, s in enumerate(sources):
        if s.get("name") == src.get("name"):
            sources[i] = src
            break
    else:
        sources.append(src)
    _write_overlay(ov)
