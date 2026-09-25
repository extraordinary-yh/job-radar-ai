"""Microsoft Careers on Eightfold.

Flow verified 2026-09-01: GET /careers (sets session cookies) → GET /api/pcsx/search (JSON) →
GET /api/apply/v2/jobs/<id>?domain=microsoft.com (JSON with job_description HTML).
"""
from __future__ import annotations

from typing import Any

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, register

BASE = "https://apply.careers.microsoft.com"
CAREERS_URL = f"{BASE}/careers"
SEARCH_URL = f"{BASE}/api/pcsx/search"
DETAIL_URL = f"{BASE}/api/apply/v2/jobs/{{id}}"
DOMAIN = "microsoft.com"
PAGE_SIZE = 10
HEADERS = {"Referer": CAREERS_URL}


def parse_search(payload: dict[str, Any], company_key: str = "microsoft") -> tuple[list[RawJob], int]:
    data = payload.get("data")
    if not isinstance(data, dict) or "positions" not in data:
        raise AdapterError(f"microsoft: unexpected search payload: {str(payload)[:200]}")
    out: list[RawJob] = []
    for p in data.get("positions") or []:
        pid = str(p["id"])
        url = f"{BASE}/careers/job/{pid}"
        out.append(RawJob(
            company=company_key, source_id=pid, title=str(p.get("name", "")).strip(), url=url, apply_url=url,
            locations=[str(x) for x in (p.get("standardizedLocations") or p.get("locations") or [])],
            posted_ts=p.get("postedTs") or p.get("creationTs"),
            arrangement_hint=str(p.get("workLocationOption") or ""),
            extra={"company_name": "Microsoft", "display_job_id": str(p.get("displayJobId") or ""),
                   "department": str(p.get("department") or "")},
        ))
    return out, int(data.get("count") or 0)


def parse_detail(payload: dict[str, Any], raw: RawJob) -> RawJob:
    d = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw.description_html = str(d.get("job_description") or "")
    raw.arrangement_hint = raw.arrangement_hint or str(d.get("work_location_option") or "")
    if d.get("canonicalPositionUrl"):
        raw.url = str(d["canonicalPositionUrl"])
        raw.apply_url = raw.url
    if not raw.locations and d.get("locations"):
        raw.locations = [str(x) for x in d["locations"]]
    return raw


@register
class MicrosoftAdapter:
    kind = "microsoft"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        client.get_text(CAREERS_URL, fixture_key="session")      # cookies for the pcsx API
        found: list[RawJob] = []
        for query in cfg.queries or ["software engineer"]:
            for location in cfg.locations or [""]:
                for page in range(cfg.max_pages):
                    start = page * PAGE_SIZE
                    params = {"domain": DOMAIN, "query": query, "start": start, "num": PAGE_SIZE, "sort_by": "relevance"}
                    if location:
                        params["location"] = location
                    payload = client.get_json(SEARCH_URL, params=params, headers=HEADERS, fixture_key="search")
                    jobs, count = parse_search(payload, cfg.key)
                    found.extend(jobs)
                    if len(jobs) < PAGE_SIZE or start + PAGE_SIZE >= count:
                        break
        return dedupe(found)

    def enrich(self, raw: RawJob, client) -> RawJob:
        payload = client.get_json(DETAIL_URL.format(id=raw.source_id), params={"domain": DOMAIN},
                                  headers=HEADERS, fixture_key="detail")
        return parse_detail(payload, raw)
