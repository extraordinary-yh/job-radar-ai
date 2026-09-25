"""Follow-up cadence for applications, ported from career-ops's followup-cadence.mjs rules.

Applied and silent: first touch at 7 days, then every 7, cold after 2 touches.
In an interview stage (oa, phone, onsite): thank-you within 1 day of the stage change, then every 3 days.
Offer, rejected, withdrawn: nothing due. Inputs are the feedback log: the applied date, the latest
stage and when it was set, and `followup <id>` touches the user records from the report or the CLI.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

CADENCE = {"applied_first": 7, "applied_subsequent": 7, "applied_max_followups": 2,
           "interview_thankyou": 1, "interview_subsequent": 3}
INTERVIEW_STAGES = ("oa", "phone", "onsite")
DONE_STAGES = ("offer", "rejected", "withdrawn")
ORDER = {"overdue": 0, "waiting": 1, "cold": 2, "done": 3}


def _date(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return None


def _add(d: dt.date, days: int) -> str:
    return (d + dt.timedelta(days=days)).isoformat()


def assess(entry: dict[str, Any], today: str) -> dict[str, Any]:
    """{urgency: overdue|waiting|cold|done, next_due: date|"", touches: n, last_touch: date|"", why: str}."""
    now = _date(today) or dt.date.today()
    stage = str(entry.get("stage") or "applied")
    applied_on = _date(entry.get("applied_on")) or _date(entry.get("stage_on"))
    stage_on = _date(entry.get("stage_on")) or applied_on
    touches = [t for t in (entry.get("followups") or []) if _date(t.get("date"))]
    last = _date(touches[-1]["date"]) if touches else None
    base = {"touches": len(touches), "last_touch": touches[-1]["date"] if touches else ""}
    if stage in DONE_STAGES:
        return {**base, "urgency": "done", "next_due": "", "why": f"{stage}: nothing to chase"}
    if stage in INTERVIEW_STAGES:
        since_stage = [t for t in touches if stage_on and _date(t["date"]) >= stage_on]
        if since_stage:
            due = _add(_date(since_stage[-1]["date"]), CADENCE["interview_subsequent"])
            why = f"{stage}: last touch {since_stage[-1]['date']}, check in every {CADENCE['interview_subsequent']} days"
        else:
            due = _add(stage_on, CADENCE["interview_thankyou"]) if stage_on else ""
            why = f"{stage} on {stage_on}: send the thank-you note" if stage_on else f"{stage}: date unknown"
        urgency = "overdue" if due and _date(due) <= now else "waiting"
        return {**base, "urgency": urgency, "next_due": due, "why": why}
    if not applied_on:
        return {**base, "urgency": "waiting", "next_due": "", "why": "applied date unknown"}
    if len(touches) >= CADENCE["applied_max_followups"]:
        return {**base, "urgency": "cold", "next_due": "", "why": f"{len(touches)} follow-ups sent with no reply; let it rest"}
    if not touches:
        due = _add(applied_on, CADENCE["applied_first"])
        why = f"applied {applied_on}: first follow-up at {CADENCE['applied_first']} days"
    else:
        due = _add(last, CADENCE["applied_subsequent"])
        why = f"followed up {last}: next in {CADENCE['applied_subsequent']} days"
    urgency = "overdue" if _date(due) <= now else "waiting"
    return {**base, "urgency": urgency, "next_due": due, "why": why}


def annotate_archive(archive: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Attach entry['followup'] = assess(...) to every archive row and return the rows sorted by urgency."""
    for a in archive:
        a["followup"] = assess(a, today)
    return sorted(archive, key=lambda a: (ORDER.get(a["followup"]["urgency"], 9), a["followup"]["next_due"] or "9999", a.get("company", "")))


def format_rows(rows: list[dict[str, Any]], only_due: bool = False) -> str:
    lines = []
    for a in rows:
        f = a["followup"]
        if only_due and f["urgency"] != "overdue":
            continue
        head = f"{f['urgency']:8} {f['next_due'] or '    -    '}  {a.get('company', '?')} — {a.get('title', a.get('id'))}"
        lines.append(head)
        lines.append(f"         {f['why']} · {a.get('id')}")
    return "\n".join(lines) if lines else ("nothing overdue" if only_due else "no applications on file")
