"""Core data types shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


def job_id(company_key: str, source_id: str) -> str:
    return f"{company_key}:{source_id}"


@dataclass
class RawJob:
    """What an adapter returns before normalization."""

    company: str            # company key from config, e.g. "google"
    source_id: str
    title: str
    url: str
    apply_url: str = ""
    locations: list[str] = field(default_factory=list)
    description_html: str = ""
    responsibilities_html: str = ""
    qualifications_html: str = ""
    posted_ts: int | None = None          # unix seconds
    arrangement_hint: str = ""            # "remote" | "hybrid" | "onsite" | ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Review:
    """The agent's semantic assessment for one job. `skills` (0..max) replaces the skills keyword points."""

    id: str
    skills: int | None = None     # semantic skills score, 0..preferences.skills.max_points
    fit: int | None = None        # legacy 1..5 rating (converted to skills when skills is absent)
    yoe_match: str = "match"      # under | match | stretch | over
    experience_match: str = "partial"   # strong | partial | weak
    reason: str = ""
    gaps: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Review":
        return cls(
            id=str(d["id"]),
            skills=int(d["skills"]) if d.get("skills") is not None else None,
            fit=int(d["fit"]) if d.get("fit") is not None else None,
            yoe_match=str(d.get("yoe_match", "match")),
            experience_match=str(d.get("experience_match", "partial")),
            reason=str(d.get("reason", ""))[:300],
            gaps=list(d.get("gaps", [])), tags=list(d.get("tags", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "skills": self.skills, "fit": self.fit, "yoe_match": self.yoe_match,
                "experience_match": self.experience_match, "reason": self.reason,
                "gaps": self.gaps, "tags": self.tags}


@dataclass
class SourceResult:
    """Outcome of fetching one company during a run."""

    company: str
    ok: bool
    count: int
    error: str = ""


@dataclass
class Job:
    """A normalized posting. Field order matters only for readability."""

    id: str
    company: str
    title: str
    url: str
    apply_url: str = ""
    company_size: str = "small"       # big | small, from config/companies.yaml
    company_max_yoe: int | None = None  # per-company cap on years asked, from config/companies.yaml
    locations: list[str] = field(default_factory=list)
    location_class: str = "unknown"   # nyc | bay | remote_us | other_us | non_us | unknown
    country: str = ""
    arrangement: str = "unknown"      # remote | hybrid | onsite | unknown
    description_text: str = ""
    responsibilities: str = ""
    qualifications_min: str = ""
    qualifications_pref: str = ""
    yoe_min: int | None = None
    yoe_max: int | None = None
    yoe_pref: int | None = None       # years asked in the *preferred* qualifications, if any
    salary_min: int | None = None     # USD per year, parsed from the posting
    salary_max: int | None = None
    level: str = "unknown"            # intern | new_grad | early | mid | senior | staff | manager | unknown
    flags: list[str] = field(default_factory=list)
    posted_at: str | None = None      # ISO date
    first_seen: str | None = None
    last_seen: str | None = None
    status: str = "new"               # new | open | closed
    score: int = 0
    score_parts: dict[str, int] = field(default_factory=dict)
    excluded: bool = False
    exclude_reason: str = ""
    matched_skills: list[str] = field(default_factory=list)
    review: Review | None = None
    rank_score: float = 0.0
    verdict: str | None = None        # good | bad | applied | ignore
    hidden: bool = False
    h1b_tier: str = ""                # strong | moderate | staffing-shop | weak | none | unknown | "" (not checked)
    h1b_note: str = ""                # one line: employer as filed, LCA/PERM counts, active years

    def to_dict(self) -> dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["review"] = self.review.to_dict() if self.review else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in known and k != "review"}
        job = cls(**kwargs)
        if d.get("review"):
            job.review = Review.from_dict(d["review"])
        return job
