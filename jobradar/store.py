"""Persistence: seen.json (job lifecycle), daily snapshots, and per-source health."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .models import Job, SourceResult


def days_between(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = _read_json(self.path, {"jobs": {}})

    def update(self, jobs: list[Job], today: str, fetched_companies: set[str], purge_after_days: int = 30) -> None:
        records = self.data["jobs"]
        present: set[str] = set()
        for job in jobs:
            present.add(job.id)
            rec = records.get(job.id)
            if rec is None:
                rec = {"first_seen": today, "last_seen": today, "status": "new",
                       "title": job.title, "company": job.company, "url": job.url, "detail_fetched": today}
                records[job.id] = rec
            else:
                rec["last_seen"] = today
                rec["status"] = "new" if rec["first_seen"] == today else "open"
                rec["title"], rec["url"] = job.title, job.url
            job.first_seen, job.last_seen, job.status = rec["first_seen"], rec["last_seen"], rec["status"]
        for jid, rec in list(records.items()):
            company = jid.split(":", 1)[0]
            if jid in present or company not in fetched_companies or rec["last_seen"] == today:
                continue
            rec["status"] = "closed"
            if days_between(rec["last_seen"], today) > purge_after_days:
                del records[jid]

    def known_ids(self) -> set[str]:
        return set(self.data["jobs"])

    def detail_stale(self, job_id: str, today: str, days: int = 14) -> bool:
        rec = self.data["jobs"].get(job_id)
        if not rec:
            return True
        fetched = rec.get("detail_fetched") or rec["first_seen"]
        return days_between(fetched, today) > days

    def mark_detail_fetched(self, job_id: str, today: str) -> None:
        if job_id in self.data["jobs"]:
            self.data["jobs"][job_id]["detail_fetched"] = today

    def save(self) -> None:
        _write_json(self.path, self.data)


# Excluded jobs keep identity, lifecycle, score and the exclude reason in the snapshot, but not their text: on
# 2026-09-08 the 3,363 excluded postings were 37.9 MB of a 40.7 MB snapshot (the user: "if it's excluded, don't keep it
# where it costs every agent context"). The report's excluded list, eval regressions and repost detection only need
# the fields that stay. A job that later becomes visible (a preference change) is re-enriched by the 14-day detail
# refresh; until then it renders without a description.
SLIM_EXCLUDED_DROP = ("description_text", "qualifications_min", "qualifications_pref", "responsibilities",
                      "matched_skills", "score_parts")


def snapshot_record(job: Job) -> dict[str, Any]:
    d = job.to_dict()
    if job.excluded:
        for k in SLIM_EXCLUDED_DROP:
            d.pop(k, None)
    return d


def save_snapshot(directory: Path, date: str, jobs: list[Job], meta: dict[str, Any]) -> Path:
    path = Path(directory) / f"{date}.json"
    _write_json(path, {"date": date, "meta": meta, "jobs": [snapshot_record(j) for j in jobs]})
    return path


def load_snapshot(path: Path) -> tuple[dict[str, Any], list[Job]]:
    doc = json.loads(Path(path).read_text())
    return doc.get("meta", {}), [Job.from_dict(d) for d in doc.get("jobs", [])]


def list_snapshots(directory: Path) -> list[Path]:
    directory = Path(directory)
    return sorted(directory.glob("????-??-??.json")) if directory.exists() else []


def record_health(path: Path, date: str, results: list[SourceResult], keep_days: int = 60) -> None:
    data = _read_json(path, {})
    day = data.get(date, {})
    day.update({r.company: {"ok": r.ok, "count": r.count, "error": r.error} for r in results})   # partial runs merge
    data[date] = day
    for old in sorted(data):
        if days_between(old, date) > keep_days:
            del data[old]
    _write_json(path, data)


def breakage_warnings(path: Path, date: str) -> list[str]:
    data = _read_json(path, {})
    today = data.get(date, {})
    warnings: list[str] = []
    for company, rec in today.items():
        if not rec["ok"] or rec["count"] > 0:
            continue
        for prev_date in sorted((d for d in data if d < date), reverse=True):
            prev = data[prev_date].get(company)
            if prev and prev["ok"]:
                if prev["count"] > 0:
                    warnings.append(f"{company}: 0 jobs today but {prev['count']} on {prev_date} (possible breakage)")
                break
    return warnings
