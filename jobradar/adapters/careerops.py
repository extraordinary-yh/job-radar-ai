"""Any of career-ops's ~100 job-board providers as a job-radar source.

companies.yaml entry:
  - name: Amazon
    key: amazon_nyc
    adapter: careerops
    provider: amazon                 # optional; auto-detected from careers_url for most ATSes
    careers_url: https://www.amazon.jobs/...   # or api:
    amazon: {base_query: "software development engineer", normalized_location: ["New York, New York, USA"]}
    aggregator: false                # true for multi-employer boards: the posting's own company name is used

Unknown keys pass straight through to the provider (see vendor/career-ops/docs/SUPPORTED_JOB_BOARDS.md).
Providers return list-page data only; enrich() fetches the posting page when no description came back.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any

from ..careerops import CareerOpsError, run_json
from ..config import CompanyConfig, repo_root
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, register

RUNNER = "scripts/careerops/fetch.mjs"
PASSTHROUGH_SKIP = {"aggregator", "pace_seconds", "h1b_name"}
ID_SEGMENT = re.compile(r"^(\d{4,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I)
MAX_PAGE_CHARS = 300_000
JSONLD_SCRIPT = re.compile(r"<script\b[^>]*\btype\s*=\s*['\"]application/ld\+json['\"][^>]*>(.*?)</script\s*>", re.I | re.S)


def parse_eightfold_detail(html: str) -> tuple[str, int | None]:
    """Read the public JobPosting, excluding Eightfold's scripts and site config."""
    def postings(value):
        if isinstance(value, list):
            for item in value:
                yield from postings(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
            if "JobPosting" in types:
                yield value
            yield from postings(value.get("@graph"))

    for script in JSONLD_SCRIPT.findall(html):
        try:
            payload = json.loads(script)
        except json.JSONDecodeError:
            continue
        for posting in postings(payload):
            description = posting.get("description")
            if not isinstance(description, str) or not description.strip():
                continue
            posted_ts = None
            try:
                posted = dt.datetime.fromisoformat(posting["datePosted"])
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=dt.timezone.utc)
                posted_ts = int(posted.timestamp())
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
            return description, posted_ts
    raise AdapterError("eightfold: posting page has no JobPosting description")


def build_entry(cfg: CompanyConfig) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": cfg.name}
    if cfg.max_pages > 1:
        entry["max_pages"] = cfg.max_pages
    for k, v in cfg.extra.items():
        if k not in PASSTHROUGH_SKIP:
            entry[k] = v
    if "provider" not in entry and "careers_url" not in entry and "api" not in entry:
        raise AdapterError(f"careerops:{cfg.key}: set provider:, careers_url: or api: in companies.yaml")
    return entry


def source_id_for(url: str, dedup_key: str | None) -> str:
    if dedup_key:
        return dedup_key
    for seg in reversed(url.split("?", 1)[0].rstrip("/").split("/")):
        if ID_SEGMENT.match(seg):
            return seg.lower()
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def parse_jobs(payload: dict[str, Any], cfg: CompanyConfig) -> list[RawJob]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise AdapterError(f"careerops:{cfg.key}: unexpected runner output {str(payload)[:200]}")
    aggregator = bool(cfg.extra.get("aggregator"))
    out: list[RawJob] = []
    for j in payload["jobs"]:
        url = str(j.get("url") or "")
        title = str(j.get("title") or "").strip()
        if not url or not title:
            continue
        posted = j.get("postedAt")
        company_name = (str(j.get("company") or "").strip() or cfg.name) if aggregator else cfg.name
        out.append(RawJob(
            company=cfg.key, source_id=source_id_for(url, j.get("dedupKey")), title=title, url=url, apply_url=url,
            locations=[str(j["location"])] if j.get("location") else [],
            description_html=str(j.get("description") or ""),
            posted_ts=int(posted / 1000) if isinstance(posted, (int, float)) and posted > 0 else None,
            extra={"company_name": company_name, "provider": str(payload.get("provider") or ""),
                   "source_company": str(j.get("company") or "")},
        ))
    return out


@register
class CareerOpsAdapter:
    kind = "careerops"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        entry = build_entry(cfg)
        if hasattr(client, "dir"):                                   # FixtureClient: recorded runner output
            payload = client.get_json("", fixture_key="search")
        else:
            try:
                payload = run_json(repo_root(), RUNNER, stdin=json.dumps(entry), timeout=600)
            except CareerOpsError as e:
                raise AdapterError(f"careerops:{cfg.key}: {e}") from None
        return dedupe(parse_jobs(payload, cfg))

    def enrich(self, raw: RawJob, client) -> RawJob:
        # Amazon's search API returns a short non-empty teaser.  It looks like a
        # description to the generic adapter, but omits Basic Qualifications
        # (including the non-internship years requirement), so it must not
        # suppress the posting-page fetch.
        if raw.description_html.strip() and raw.extra.get("provider") != "amazon":
            return raw
        html = client.get_text(raw.url, fixture_key="detail")
        if raw.extra.get("provider") == "eightfold":
            raw.description_html, posted_ts = parse_eightfold_detail(str(html)[:MAX_PAGE_CHARS])
            if posted_ts is not None:
                raw.posted_ts = posted_ts
            raw.extra["enriched"] = "jsonld"
            return raw
        raw.description_html = str(html)[:MAX_PAGE_CHARS]
        raw.extra["enriched"] = "page"
        return raw
