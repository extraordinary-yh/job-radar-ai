"""Workday-hosted career sites (Salesforce, Adobe, ...): JSON API under /wday/cxs/<tenant>/<site>/.

Config block per company (kept in CompanyConfig.extra["workday"]):
  workday: {host: salesforce.wd12.myworkdayjobs.com, tenant: salesforce, site: External_Career_Site,
            facets: {"<facetParameter>": ["<value id>"]}}     # facets optional, e.g. a country filter
Search: POST /wday/cxs/<tenant>/<site>/jobs {searchText, limit, offset, appliedFacets} -> {total, jobPostings[]}.
Detail: GET  /wday/cxs/<tenant>/<site><externalPath> -> {jobPostingInfo: {jobDescription, location, startDate, ...}}.
"""
from __future__ import annotations

from typing import Any

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, iso_to_ts, register

PAGE_SIZE = 20


def _wd(cfg: CompanyConfig) -> dict[str, Any]:
    wd = cfg.extra.get("workday") or {}
    for key in ("host", "tenant", "site"):
        if not wd.get(key):
            raise AdapterError(f"workday:{cfg.key}: 'workday.{key}' is required in companies.yaml")
    return wd


def parse_search(payload: dict[str, Any], cfg: CompanyConfig) -> tuple[list[RawJob], int]:
    if not isinstance(payload, dict) or "jobPostings" not in payload:
        raise AdapterError(f"workday:{cfg.key}: unexpected search payload {str(payload)[:200]}")
    wd = _wd(cfg)
    out: list[RawJob] = []
    for p in payload.get("jobPostings") or []:
        path = str(p.get("externalPath") or "")
        if not path:
            continue
        sid = path.rsplit("_", 1)[-1] if "_" in path else path.rsplit("/", 1)[-1]
        url = f"https://{wd['host']}/{wd['site']}{path}"
        loc = str(p.get("locationsText") or "").strip()
        out.append(RawJob(
            company=cfg.key, source_id=sid, title=str(p.get("title") or "").strip(), url=url, apply_url=url,
            locations=[loc] if loc and not loc.endswith("Locations") else [],
            extra={"company_name": cfg.name, "posted_text": p.get("postedOn"), "external_path": path,
                   "workday": {"host": wd["host"], "tenant": wd["tenant"], "site": wd["site"]}},
        ))
    return out, int(payload.get("total") or 0)


def parse_detail(payload: dict[str, Any], raw: RawJob) -> RawJob:
    jp = (payload or {}).get("jobPostingInfo") or {}
    if not jp:
        raise AdapterError(f"workday: jobPostingInfo missing on {raw.url}")
    raw.description_html = str(jp.get("jobDescription") or "")
    locs = [str(jp.get("location") or "").strip()]
    extra_locs = jp.get("additionalLocations")
    if isinstance(extra_locs, list):
        locs += [str(x) for x in extra_locs]
    raw.locations = [l for l in locs if l]
    if jp.get("externalUrl"):
        raw.url = raw.apply_url = str(jp["externalUrl"])
    if jp.get("startDate"):
        raw.posted_ts = iso_to_ts(f"{jp['startDate']}T00:00:00Z")
    remote = str(jp.get("remoteType") or "").lower()
    raw.arrangement_hint = "remote" if "remote" in remote else ("hybrid" if "hybrid" in remote else raw.arrangement_hint)
    return raw


@register
class WorkdayAdapter:
    kind = "workday"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        wd = _wd(cfg)
        url = f"https://{wd['host']}/wday/cxs/{wd['tenant']}/{wd['site']}/jobs"
        found: list[RawJob] = []
        for query in cfg.queries or ["software engineer"]:
            for page in range(cfg.max_pages):
                body = {"appliedFacets": wd.get("facets") or {}, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": query}
                jobs, total = parse_search(client.post_json(url, json_body=body, fixture_key="search"), cfg)
                found.extend(jobs)
                if len(jobs) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                    break
        return dedupe(found)

    def enrich(self, raw: RawJob, client) -> RawJob:
        wd = raw.extra["workday"]
        url = f"https://{wd['host']}/wday/cxs/{wd['tenant']}/{wd['site']}{raw.extra['external_path']}"
        return parse_detail(client.get_json(url, fixture_key="detail"), raw)
