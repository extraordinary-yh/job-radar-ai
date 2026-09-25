"""Deterministic 0-100 score from profile/preferences.yaml. Hard exclusions carry a reason."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .config import Preferences
from .models import Job


@dataclass
class ScoreResult:
    total: int
    parts: dict[str, int] = field(default_factory=dict)
    excluded: bool = False
    reason: str = ""
    matched_skills: list[str] = field(default_factory=list)
    family: str | None = None


def _excluded(reason: str) -> ScoreResult:
    return ScoreResult(0, {}, True, reason, [], None)


def match_title_family(title: str, prefs: Preferences) -> tuple[str | None, str | None]:
    t = title.lower()
    for pat in prefs.titles.get("exclude_patterns", []):
        if re.search(pat, t):
            return None, pat
    for fam in prefs.titles.get("include", []):
        for pat in fam.get("patterns", []):
            if re.search(pat, t):
                return fam["name"], None
    return None, None


def _term_re(term: str) -> re.Pattern[str]:
    # whole-term match with an optional plural ("agent" matches "agents", not "agency")
    return re.compile(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?:s|es)?(?![a-z0-9])")


def matched_skills(text: str, weights: dict[str, int]) -> list[str]:
    low = text.lower()
    return [k for k in weights if _term_re(k).search(low)]


def days_since(date_iso: str | None, today: str) -> int | None:
    if not date_iso:
        return None
    try:
        return (dt.date.fromisoformat(today) - dt.date.fromisoformat(date_iso)).days
    except ValueError:
        return None


def score_job(job: Job, prefs: Preferences, today: str) -> ScoreResult:
    w = prefs.weights
    parts: dict[str, int] = {}

    family, excl = match_title_family(job.title, prefs)
    if excl:
        return _excluded(f"title matches exclude pattern '{excl}'")
    if family is None and prefs.titles.get("require_family", True):
        return _excluded("title matches no target family")
    parts["title"] = int(w["title"]) if family else int(w["title"]) // 2

    hard = [f for f in job.flags if f in set(prefs.flags.get("exclude", []))]
    if hard:
        return _excluded(f"flag: {hard[0]}")
    floor = prefs.salary.get("floor")
    if floor and job.salary_max is not None and job.salary_max < int(floor):
        return _excluded(f"salary below floor (${job.salary_max:,})")

    if job.location_class == "non_us" and prefs.locations.get("exclude_non_us", True):
        return _excluded("non-US location")
    parts["location"] = int(prefs.locations["scores"].get(job.location_class, 0))

    exp = prefs.experience
    if job.level in exp.get("exclude_levels", []):
        return _excluded(f"level {job.level}")
    caps = exp.get("max_yoe_by_size") or {}
    if job.company_max_yoe is not None:
        cap, where = int(job.company_max_yoe), f" ({job.company} accepts up to {job.company_max_yoe})"
    else:
        cap = int(caps.get(job.company_size, caps.get("small", exp.get("max_yoe", 6))))
        where = f" at a {job.company_size} company" if job.company_size in caps and len(caps) > 1 else ""
    if job.yoe_min is not None and job.yoe_min > cap:
        return _excluded(f"requires {job.yoe_min}+ years{where}")
    if job.yoe_min is not None:
        experience = int(exp["yoe_scores"].get(job.yoe_min, exp["yoe_scores"].get(str(job.yoe_min), 0)))
    else:
        experience = int(exp["level_scores"].get(job.level, exp["level_scores"].get("unknown", 0)))
    if job.level == "senior":
        experience = min(experience, int(exp.get("senior_cap", experience)))
    cap_at = exp.get("preferred_yoe_cap_at")
    if cap_at is not None and job.yoe_pref is not None and job.yoe_pref >= int(cap_at):
        experience = min(experience, int(exp.get("preferred_yoe_cap_points", 5)))
    parts["experience"] = experience

    sk = prefs.skills
    text = " ".join([job.title, job.description_text, job.responsibilities, job.qualifications_min, job.qualifications_pref])
    matched = matched_skills(text, sk["weights"])
    raw = sum(int(sk["weights"][k]) for k in matched)
    parts["skills"] = min(int(sk["max_points"]), round(raw * int(sk["max_points"]) / int(sk["full_marks"])))

    rec = prefs.recency
    parts["recency"] = int(rec.get("default", 1))
    age = days_since(job.posted_at or job.first_seen, today)
    if age is not None:
        for limit, pts in rec["days_scores"]:
            if age <= int(limit):
                parts["recency"] = int(pts)
                break

    return ScoreResult(total_from_parts(parts, penalty_points(job.flags, prefs)), parts, False, "", matched, family)


def penalty_points(flags: list[str], prefs: Preferences) -> int:
    """Negative number: the sum of penalties for the job's flags."""
    return sum(int(prefs.penalties.get(f, 0)) for f in flags)


def total_from_parts(parts: dict[str, int], penalty: int) -> int:
    return max(0, min(100, sum(parts.values()) + penalty))


def apply_scores(jobs: list[Job], prefs: Preferences, today: str) -> None:
    for job in jobs:
        r = score_job(job, prefs, today)
        job.score, job.score_parts, job.excluded, job.exclude_reason = r.total, r.parts, r.excluded, r.reason
        job.matched_skills, job.rank_score = r.matched_skills, float(r.total)
