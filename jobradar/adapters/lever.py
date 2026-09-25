"""Lever public postings: https://api.lever.co/v0/postings/<board>?mode=json"""
from __future__ import annotations

from typing import Any

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, register

URL = "https://api.lever.co/v0/postings/{board}"
_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}


def parse_board(payload: list[dict[str, Any]], cfg: CompanyConfig) -> list[RawJob]:
    if not isinstance(payload, list):
        raise AdapterError(f"lever:{cfg.board}: unexpected payload {str(payload)[:200]}")
    out: list[RawJob] = []
    for j in payload:
        cats = j.get("categories") or {}
        locs = [str(x) for x in (cats.get("allLocations") or ([cats["location"]] if cats.get("location") else []))]
        lists_html = "".join(f"<h3>{s.get('text', '')}</h3>{s.get('content', '')}" for s in j.get("lists") or [])
        created = j.get("createdAt")
        out.append(RawJob(
            company=cfg.key, source_id=str(j["id"]), title=str(j.get("text", "")).strip(),
            url=str(j.get("hostedUrl", "")), apply_url=str(j.get("applyUrl") or j.get("hostedUrl", "")),
            locations=locs, description_html=str(j.get("description") or "") + lists_html + str(j.get("additional") or ""),
            posted_ts=int(created) // 1000 if created else None,
            arrangement_hint=_WORKPLACE.get(str(j.get("workplaceType") or "").lower(), ""),
            extra={"company_name": cfg.name, "team": cats.get("team"), "commitment": cats.get("commitment")},
        ))
    return out


@register
class LeverAdapter:
    kind = "lever"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        if not cfg.board:
            raise AdapterError(f"lever:{cfg.key}: 'board' is required in companies.yaml")
        payload = client.get_json(URL.format(board=cfg.board), params={"mode": "json"}, fixture_key="search")
        return dedupe(parse_board(payload, cfg))

    def enrich(self, raw: RawJob, client) -> RawJob:
        return raw
