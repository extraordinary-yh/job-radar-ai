"""Google Careers: server-rendered results page with an embedded AF_initDataCallback JSON payload.

Payload layout (ds:1) observed 2026-09-01: data[0] = list of jobs, data[2] = total count.
Job entry indexes: 0 id, 1 title, 2 apply url, 3 [_, responsibilities html], 4 [_, qualifications html],
7 company name, 9 locations [[display, ...], ...], 10 [_, about html], 12 [posted seconds, nanos].
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, register

BASE = "https://www.google.com/about/careers/applications/jobs/results/"
PAGE_SIZE = 20
_DS_RE = re.compile(r"AF_initDataCallback\(\{key: '(ds:\d+)'.*?data:(.*?), sideChannel", re.S)


def extract_ds(html: str, key: str = "ds:1") -> Any | None:
    for m in _DS_RE.finditer(html):
        if m.group(1) == key:
            return json.loads(m.group(2))
    return None


def _pair(v: Any) -> str:
    return v[1] if isinstance(v, list) and len(v) > 1 and isinstance(v[1], str) else ""


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_results_page(html: str, company_key: str = "google") -> tuple[list[RawJob], int]:
    data = extract_ds(html, "ds:1")
    if data is None:
        raise AdapterError("google: ds:1 payload not found (page layout changed?)")
    entries = data[0] or []
    total = int(data[2] or 0) if len(data) > 2 and data[2] is not None else len(entries)
    out: list[RawJob] = []
    for j in entries:
        jid, title = str(j[0]), str(j[1])
        locs = [loc[0] for loc in (j[9] or []) if loc and loc[0]] if len(j) > 9 else []
        posted = j[12][0] if len(j) > 12 and isinstance(j[12], list) and j[12] else None
        out.append(RawJob(
            company=company_key, source_id=jid, title=title, url=f"{BASE}{jid}-{_slug(title)}",
            apply_url=str(j[2] or ""), locations=locs,
            description_html=_pair(j[10]) if len(j) > 10 else "",
            responsibilities_html=_pair(j[3]), qualifications_html=_pair(j[4]),
            posted_ts=int(posted) if posted else None,
            extra={"company_name": str(j[7]) if len(j) > 7 and j[7] else "Google"},
        ))
    return out, total


def search_url(query: str, locations: list[str], page: int) -> str:
    params: list[tuple[str, str]] = [("q", f'"{query}"')]
    params += [("location", loc) for loc in locations]
    if page > 1:
        params.append(("page", str(page)))
    return BASE + "?" + urlencode(params)


@register
class GoogleAdapter:
    kind = "google"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        found: list[RawJob] = []
        for query in cfg.queries or ["software engineer"]:
            for page in range(1, cfg.max_pages + 1):
                html = client.get_text(search_url(query, cfg.locations, page), fixture_key="search")
                jobs, total = parse_results_page(html, cfg.key)
                found.extend(jobs)
                if len(jobs) < PAGE_SIZE or page * PAGE_SIZE >= total:
                    break
        return dedupe(found)

    def enrich(self, raw: RawJob, client) -> RawJob:
        return raw   # search payload already carries qualifications and responsibilities
