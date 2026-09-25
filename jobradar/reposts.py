"""Repost detection: the same company re-listing a title under a new URL within 90 days.

data/seen.json (every posting job-radar has seen, kept 30 days after it disappears) is exported
to the scan-history.tsv shape career-ops's detect-reposts.mjs reads. Jobs whose URL falls in a
cluster get the `repost` flag; flags carry no penalty unless preferences.yaml says so.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .careerops import CareerOpsError, data_root, run_json, unavailable_reason
from .models import Job

DETECT = "detect-reposts.mjs"
FLAG = "repost"


def history_path(root: Path) -> Path:
    return data_root(root) / "data" / "scan-history.tsv"


def export_history(root: Path, seen: dict[str, dict[str, Any]]) -> Path:
    """scan-history.tsv: url, first_seen, portal, title, company, status, location — one row per seen posting."""
    p = history_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = ["url\tfirst_seen\tportal\ttitle\tcompany\tstatus\tlocation"]
    for job_id, rec in sorted(seen.items(), key=lambda kv: (kv[1].get("first_seen", ""), kv[0])):
        url = str(rec.get("url") or "").strip()
        if not url or not rec.get("first_seen"):
            continue
        clean = lambda s: str(s or "").replace("\t", " ").replace("\n", " ").strip()
        rows.append("\t".join([url, str(rec["first_seen"]), job_id.split(":", 1)[0], clean(rec.get("title")),
                               clean(rec.get("company")), "added", ""]))
    p.write_text("\n".join(rows) + "\n")
    return p


MIN_SPAN_DAYS = 7


def detect(root: Path, *, window_days: int = 90, min_span_days: int = MIN_SPAN_DAYS) -> list[dict[str, Any]]:
    env = {"CAREER_OPS_ROOT": str(data_root(root).resolve())}
    out = run_json(root, DETECT, ["--window", str(window_days), "--min-span", str(min_span_days)], env=env, timeout=120)
    clusters = out.get("clusters") if isinstance(out, dict) else out
    return [c for c in (clusters or []) if isinstance(c, dict)]


def real_reposts(clusters: list[dict[str, Any]], seen: dict[str, dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Keep clusters where an earlier listing has actually gone away.

    Big boards list one title in many cities at once; those siblings are all still open. A repost means
    the old URL disappeared and the title came back under a new one, so at least one appearance other
    than the newest must be absent from today's fetch (seen.json's last_seen before today)."""
    by_url = {str(rec.get("url") or ""): rec for rec in seen.values()}
    kept = []
    for c in clusters:
        apps = sorted(c.get("appearances") or [], key=lambda a: str(a.get("date") or ""))
        earlier = apps[:-1]
        if earlier and any(str(by_url.get(str(a.get("url")), {}).get("last_seen") or "") < today for a in earlier):
            kept.append(c)
    return kept


def url_index(clusters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """url -> cluster summary for every appearance in every cluster."""
    idx: dict[str, dict[str, Any]] = {}
    for c in clusters:
        summary = {"company": c.get("company", ""), "role": c.get("role", ""), "count": int(c.get("repostCount") or 0),
                   "first_seen": c.get("firstSeen", ""), "last_seen": c.get("lastSeen", ""), "days": int(c.get("daysSpan") or 0)}
        for a in c.get("appearances") or []:
            if a.get("url"):
                idx[str(a["url"])] = summary
    return idx


def store_path(root: Path) -> Path:
    return data_root(root) / "reposts.json"


def annotate(jobs: list[Job], root: Path, seen: dict[str, dict[str, Any]], today: str, *, warnings: list[str] | None = None,
             detect_fn: Callable[[], list[dict[str, Any]]] | None = None) -> dict[str, dict[str, Any]]:
    """Flag every job whose URL sits in a real repost cluster; returns url -> cluster summary."""
    warnings = warnings if warnings is not None else []
    reason = unavailable_reason(root)
    if reason:
        warnings.append(f"reposts: {reason}")
        return {}
    export_history(root, seen)
    try:
        clusters = (detect_fn or (lambda: detect(root)))()
    except CareerOpsError as e:
        warnings.append(f"reposts: {e}")
        return {}
    clusters = real_reposts(clusters, seen, today)
    idx = url_index(clusters)
    store_path(root).write_text(json.dumps(clusters, indent=1, ensure_ascii=False) + "\n")
    for j in jobs:
        if j.url in idx and FLAG not in j.flags:
            j.flags.append(FLAG)
    return idx
