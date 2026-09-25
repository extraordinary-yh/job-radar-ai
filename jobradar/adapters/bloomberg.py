"""Bloomberg careers on Avature: HTML search results (12 per page) and HTML detail pages."""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import quote

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, register

BASE = "https://bloomberg.avature.net/careers"
PAGE_SIZE = 12
_ARTICLE_RE = re.compile(r'<article class="article article--result".*?</article>', re.S)
_TITLE_RE = re.compile(r'article__header__text__title[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_LOC_RE = re.compile(r'list-item-location">([^<]*)<')
_TOTAL_RE = re.compile(r'(\d[\d,]*)\s+results')
_ID_RE = re.compile(r'/JobDetail/[^/]+/(\d+)')
_TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.S)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def parse_search_page(html: str, company_key: str = "bloomberg") -> tuple[list[RawJob], int]:
    articles = _ARTICLE_RE.findall(html)
    m = _TOTAL_RE.search(html)
    total = int(m.group(1).replace(",", "")) if m else len(articles)
    if not articles and "SearchJobs" not in html and "article" not in html:
        raise AdapterError("bloomberg: no result articles found (page layout changed?)")
    out: list[RawJob] = []
    for art in articles:
        t = _TITLE_RE.search(art)
        if not t:
            continue
        url = htmllib.unescape(t.group(1)).split("?")[0]
        idm = _ID_RE.search(url)
        sid = idm.group(1) if idm else url.rstrip("/").rsplit("/", 1)[-1]
        out.append(RawJob(
            company=company_key, source_id=sid, title=_clean(t.group(2)), url=url, apply_url=url,
            locations=[_clean(l) for l in _LOC_RE.findall(art) if _clean(l)],
            extra={"company_name": "Bloomberg"},
        ))
    return out, total


_ANY_ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.S)


def parse_detail_page(html: str, raw: RawJob) -> RawJob:
    # The page has several <article> blocks (title, facts, description, related jobs);
    # the description is the one carrying rich-text fields. Fall back to the longest block.
    blocks = _ANY_ARTICLE_RE.findall(html)
    if not blocks:
        raise AdapterError(f"bloomberg: no <article> blocks on {raw.url} (layout changed?)")
    rich = [b for b in blocks if "field--rich-text" in b]
    raw.description_html = max(rich or blocks, key=len)
    if not raw.title:
        m = _TITLE_TAG_RE.search(html)
        raw.title = _clean(m.group(1)).split(" - ")[0] if m else raw.title
    return raw


def search_url(query: str, offset: int) -> str:
    return f"{BASE}/SearchJobs/{quote(query)}/?jobRecordsPerPage={PAGE_SIZE}&jobOffset={offset}"


@register
class BloombergAdapter:
    kind = "bloomberg"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        found: list[RawJob] = []
        for query in cfg.queries or ["software engineer"]:
            for page in range(cfg.max_pages):
                offset = page * PAGE_SIZE
                jobs, total = parse_search_page(client.get_text(search_url(query, offset), fixture_key="search"), cfg.key)
                found.extend(jobs)
                if len(jobs) < PAGE_SIZE or offset + PAGE_SIZE >= total:
                    break
        return dedupe(found)

    def enrich(self, raw: RawJob, client) -> RawJob:
        return parse_detail_page(client.get_text(raw.url, fixture_key="detail"), raw)
