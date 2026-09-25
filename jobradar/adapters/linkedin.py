"""LinkedIn job postings through the public guest API (no login):
search: /jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=&f_C=<companyId>&location=&start=N  (HTML, 10 cards/page)
detail: /jobs-guest/jobs/api/jobPosting/<jobId>                                                     (HTML)
Config: board = LinkedIn company id (LinkedIn itself is 1337); locations = LinkedIn location strings.
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urlencode

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, iso_to_ts, register

BASE = "https://www.linkedin.com"
PAGE_SIZE = 10
_CARD_RE = re.compile(r"<li>.*?</li>", re.S)
_TITLE_RE = re.compile(r'class="base-search-card__title">\s*(.*?)\s*<', re.S)
_COMPANY_RE = re.compile(r'class="base-search-card__subtitle">.*?>\s*(.*?)\s*<', re.S)
_LOC_RE = re.compile(r'class="job-search-card__location">\s*(.*?)\s*<', re.S)
_URL_RE = re.compile(r'href="(https://www\.linkedin\.com/jobs/view/[^"?]+)')
_DATE_RE = re.compile(r'datetime="([^"]+)"')
_ID_RE = re.compile(r"-(\d{6,})/?$")
_DESC_RE = re.compile(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.S)
_CRITERIA_RE = re.compile(r'<h3 class="description__job-criteria-subheader">\s*(.*?)\s*</h3>\s*<span[^>]*>\s*(.*?)\s*</span>', re.S)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def parse_search_page(html: str, cfg: CompanyConfig) -> list[RawJob]:
    out: list[RawJob] = []
    for card in _CARD_RE.findall(html):
        u, t = _URL_RE.search(card), _TITLE_RE.search(card)
        if not (u and t):
            continue
        url = u.group(1)
        idm = _ID_RE.search(url)
        if not idm:
            continue
        loc, d = _LOC_RE.search(card), _DATE_RE.search(card)
        out.append(RawJob(
            company=cfg.key, source_id=idm.group(1), title=_clean(t.group(1)), url=url, apply_url=url,
            locations=[_clean(loc.group(1))] if loc else [],
            posted_ts=iso_to_ts(d.group(1) + "T00:00:00Z") if d else None,
            extra={"company_name": cfg.name},
        ))
    return out


def parse_detail_page(html: str, raw: RawJob) -> RawJob:
    m = _DESC_RE.search(html)
    if not m:
        raise AdapterError(f"linkedin: description missing on {raw.url}")
    raw.description_html = m.group(1)
    criteria = {_clean(k).lower(): _clean(v) for k, v in _CRITERIA_RE.findall(html)}
    raw.extra["seniority"] = criteria.get("seniority level", "")
    raw.extra["employment_type"] = criteria.get("employment type", "")
    return raw


def search_url(query: str, company_id: str, location: str, start: int) -> str:
    params = {"keywords": query, "f_C": company_id, "start": str(start)}
    if location:
        params["location"] = location
    return f"{BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)


@register
class LinkedInAdapter:
    kind = "linkedin"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        if not cfg.board:
            raise AdapterError(f"linkedin:{cfg.key}: 'board' (LinkedIn company id) is required")
        found: list[RawJob] = []
        for query in cfg.queries or ["software engineer"]:
            for location in cfg.locations or ["United States"]:
                for page in range(cfg.max_pages):
                    jobs = parse_search_page(client.get_text(search_url(query, cfg.board, location, page * PAGE_SIZE), fixture_key="search"), cfg)
                    found.extend(jobs)
                    if len(jobs) < PAGE_SIZE:
                        break
        return dedupe(found)

    def enrich(self, raw: RawJob, client) -> RawJob:
        return parse_detail_page(client.get_text(f"{BASE}/jobs-guest/jobs/api/jobPosting/{raw.source_id}", fixture_key="detail"), raw)
