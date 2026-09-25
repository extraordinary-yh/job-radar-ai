"""Greenhouse public job board: https://boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true"""
from __future__ import annotations

from typing import Any

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, iso_to_ts, register

URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def parse_board(payload: dict[str, Any], cfg: CompanyConfig) -> list[RawJob]:
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise AdapterError(f"greenhouse:{cfg.board}: unexpected payload {str(payload)[:200]}")
    out: list[RawJob] = []
    for j in payload["jobs"]:
        locs = []
        if isinstance(j.get("location"), dict) and j["location"].get("name"):
            locs.append(str(j["location"]["name"]))
        locs += [str(o["name"]) for o in j.get("offices") or [] if o.get("name") and str(o["name"]) not in locs]
        out.append(RawJob(
            company=cfg.key, source_id=str(j["id"]), title=str(j.get("title", "")).strip(),
            url=str(j.get("absolute_url", "")), apply_url=str(j.get("absolute_url", "")),
            locations=locs, description_html=str(j.get("content") or ""),
            posted_ts=iso_to_ts(j.get("first_published") or j.get("updated_at")),
            extra={"company_name": cfg.name, "departments": [d.get("name") for d in j.get("departments") or []]},
        ))
    return out


@register
class GreenhouseAdapter:
    kind = "greenhouse"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        if not cfg.board:
            raise AdapterError(f"greenhouse:{cfg.key}: 'board' is required in companies.yaml")
        payload = client.get_json(URL.format(board=cfg.board), params={"content": "true"}, fixture_key="search")
        return dedupe(parse_board(payload, cfg))

    def enrich(self, raw: RawJob, client) -> RawJob:
        return raw
