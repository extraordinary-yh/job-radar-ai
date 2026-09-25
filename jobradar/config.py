"""Load config/companies.yaml and profile/preferences.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    env = os.environ.get("JOBRADAR_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("pyproject.toml not found above cwd; set JOBRADAR_ROOT")


@dataclass
class CompanyConfig:
    name: str
    key: str
    adapter: str
    enabled: bool = True
    queries: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    max_pages: int = 1
    board: str = ""
    size: str = "small"           # big | small
    max_yoe: int | None = None    # per-company cap on years asked; overrides preferences.experience.max_yoe_by_size
    extra: dict[str, Any] = field(default_factory=dict)


KNOWN_FIELDS = {"name", "key", "adapter", "enabled", "queries", "locations", "max_pages", "board", "size", "max_yoe"}


def load_companies(path: Path) -> list[CompanyConfig]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    out: list[CompanyConfig] = []
    seen: set[str] = set()
    for entry in doc.get("companies", []):
        key = str(entry["key"])
        if key in seen:
            raise ValueError(f"duplicate company key: {key}")
        seen.add(key)
        out.append(CompanyConfig(
            name=str(entry["name"]), key=key, adapter=str(entry["adapter"]),
            enabled=bool(entry.get("enabled", True)),
            queries=[str(q) for q in entry.get("queries", [])],
            locations=[str(l) for l in entry.get("locations", [])],
            max_pages=int(entry.get("max_pages", 1)), board=str(entry.get("board", "")),
            size=str(entry.get("size", "small")),
            max_yoe=int(entry["max_yoe"]) if entry.get("max_yoe") is not None else None,
            extra={k: v for k, v in entry.items() if k not in KNOWN_FIELDS},
        ))
    return out


@dataclass
class Preferences:
    candidate: dict[str, Any]
    titles: dict[str, Any]
    locations: dict[str, Any]
    experience: dict[str, Any]
    skills: dict[str, Any]
    recency: dict[str, Any]
    penalties: dict[str, Any]
    weights: dict[str, Any]
    review: dict[str, Any]
    referrals: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    salary: dict[str, Any] = field(default_factory=dict)


def load_preferences(path: Path) -> Preferences:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    sections = ("candidate", "titles", "locations", "experience", "skills", "recency",
                "penalties", "weights", "review")
    missing = [s for s in sections if s not in doc]
    if missing:
        raise ValueError(f"preferences.yaml missing sections: {missing}")
    prefs = Preferences(**{s: dict(doc[s]) for s in sections})
    prefs.referrals = dict(doc.get("referrals") or {})
    prefs.flags = dict(doc.get("flags") or {})
    prefs.salary = dict(doc.get("salary") or {})
    return prefs
