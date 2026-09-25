"""Render the daily job board as one self-contained HTML page."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Preferences
from .models import Job

TEMPLATES = Path(__file__).parent / "templates"
ARRANGEMENT_LABEL = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site", "unknown": "Arrangement unknown"}
METRO_LABEL = {"nyc": "New York", "bay": "SF Bay Area", "remote_us": "Remote US", "other_us": "Other US",
               "non_us": "Outside US", "unknown": "Location unknown"}


def yoe_label(yoe_min: int | None, effective: float) -> str:
    """match: asks no more than the user's full-time years; stretch: up to two more; over: beyond that."""
    if yoe_min is None:
        return "not stated"
    if yoe_min <= effective:
        return "match"
    if yoe_min <= effective + 2:
        return "stretch"
    return "over"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    env.filters["metro"] = lambda c: METRO_LABEL.get(c, c)
    env.filters["arrangement"] = lambda a: ARRANGEMENT_LABEL.get(a, a)
    return env


PART_ORDER = ("title", "location", "experience", "skills", "recency")


def referral_url(company: str) -> str:
    from urllib.parse import quote
    return f"https://www.linkedin.com/search/results/people/?keywords={quote(company)}&network=%5B%22F%22%5D&origin=FACETED_SEARCH"


def second_degree_url(company: str) -> str:
    from urllib.parse import quote
    return f"https://www.linkedin.com/search/results/people/?keywords={quote(company)}&network=%5B%22S%22%5D&origin=FACETED_SEARCH"


def _salary_label(lo: int | None, hi: int | None) -> str:
    if lo is None and hi is None:
        return ""
    fmt = lambda v: f"${round(v / 1000)}K"
    return fmt(lo) if lo == hi or hi is None else (f"{fmt(lo)}–{fmt(hi)}" if lo is not None else fmt(hi))


MAX_CONNECTIONS = 4


def _card(j: Job, effective: float, maxes: dict[str, int], referrals: dict[str, Any] | None = None,
          marks: dict[str, bool] | None = None, companies: set[str] | None = None,
          connections: dict[str, list[dict[str, str]]] | None = None,
          reposts: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    referrals = referrals or {}
    known = (connections or {}).get(j.company) or []
    rp = (reposts or {}).get(j.url)
    repost_note = (f"listed {rp['count']} times over {rp['days']} days ({rp['first_seen']} → {rp['last_seen']}); "
                   "the same title keeps coming back under new URLs") if rp else ""
    wants_referral = (not j.excluded and j.score >= int(referrals.get("min_score", 101))
                      and j.company not in set(referrals.get("skip_companies", [])))
    parts = j.score_parts or {}
    penalty = max(0, sum(parts.values()) - j.score) if parts else 0
    reviewed = j.review is not None and not j.excluded
    chart = [{"name": k, "value": int(parts.get(k, 0)), "max": int(maxes.get(k, 0)),
              "pct": round(100 * int(parts.get(k, 0)) / int(maxes.get(k, 1)) if maxes.get(k) else 0),
              "semantic": k == "skills" and reviewed} for k in PART_ORDER]
    return {
        "id": j.id, "company": j.company, "company_key": j.id.split(":", 1)[0], "title": j.title, "url": j.url,
        "locations": j.locations[:3], "more_locations": max(0, len(j.locations) - 3),
        "metro": j.location_class, "arrangement": j.arrangement, "level": j.level,
        "yoe_min": j.yoe_min, "yoe_label": yoe_label(j.yoe_min, effective), "yoe_pref": j.yoe_pref, "flags": j.flags,
        "salary": _salary_label(j.salary_min, j.salary_max),
        "status": j.status, "first_seen": j.first_seen, "posted_at": j.posted_at,
        "score": j.score, "parts": parts, "penalty": penalty, "chart": chart, "rank": round(j.rank_score, 1),
        "skills": j.matched_skills, "verdict": j.verdict or "", "reviewed": reviewed,
        "referral_url": referral_url(j.company) if wants_referral else "",
        "referral_on": bool((marks or {}).get(j.id)), "company_referral": j.company in (companies or set()),
        "skills_points": int(parts.get("skills", 0)),
        "h1b_tier": j.h1b_tier, "h1b_note": j.h1b_note,
        "connections": known[:MAX_CONNECTIONS], "more_connections": max(0, len(known) - MAX_CONNECTIONS),
        "connection_count": len(known), "second_degree_url": second_degree_url(j.company),
        "repost_note": repost_note,
        "reason": j.review.reason if j.review else "", "gaps": j.review.gaps if j.review else [],
        "yoe_match": j.review.yoe_match if j.review else "", "experience_match": j.review.experience_match if j.review else "",
    }


def render_report(jobs: list[Job], meta: dict[str, Any], prefs: Preferences, date: str,
                  archive: list[dict[str, Any]] | None = None, referral_marks: dict[str, bool] | None = None,
                  referral_companies: set[str] | None = None,
                  connections: dict[str, list[dict[str, str]]] | None = None,
                  reposts: dict[str, dict[str, Any]] | None = None,
                  write: dict[str, Any] | None = None) -> str:
    """`write` = {repo: "owner/name", branch, api?} turns on the feedback box's Send-to-repo button: the page commits
    its draft lines to data/feedback.jsonl through the GitHub Contents API with a token kept in the browser (the
    same module and token the study hub uses), so the user never pastes the box to an agent."""
    effective = float(prefs.candidate.get("effective_yoe", 2))
    visible = [j for j in jobs if not j.excluded and not j.hidden]          # applied jobs stay in place, muted
    visible.sort(key=lambda j: (-j.rank_score, -j.score, j.company, j.title))
    applied = sorted((j for j in jobs if j.verdict == "applied" and not j.excluded), key=lambda j: j.company)
    archive = archive if archive is not None else [
        {"id": j.id, "title": j.title, "company": j.company, "url": j.url, "status": j.status, "applied_on": "", "note": "", "first_seen": j.first_seen}
        for j in applied]
    excluded = [j for j in jobs if j.excluded and not j.hidden]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for j in excluded:
        groups[j.exclude_reason].append({"title": j.title, "company": j.company, "url": j.url})
    excluded_groups = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    counts = {
        "visible": len(visible), "new": sum(1 for j in visible if j.status == "new"),
        "reviewed": sum(1 for j in visible if j.review), "applied": len(applied), "excluded": len(excluded),
        "hidden": sum(1 for j in jobs if j.hidden),
    }
    companies = sorted(Counter(j.company for j in visible).items())
    metros = [m for m in ("nyc", "bay", "remote_us", "other_us", "unknown") if any(j.location_class == m for j in visible)]
    maxes = {k: int(v) for k, v in prefs.weights.items()}
    tpl = _env().get_template("report.html.j2")
    return tpl.render(
        date=date, generated_at=meta.get("generated_at", ""), sources=meta.get("sources", []),
        warnings=meta.get("warnings", []), counts=counts, companies=companies, metros=metros,
        effective_yoe=effective, maxes=maxes,
        cards=[_card(j, effective, maxes, prefs.referrals, referral_marks, referral_companies, connections, reposts) for j in visible],
        archive=archive, excluded_groups=excluded_groups,
        write=write or None, hubwrite_js=(TEMPLATES / "hubwrite.js").read_text() if write else "",
    )


def write_report(html: str, reports_dir: Path, date: str) -> tuple[Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    dated = reports_dir / f"{date}.html"
    index = reports_dir / "index.html"
    dated.write_text(html)
    index.write_text(html)
    return dated, index
