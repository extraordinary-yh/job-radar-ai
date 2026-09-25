"""Per-job verdicts from the user: append-only JSONL, latest verdict wins."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .models import Job

VERDICTS = ("good", "bad", "applied", "ignore")
STAGES = ("applied", "oa", "phone", "onsite", "offer", "rejected", "withdrawn")
KINDS = ("referral", "tailor", "followup", "company_ignore")
_RESUME_TOKEN = re.compile(r"^resume=([0-9a-f]{8})\b\s*")


def parse_feedback_text(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("{"):
            obj = json.loads(line)
            if obj.get("kind") in KINDS:
                allowed = ("company_key", "job_id", "kind", "state", "note")
                entries.append({k: v for k, v in obj.items() if k in allowed})
                continue
            entry = {"job_id": str(obj["job_id"]), "verdict": str(obj.get("verdict", "applied")), "note": str(obj.get("note", ""))}
            if obj.get("stage"):
                entry["stage"] = str(obj["stage"]).lower()
            if obj.get("resume"):
                entry["resume"] = str(obj["resume"])
        else:
            parts = line.split(None, 2)
            if len(parts) < 2:
                raise ValueError(f"cannot parse feedback line: {line!r}")
            head = parts[0].lower()
            if head == "referral":                                # "referral <job_id> [none|off]"
                state = "off" if (parts[2] if len(parts) > 2 else "").strip().lower() in ("none", "off") else "on"
                entries.append({"job_id": parts[1], "kind": "referral", "state": state})
                continue
            if head == "tailor":                                  # "tailor <job_id>"
                entries.append({"job_id": parts[1], "kind": "tailor"})
                continue
            if head == "followup":                                # "followup <job_id> [note]": one outreach touch, today
                entries.append({"job_id": parts[1], "kind": "followup", "note": parts[2] if len(parts) > 2 else ""})
                continue
            if head == "ignore-company":                          # "ignore-company <company_key> [note]"
                entries.append({"company_key": parts[1].lower(), "kind": "company_ignore", "note": parts[2] if len(parts) > 2 else ""})
                continue
            if head == "stage":                                   # "stage <job_id> <stage> [resume=<sha8>] [note]"
                rest = (parts[2] if len(parts) > 2 else "").split(None, 1)
                if not rest:
                    raise ValueError(f"stage line needs a stage: {line!r}")
                note = rest[1] if len(rest) > 1 else ""
                entry = {"job_id": parts[1], "verdict": "applied", "stage": rest[0].lower(), "note": note}
                m = _RESUME_TOKEN.match(note)
                if m:
                    entry["resume"], entry["note"] = m.group(1), note[m.end():]
            else:
                entry = {"job_id": parts[1], "verdict": head, "note": parts[2] if len(parts) > 2 else ""}
        if entry["verdict"] not in VERDICTS:
            raise ValueError(f"unknown verdict {entry['verdict']!r} (expected one of {VERDICTS})")
        if entry.get("stage") and entry["stage"] not in STAGES:
            raise ValueError(f"unknown stage {entry['stage']!r} (expected one of {STAGES})")
        entries.append(entry)
    return entries


def append_feedback(path: Path, entries: list[dict[str, Any]], ts: str | None = None) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = ts or dt.datetime.now().replace(microsecond=0).isoformat()
    with path.open("a") as f:
        for e in entries:
            if e.get("kind") in KINDS:
                rec = {"ts": stamp, "kind": e["kind"]}
                if e["kind"] == "company_ignore":
                    rec["company_key"] = str(e["company_key"]).lower()
                    if e.get("note"):
                        rec["note"] = str(e["note"])
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    continue
                rec["job_id"] = e["job_id"]
                if e["kind"] == "referral":
                    rec["state"] = "on" if e.get("state", "on") == "on" else "off"
                if e["kind"] == "followup" and e.get("note"):
                    rec["note"] = str(e["note"])
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            if e["verdict"] not in VERDICTS:
                raise ValueError(f"unknown verdict {e['verdict']!r}")
            rec = {"ts": stamp, "job_id": e["job_id"], "verdict": e["verdict"], "note": e.get("note", "")}
            if e.get("stage"):
                if e["stage"] not in STAGES:
                    raise ValueError(f"unknown stage {e['stage']!r}")
                rec["stage"] = e["stage"]
            if e.get("resume"):
                rec["resume"] = e["resume"]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(entries)


def latest_verdicts(path: Path) -> dict[str, dict[str, Any]]:
    """Latest verdict per job; the latest stage and the first applied date ride along."""
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("kind") in KINDS:
            continue
        prev = out.get(e["job_id"], {})
        merged = {**prev, **e}
        merged["stage"] = e.get("stage") or (prev.get("stage") if e.get("verdict") == "applied" else None) or ("applied" if e.get("verdict") == "applied" else None)
        merged["applied_on"] = prev.get("applied_on") or (str(e.get("ts", ""))[:10] if e.get("verdict") == "applied" else None)
        out[e["job_id"]] = merged
    return out


def company_ignores(path: Path) -> set[str]:
    """Company keys the user has explicitly opted out of, from the append-only feedback ledger."""
    return {str(e["company_key"]).lower() for e in _events(path, "company_ignore") if e.get("company_key")}


def apply_feedback(jobs: list[Job], verdicts: dict[str, dict[str, Any]], ignored_companies: set[str] | None = None) -> None:
    for job in jobs:
        if job.id.split(":", 1)[0].lower() in (ignored_companies or set()):
            job.verdict = "ignore"
            job.hidden = True
            continue
        v = verdicts.get(job.id)
        if v:
            job.verdict = v["verdict"]
            job.hidden = v["verdict"] in ("bad", "ignore")


def _events(path: Path, kind: str) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [e for e in (json.loads(l) for l in path.read_text().splitlines() if l.strip()) if e.get("kind") == kind]


def referral_marks(path: Path) -> dict[str, bool]:
    """Latest referral state per job: True when a referral is pending or found."""
    out: dict[str, bool] = {}
    for e in _events(path, "referral"):
        out[e["job_id"]] = e.get("state", "on") == "on"
    return out


def _company_of(job_id: str, seen: dict[str, dict[str, Any]]) -> str:
    return seen.get(job_id, {}).get("company") or job_id.split(":", 1)[0].title()


def referral_companies(path: Path, seen: dict[str, dict[str, Any]]) -> set[str]:
    """Companies with at least one job marked referral-on; the apply batch skips them."""
    return {_company_of(j, seen) for j, on in referral_marks(path).items() if on}


def followup_events(path: Path) -> dict[str, list[dict[str, str]]]:
    """job_id -> [{date, note}, ...] in log order; one entry per outreach touch the user recorded."""
    out: dict[str, list[dict[str, str]]] = {}
    for e in _events(path, "followup"):
        out.setdefault(e["job_id"], []).append({"date": str(e.get("ts", ""))[:10], "note": str(e.get("note", ""))})
    return out


def pending_tailors(path: Path, applications_dir: Path) -> list[str]:
    ids: list[str] = []
    for e in _events(path, "tailor"):
        if e["job_id"] not in ids:
            ids.append(e["job_id"])
    return [j for j in ids if not (Path(applications_dir) / j.replace(":", "-") / "overlay.yaml").exists()]


def applied_archive(path: Path, seen: dict[str, dict[str, Any]], applications_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every job the user marked applied, newest first, joined with what seen.json knows (title, url, status)."""
    out: list[dict[str, Any]] = []
    touches = followup_events(path)
    for job_id, v in latest_verdicts(path).items():
        if v.get("verdict") != "applied":
            continue
        rec = seen.get(job_id, {})
        job_dir = job_id.replace(":", "-")
        has_pdf = applications_dir is not None and (Path(applications_dir) / job_dir / "resume.pdf").exists()
        resume_path = f"../data/applications/{job_dir}/resume.pdf" if has_pdf else ""
        if applications_dir is not None:
            pointer = Path(applications_dir) / job_dir / "resume-location.json"
            if pointer.exists():
                try:
                    location = json.loads(pointer.read_text())
                    relative = (location.get("versions") or {}).get(v.get("resume"), location.get("path", ""))
                    if relative and (Path(applications_dir).parent.parent / relative).is_file():
                        resume_path = "../" + relative
                except (json.JSONDecodeError, OSError, KeyError):
                    pass
        out.append({"id": job_id, "applied_on": v.get("applied_on") or str(v.get("ts", ""))[:10], "note": v.get("note", ""),
                    "stage": v.get("stage") or "applied", "stage_on": str(v.get("ts", ""))[:10],
                    "title": rec.get("title", job_id), "company": rec.get("company", job_id.split(":", 1)[0].title()),
                    "url": rec.get("url", ""), "status": rec.get("status", "unknown"), "first_seen": rec.get("first_seen", ""),
                    "resume": v.get("resume", ""), "resume_path": resume_path,
                    "followups": touches.get(job_id, [])})
    out.sort(key=lambda e: e["applied_on"], reverse=True)
    return out
