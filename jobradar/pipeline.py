"""Orchestrates one run: fetch → normalize → store → score → feedback → review → render."""
from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import adapters  # noqa: F401  (registers adapters)
from .adapters.base import get_adapter
from .config import CompanyConfig, Preferences, load_companies, load_preferences
from .errors import AdapterError
from .feedback import applied_archive, apply_feedback, company_ignores, latest_verdicts, referral_companies, referral_marks
from . import connections as connections_mod, followup, h1b, liveness, reposts
from .http import FixtureClient, HttpClient
from .models import Job, RawJob, SourceResult, job_id
from .normalize import classify_location, normalize, renormalize
from .render import render_report, write_report
from .review import apply_reviews, load_review_history, load_reviews, select_candidates, write_candidates
from .score import apply_scores, match_title_family
from .store import SeenStore, breakage_warnings, list_snapshots, load_snapshot, record_health, save_snapshot

DETAIL_FIELDS = ("description_text", "responsibilities", "qualifications_min", "qualifications_pref",
                 "yoe_min", "yoe_max", "flags", "posted_at", "apply_url")


@dataclass
class RunResult:
    date: str
    jobs: list[Job] = field(default_factory=list)
    sources: list[SourceResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report_path: Path | None = None
    snapshot_path: Path | None = None
    candidates_path: Path | None = None
    reviewed: int = 0


def carry_forward(job: Job, prev: Job) -> None:
    for f in DETAIL_FIELDS:
        cur = getattr(job, f)
        if cur in (None, "", []):
            setattr(job, f, getattr(prev, f))
    if job.arrangement == "unknown" and prev.arrangement != "unknown":
        job.arrangement = prev.arrangement


def _needs_detail(raw: RawJob, cfg: CompanyConfig, prefs: Preferences) -> bool:
    if prefs.locations.get("exclude_non_us", True) and classify_location(raw.locations) == "non_us":
        return False
    family, excluded = match_title_family(raw.title, prefs)
    return excluded is None


def fetch_company(cfg: CompanyConfig, client, store: SeenStore, prefs: Preferences, prev: dict[str, Job],
                  today: str) -> list[Job]:
    adapter = get_adapter(cfg.adapter)
    jobs: list[Job] = []
    for raw in adapter.search(cfg, client):
        jid = job_id(cfg.key, raw.source_id)
        # career-ops' Amazon search responses contain a teaser, not the Basic
        # Qualifications section.  Retry records that still have no parsed
        # minimum qualifications so a previous teaser-only run self-heals.
        amazon_detail_missing = (cfg.adapter == "careerops" and raw.extra.get("provider") == "amazon"
                                 and jid in prev and not prev[jid].qualifications_min)
        fresh = jid not in prev or store.detail_stale(jid, today) or amazon_detail_missing
        if fresh and _needs_detail(raw, cfg, prefs):
            try:
                raw = adapter.enrich(raw, client)
                store.mark_detail_fetched(jid, today)
            except (AdapterError, FileNotFoundError) as e:
                raw.extra["enrich_error"] = str(e)[:200]
        job = normalize(raw, str(raw.extra.get("company_name") or cfg.name))   # aggregators carry the employer per posting
        if jid in prev:
            carry_forward(job, prev[jid])
        jobs.append(job)
    return jobs


def _previous_jobs(root: Path, date: str) -> dict[str, Job]:
    snaps = [p for p in list_snapshots(root / "data" / "jobs") if p.stem <= date]
    if not snaps:
        return {}
    _, jobs = load_snapshot(snaps[-1])
    return {j.id: j for j in jobs}


def _prune_raw(raw_root: Path, date: str, keep_days: int = 7) -> None:
    if not raw_root.exists():
        return
    today = dt.date.fromisoformat(date)
    for d in raw_root.iterdir():
        try:
            if (today - dt.date.fromisoformat(d.name)).days > keep_days:
                shutil.rmtree(d, ignore_errors=True)
        except ValueError:
            continue


def run(root: Path, date: str, *, offline: bool = False, fixtures_root: Path | None = None,
        company_filter: set[str] | None = None, review_path: Path | None = None,
        skip_fetch: bool = False) -> RunResult:
    root = Path(root)
    prefs = load_preferences(root / "profile" / "preferences.yaml")
    companies = [c for c in load_companies(root / "config" / "companies.yaml")
                 if c.enabled and (not company_filter or c.key in company_filter)]
    result = RunResult(date=date)
    store = SeenStore(root / "data" / "seen.json")

    if skip_fetch:
        snap = root / "data" / "jobs" / f"{date}.json"
        if not snap.exists():
            raise FileNotFoundError(f"no snapshot for {date}; run without --skip-fetch first")
        meta, jobs = load_snapshot(snap)
        for job in jobs:
            renormalize(job)                       # parser fixes apply on re-render
        result.sources = [SourceResult(**s) for s in meta.get("sources", [])]
    else:
        prev = _previous_jobs(root, date)
        jobs = []
        fetched_ok: set[str] = set()
        for cfg in companies:
            client = FixtureClient(fixtures_root or root / "tests" / "fixtures", cfg.adapter) if offline \
                else HttpClient(raw_dir=root / "data" / "raw" / date / cfg.key, pace_seconds=float(cfg.extra.get("pace_seconds", 0.5)))
            try:
                found = fetch_company(cfg, client, store, prefs, prev, date)
                jobs.extend(found)
                fetched_ok.add(cfg.key)
                result.sources.append(SourceResult(cfg.key, True, len(found)))
            except Exception as e:   # one source never kills the run
                result.sources.append(SourceResult(cfg.key, False, 0, f"{type(e).__name__}: {str(e)[:300]}"))
            finally:
                client.close()
        if company_filter:
            today_snap = root / "data" / "jobs" / f"{date}.json"
            if today_snap.exists():                     # partial run: keep the other companies' jobs from today
                _, kept = load_snapshot(today_snap)
                jobs.extend(j for j in kept if j.id.split(":", 1)[0] not in company_filter)
        store.update(jobs, date, fetched_ok)
        store.save()
        record_health(root / "data" / "health.json", date, result.sources)
        _prune_raw(root / "data" / "raw", date)

    by_key = {c.key: c for c in load_companies(root / "config" / "companies.yaml")}
    for job in jobs:
        cfg = by_key.get(job.id.split(":", 1)[0])
        if cfg is not None:
            job.company_size, job.company_max_yoe = cfg.size, cfg.max_yoe
    sidecar_warnings: list[str] = []
    repost_index: dict[str, dict] = {}
    if not offline:
        repost_index = reposts.annotate(jobs, root, SeenStore(root / "data" / "seen.json").data["jobs"], date, warnings=sidecar_warnings)
    apply_scores(jobs, prefs, date)
    feedback_path = root / "data" / "feedback.jsonl"
    apply_feedback(jobs, latest_verdicts(feedback_path), company_ignores(feedback_path))
    if not offline:                                   # after scoring: only companies with a visible job are worth a lookup
        aliases = {c.name: str(c.extra["h1b_name"]) for c in by_key.values() if c.extra.get("h1b_name")}
        h1b.annotate(jobs, root, date, warnings=sidecar_warnings, aliases=aliases)

    reviews_file = root / "data" / "reviews" / f"{date}.json"
    if review_path is not None:
        reviews_file.parent.mkdir(parents=True, exist_ok=True)
        if Path(review_path).resolve() != reviews_file.resolve():
            shutil.copy(review_path, reviews_file)
    reviews = {**load_review_history(root / "data" / "reviews"), **load_reviews(reviews_file)}   # today's file wins
    result.reviewed = apply_reviews(jobs, reviews, prefs)

    jobs.sort(key=lambda j: (-j.rank_score, -j.score, j.company, j.title))
    result.warnings = breakage_warnings(root / "data" / "health.json", date)
    result.warnings += [f"{s.company}: fetch failed ({s.error})" for s in result.sources if not s.ok]
    meta = {"sources": [s.__dict__ for s in result.sources], "warnings": result.warnings,
            "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(), "reviewed": result.reviewed}
    result.snapshot_path = save_snapshot(root / "data" / "jobs", date, jobs, meta)
    result.candidates_path = write_candidates(root / "data" / "candidates" / f"{date}.json", select_candidates(jobs, prefs))
    fb = root / "data" / "feedback.jsonl"
    seen_jobs = SeenStore(root / "data" / "seen.json").data["jobs"]
    archive = followup.annotate_archive(applied_archive(fb, seen_jobs, applications_dir=root / "data" / "applications"), date)
    known: dict[str, list[dict[str, str]]] = {}
    if not offline:
        liveness.annotate_archive(archive, root, date, warnings=sidecar_warnings)
        known = connections_mod.annotate(jobs, root, warnings=sidecar_warnings)
    from .publish import load_publish_config
    pub = load_publish_config(root / "config" / "publish.yaml")
    local_board_url = pub.get("local_board_url") if pub.get("feedback_mode") == "local" else None
    write = ({"repo": str(pub["source_repo"]), "branch": str(pub.get("source_branch", "main"))}
             if pub.get("source_repo") and not local_board_url else None)
    html = render_report(jobs, meta, prefs, date, archive=archive, referral_marks=referral_marks(fb),
                         referral_companies=referral_companies(fb, seen_jobs), connections=known, reposts=repost_index,
                         write=write, local_board_url=local_board_url, pinned_jobs=pub.get("pinned_jobs"))
    result.report_path, _ = write_report(html, root / "reports", date)
    result.warnings += sidecar_warnings
    result.jobs = jobs
    return result
