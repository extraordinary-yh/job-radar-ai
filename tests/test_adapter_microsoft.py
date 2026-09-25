import json
from pathlib import Path

from jobradar.adapters.base import get_adapter
from jobradar.adapters.microsoft import parse_detail, parse_search
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "microsoft" / "search.json").read_text())
DETAIL = json.loads((FIXTURES / "microsoft" / "detail.json").read_text())


def test_parse_search_maps_fields():
    jobs, count = parse_search(SEARCH)
    assert count >= 3 and len(jobs) == 3
    j = jobs[0]
    assert j.company == "microsoft" and j.source_id == str(DETAIL["id"])
    assert j.title and j.url == f"https://apply.careers.microsoft.com/careers/job/{j.source_id}"
    assert any(", US" in loc for loc in j.locations)
    assert j.arrangement_hint in {"onsite", "hybrid", "remote", ""}
    assert j.posted_ts and j.posted_ts > 1_700_000_000
    assert j.extra["company_name"] == "Microsoft" and j.extra["display_job_id"]


def test_parse_detail_fills_description_and_url():
    raw = parse_search(SEARCH)[0][0]
    enriched = parse_detail(DETAIL, raw)
    assert "<" in enriched.description_html and len(enriched.description_html) > 500
    assert enriched.url.startswith("https://apply.careers.microsoft.com/careers/job/")


def test_normalized_microsoft_job_has_min_qualifications():
    raw = parse_detail(DETAIL, parse_search(SEARCH)[0][0])
    job = normalize(raw, "Microsoft")
    assert job.qualifications_min and job.location_class in {"nyc", "bay", "remote_us", "other_us"}


def test_adapter_search_and_enrich_offline():
    cfg = CompanyConfig(name="Microsoft", key="microsoft", adapter="microsoft",
                        queries=["software engineer", "ai engineer"], locations=["New York, United States"], max_pages=2)
    client = FixtureClient(FIXTURES, "microsoft")
    adapter = get_adapter("microsoft")
    jobs = adapter.search(cfg, client)
    assert len(jobs) == 3
    assert adapter.enrich(jobs[0], client).description_html
