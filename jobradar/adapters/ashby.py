"""Ashby public job board: https://api.ashbyhq.com/posting-api/job-board/<board>?includeCompensation=true"""
from __future__ import annotations

from typing import Any

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, iso_to_ts, register

URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def parse_board(payload: dict[str, Any], cfg: CompanyConfig) -> list[RawJob]:
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise AdapterError(f"ashby:{cfg.board}: unexpected payload {str(payload)[:200]}")
    out: list[RawJob] = []
    for j in payload["jobs"]:
        if j.get("isListed") is False:
            continue
        locs = [str(j["location"])] if j.get("location") else []
        locs += [str(s["location"]) for s in j.get("secondaryLocations") or [] if s.get("location")]
        out.append(RawJob(
            company=cfg.key, source_id=str(j["id"]), title=str(j.get("title", "")).strip(),
            url=str(j.get("jobUrl", "")), apply_url=str(j.get("applyUrl") or j.get("jobUrl", "")),
            locations=locs, description_html=str(j.get("descriptionHtml") or j.get("descriptionPlain") or ""),
            posted_ts=iso_to_ts(j.get("publishedAt")),
            arrangement_hint="remote" if j.get("isRemote") else "",
            extra={"company_name": cfg.name, "department": j.get("department"), "team": j.get("team"),
                   "employment_type": j.get("employmentType")},
        ))
    return out


@register
class AshbyAdapter:
    kind = "ashby"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        if not cfg.board:
            raise AdapterError(f"ashby:{cfg.key}: 'board' is required in companies.yaml")
        payload = client.get_json(URL.format(board=cfg.board), params={"includeCompensation": "true"}, fixture_key="search")
        return dedupe(parse_board(payload, cfg))

    def enrich(self, raw: RawJob, client) -> RawJob:
        return raw
