from pathlib import Path

from jobradar.adapters.base import get_adapter
from jobradar.adapters.linkedin import parse_detail_page, parse_search_page, search_url
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures"
CFG = CompanyConfig(name="LinkedIn", key="linkedin", adapter="linkedin", board="1337", queries=["software engineer"],
                    locations=["United States"], max_pages=2)


def test_parse_search_page_maps_fields():
    jobs = parse_search_page((FIXTURES / "linkedin" / "search.html").read_text(), CFG)
    assert len(jobs) == 3
    j = jobs[0]
    assert j.company == "linkedin" and j.source_id.isdigit() and j.url.startswith("https://www.linkedin.com/jobs/view/")
    assert j.title and j.locations and j.posted_ts and j.extra["company_name"] == "LinkedIn"


def test_parse_detail_page_fills_description():
    raw = parse_search_page((FIXTURES / "linkedin" / "search.html").read_text(), CFG)[0]
    enriched = parse_detail_page((FIXTURES / "linkedin" / "detail.html").read_text(), raw)
    assert len(enriched.description_html) > 300 and enriched.extra["seniority"]
    assert normalize(enriched, "LinkedIn").description_text


def test_search_url():
    assert search_url("software engineer", "1337", "United States", 10) == \
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=software+engineer&f_C=1337&start=10&location=United+States"


def test_adapter_offline():
    client = FixtureClient(FIXTURES, "linkedin")
    adapter = get_adapter("linkedin")
    jobs = adapter.search(CFG, client)
    assert len(jobs) == 3 and adapter.enrich(jobs[0], client).description_html
