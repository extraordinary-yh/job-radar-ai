"""Is an applied posting still open? career-ops's ATS API rung, no browser.

Only the applied archive is checked: today's cards came from the boards today, so they are
live by construction. Greenhouse, Lever, Ashby, Workday and LinkedIn URLs get a definite
answer; other hosts stay "uncertain" and the sidebar shows nothing for them.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

from .careerops import CareerOpsError, data_root, run_json, unavailable_reason

RUNNER = "scripts/careerops/liveness.mjs"
TTL_DAYS = 1


def check(root: Path, urls: list[str]) -> dict[str, dict[str, str]]:
    """{url: {result: active|expired|uncertain, reason}} for every URL asked."""
    if not urls:
        return {}
    out = run_json(root, RUNNER, stdin=json.dumps(urls), timeout=300)
    result: dict[str, dict[str, str]] = {}
    for url in urls:
        r = out.get(url) if isinstance(out, dict) else None
        if isinstance(r, dict) and r.get("result") in ("active", "expired"):
            result[url] = {"result": str(r["result"]), "reason": str(r.get("reason") or "")}
        else:
            result[url] = {"result": "uncertain", "reason": "no public ATS API for this host"}
    return result


def store_path(root: Path) -> Path:
    return data_root(root) / "liveness.json"


def load_store(root: Path) -> dict[str, dict[str, str]]:
    p = store_path(root)
    return json.loads(p.read_text()) if p.exists() else {}


def _fresh(entry: dict[str, str], today: str) -> bool:
    try:
        return (dt.date.fromisoformat(today) - dt.date.fromisoformat(entry.get("checked", ""))).days < TTL_DAYS
    except ValueError:
        return False


def annotate_archive(archive: list[dict[str, Any]], root: Path, today: str, *, warnings: list[str] | None = None,
                     check_fn: Callable[[list[str]], dict[str, dict[str, str]]] | None = None) -> dict[str, dict[str, str]]:
    """Set entry['live'] (active | expired | uncertain) and entry['live_checked'] on archive rows; cached one day per URL."""
    warnings = warnings if warnings is not None else []
    urls = sorted({str(a.get("url") or "") for a in archive if a.get("url")})
    if not urls:
        return {}
    store = load_store(root)
    reason = unavailable_reason(root)
    todo = [u for u in urls if not _fresh(store.get(u, {}), today)]
    if todo and reason:
        warnings.append(f"liveness: {reason}")
    elif todo:
        try:
            found = (check_fn or (lambda us: check(root, us)))(todo)
        except CareerOpsError as e:
            warnings.append(f"liveness: {e}")
            found = {}
        for u, r in found.items():
            store[u] = {**r, "checked": today}
        store = {u: v for u, v in store.items() if u in urls}          # forget URLs no longer in the archive
        store_path(root).write_text(json.dumps(store, indent=1) + "\n")
    for a in archive:
        entry = store.get(str(a.get("url") or ""))
        if entry:
            a["live"], a["live_checked"] = entry["result"], entry.get("checked", "")
    return store
