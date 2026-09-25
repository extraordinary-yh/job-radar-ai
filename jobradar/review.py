"""Agent fit review: export candidates, load the agent's reviews, blend into rank_score."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Preferences
from .models import Job, Review
from .score import penalty_points, total_from_parts


def load_reviews(path: Path) -> dict[str, Review]:
    path = Path(path)
    if not path.exists():
        return {}
    doc = json.loads(path.read_text())
    entries = doc.get("reviews", []) if isinstance(doc, dict) else doc
    out: dict[str, Review] = {}
    for e in entries:
        if not e.get("id") or (e.get("skills") is None and e.get("fit") is None):
            continue
        r = Review.from_dict(e)
        if r.fit is not None:
            r.fit = max(1, min(5, r.fit))
        out[r.id] = r
    return out


def load_review_history(reviews_dir: Path) -> dict[str, Review]:
    """Every review ever written, latest file wins per job id (reviews are dated files)."""
    out: dict[str, Review] = {}
    reviews_dir = Path(reviews_dir)
    if not reviews_dir.exists():
        return out
    for path in sorted(reviews_dir.glob("????-??-??.json")):
        out.update(load_reviews(path))
    return out


def review_skill_points(r: Review, prefs: Preferences) -> int:
    """The semantic skills score, clamped; a legacy 1..5 fit maps onto the same scale."""
    max_points = int(prefs.skills["max_points"])
    if r.skills is not None:
        return max(0, min(max_points, int(r.skills)))
    return round((r.fit or 0) * max_points / 5)


def apply_reviews(jobs: list[Job], reviews: dict[str, Review], prefs: Preferences) -> int:
    """Swap the keyword skills points for the agent's semantic score and recompute the total."""
    n = 0
    for job in jobs:
        r = reviews.get(job.id)
        if r is None or job.excluded:
            job.rank_score = float(job.score)
            continue
        job.review = r
        job.score_parts = {**job.score_parts, "skills": review_skill_points(r, prefs)}
        job.score = total_from_parts(job.score_parts, penalty_points(job.flags, prefs))
        job.rank_score = float(job.score)
        n += 1
    return n


def select_candidates(jobs: list[Job], prefs: Preferences) -> list[Job]:
    min_score = int(prefs.review["candidate_min_score"])
    cap = int(prefs.review["max_candidates"])
    eligible = [j for j in jobs if not j.excluded and not j.hidden and (j.score >= min_score or j.status == "new")]
    eligible.sort(key=lambda j: (-j.score, j.company, j.title))
    return eligible[:cap]


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def write_candidates(path: Path, jobs: list[Job]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for j in jobs:
        entries.append({
            "id": j.id, "company": j.company, "title": j.title, "url": j.url, "locations": j.locations,
            "reviewed": j.review is not None, "review_skills": j.review.skills if j.review else None,
            "location_class": j.location_class, "arrangement": j.arrangement, "level": j.level,
            "yoe_min": j.yoe_min, "flags": j.flags, "status": j.status, "posted_at": j.posted_at,
            "score": j.score, "score_parts": j.score_parts, "matched_skills": j.matched_skills,
            "responsibilities": _trim(j.responsibilities, 800),
            "qualifications_min": _trim(j.qualifications_min, 1500),
            "qualifications_pref": _trim(j.qualifications_pref, 600),
            "description_text": _trim(j.description_text, 1500),
        })
    unreviewed = sum(1 for e in entries if not e["reviewed"])
    path.write_text(json.dumps({"unreviewed": unreviewed, "candidates": entries}, indent=1, ensure_ascii=False) + "\n")
    return path


def review_template(date: str, jobs: list[Job]) -> dict[str, Any]:
    return {"date": date, "reviews": [
        {"id": j.id, "skills": None, "yoe_match": "match", "experience_match": "partial", "reason": "", "gaps": [], "tags": []}
        for j in jobs
    ]}
