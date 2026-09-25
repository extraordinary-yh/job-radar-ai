"""Hacker News "Ask HN: Who is hiring?" — the monthly thread via the public Algolia API.

Native rather than through career-ops's hackernews provider because that provider keeps only
the header line; scoring needs the comment body (skills, years, location). Each top-level
comment is one posting: the conventional first line "Company | Role | Location | ..." gives the
employer and title, the body is the description, and the source id is the comment id.
"""
from __future__ import annotations

import html
import re
from typing import Any

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob
from .base import dedupe, iso_to_ts, register

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
THREAD_RE = re.compile(r"ask\s+hn[:\s]+who\s+is\s+hiring", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"']+")
TAG_RE = re.compile(r"<[^>]+>")


def latest_thread_id(search: dict[str, Any]) -> str:
    for hit in search.get("hits") or []:
        if THREAD_RE.search(str(hit.get("title") or "")):
            return str(hit["objectID"])
    raise AdapterError("hackernews: no 'Ask HN: Who is hiring?' thread in the search results")


def _plain(text: str) -> str:
    t = re.sub(r"<a\s[^>]*href=\"([^\"]+)\"[^>]*>.*?</a>", r"\1", text, flags=re.I | re.S)
    t = re.sub(r"</?(?:p|br|div|li|h[1-6])\b[^>]*>", "\n", t, flags=re.I)
    return html.unescape(TAG_RE.sub(" ", t))


def parse_header(text: str) -> tuple[str, str, str]:
    """(company, title, location) from the first line; title falls back to the whole line."""
    lines = [l.strip() for l in _plain(text).splitlines() if l.strip()]
    first = lines[0] if lines else ""
    parts = [p.strip() for p in first.split("|")]
    strip_url = lambda s: re.sub(r"\s{2,}", " ", URL_RE.sub("", s)).strip(" -–|")
    if len(parts) >= 2:
        company, title = strip_url(parts[0]), strip_url(parts[1])
        location = strip_url(parts[2]) if len(parts) >= 3 else ""
        return company, title or first, location
    return "", strip_url(first) or first, ""


def parse_thread(item: dict[str, Any], cfg: CompanyConfig) -> list[RawJob]:
    out: list[RawJob] = []
    for c in item.get("children") or []:
        text = c.get("text")
        if not text or c.get("deleted") or c.get("dead") or not c.get("id"):
            continue
        company, title, location = parse_header(str(text))
        plain = _plain(str(text))
        m = URL_RE.search(plain)
        permalink = f"https://news.ycombinator.com/item?id={c['id']}"
        out.append(RawJob(
            company=cfg.key, source_id=str(c["id"]), title=title[:200], url=permalink, apply_url=m.group(0).rstrip(".,)") if m else permalink,
            locations=[location] if location else [], description_html=str(text),
            posted_ts=iso_to_ts(c.get("created_at")),
            extra={"company_name": company or cfg.name, "thread": str(item.get("id") or ""), "author": str(c.get("author") or "")},
        ))
    return out


@register
class HackerNewsAdapter:
    kind = "hackernews"

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]:
        search = client.get_json(SEARCH_URL, params={"tags": "story,author_whoishiring", "hitsPerPage": 5}, fixture_key="search")
        tid = latest_thread_id(search)
        item = client.get_json(ITEM_URL.format(id=tid), fixture_key="item")
        if not isinstance(item, dict) or "children" not in item:
            raise AdapterError(f"hackernews: unexpected item payload for {tid}")
        return dedupe(parse_thread(item, cfg))

    def enrich(self, raw: RawJob, client) -> RawJob:
        return raw
