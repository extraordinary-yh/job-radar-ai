"""Apple Jobs: server-rendered search and detail pages that embed their data as
window.__staticRouterHydrationData = JSON.parse("…"). Verified 2026-09-02.

Search: /en-us/search?search=<q>&location=<slug>&page=N → loaderData.search.{searchResults, totalRecords}.
Detail: /en-us/details/<positionId>/<slug> → loaderData.jobDetails.jobsData with description,
minimumQualifications, preferredQualifications, locations (with metro), postDateInGMT, homeOffice.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from typing import Any
from urllib.parse import urlencode

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, iso_to_ts, register

BASE = "https://jobs.apple.com"
PAGE_SIZE = 20
_HYD_RE = re.compile(r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((\".*?\")\);", re.S)


def extract_state(html: str) -> dict[str, Any]:
    m = _HYD_RE.search(html)
    if not m:
        raise AdapterError("apple: hydration data not found (page layout changed?)")
    return json.loads(json.loads(m.group(1)))


def _location_names(locs: list[dict[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for loc in locs or []:
        parts = [loc.get("name") or loc.get("city"), loc.get("stateProvince"), loc.get("countryName")]
        text = ", ".join(str(p) for p in parts if p)
        if text and text not in out:
            out.append(text)
    return out


def _text_html(s: str | None) -> str:
    return "<p>" + htmllib.escape(s).replace("\n", "<br>") + "</p>" if s else ""


def parse_search_page(html: str, company_key: str = "apple") -> tuple[list[RawJob], int]:
    search = extract_state(html).get("loaderData", {}).get("search") or {}
    results = search.get("searchResults") or []
    total = int(search.get("totalRecords") or 0)
    out: list[RawJob] = []
    for r in results:
        pid = str(r.get("positionId") or "")
        if not pid:
            continue
        slug = str(r.get("transformedPostingTitle") or "")
        url = f"{BASE}/en-us/details/{pid}/{slug}".rstrip("/")
        out.append(RawJob(
            company=company_key, source_id=pid, title=str(r.get("postingTitle") or "").strip(), url=url, apply_url=url,
            locations=_location_names(r.get("locations")), description_html=_text_html(r.get("jobSummary")),
            posted_ts=iso_to_ts(r.get("postDateInGMT")), arrangement_hint="remote" if r.get("homeOffice") else "",
            extra={"company_name": "Apple", "team": (r.get("team") or {}).get("teamName"), "req_id": r.get("reqId")},
        ))
    return out, total


def parse_detail_page(html: str, raw: RawJob) -> RawJob:
    jd = extract_state(html).get("loaderData", {}).get("jobDetails", {}).get("jobsData") or {}
    if not jd:
        raise AdapterError(f"apple: jobsData missing on {raw.url}")
    raw.description_html = _text_html(jd.get("description")) or raw.description_html
    quals = ""
    for heading, key in (("Minimum Qualifications", "minimumQualifications"), ("Key Qualifications", "keyQualifications"),
                         ("Preferred Qualifications", "preferredQualifications"), ("Education & Experience", "educationAndExperience")):
        if jd.get(key) and str(jd[key]).strip().lower() != "none":
            quals += f"<h3>{heading}</h3>" + _text_html(str(jd[key]))
    raw.qualifications_html = quals
    locs = _location_names(jd.get("locations"))
    if locs:
        raw.locations = locs
    if jd.get("homeOffice") in (True, "True", "true"):
        raw.arrangement_hint = "remote"
    raw.posted_ts = iso_to_ts(jd.get("postDateInGMT")) or raw.posted_ts
    return raw


def search_url(query: str, location: str, page: int) -> str:
    params = {"search": query, "location": location, "sort": "newest"}
    if page > 1:
        params["page"] = str(page)
    return f"{BASE}/en-us/search?" + urlencode(params)


@register
class AppleAdapter:
    kind = "apple"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        found: list[RawJob] = []
        for query in cfg.queries or ["software engineer"]:
            for location in cfg.locations or ["united-states-USA"]:
                for page in range(1, cfg.max_pages + 1):
                    jobs, total = parse_search_page(client.get_text(search_url(query, location, page), fixture_key="search"), cfg.key)
                    found.extend(jobs)
                    if len(jobs) < PAGE_SIZE or page * PAGE_SIZE >= total:
                        break
        return dedupe(found)

    def enrich(self, raw: RawJob, client) -> RawJob:
        return parse_detail_page(client.get_text(raw.url, fixture_key="detail"), raw)
