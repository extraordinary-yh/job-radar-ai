from pathlib import Path

from jobradar.adapters.apple import extract_state, parse_detail_page, parse_search_page, search_url
from jobradar.adapters.base import get_adapter
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = (FIXTURES / "apple" / "search.html").read_text()
DETAIL = (FIXTURES / "apple" / "detail.html").read_text()


def test_extract_state_finds_hydration_blob():
    state = extract_state(SEARCH)
    assert "loaderData" in state and len(state["loaderData"]["search"]["searchResults"]) == 3


def test_parse_search_page_maps_fields():
    jobs, total = parse_search_page(SEARCH)
    assert total > 20 and len(jobs) == 3
    j = jobs[0]
    assert j.company == "apple" and j.source_id.isdigit()
    assert j.url.startswith("https://jobs.apple.com/en-us/details/" + j.source_id + "/")
    assert j.locations and all("United States" in loc or "New York" in loc for loc in j.locations)
    assert j.posted_ts and j.posted_ts > 1_700_000_000
    assert j.description_html and j.extra["company_name"] == "Apple"


def test_parse_detail_page_fills_qualifications_and_metro():
    raw = parse_search_page(SEARCH)[0][0]
    enriched = parse_detail_page(DETAIL, raw)
    assert "Minimum Qualifications" in enriched.qualifications_html
    assert enriched.description_html and enriched.locations
    job = normalize(enriched, "Apple")
    assert job.qualifications_min.startswith("Minimum Qualifications")
    assert job.location_class in {"nyc", "bay", "remote_us", "other_us"}


def test_search_url():
    url = search_url("software engineer", "new-york-city-NYC", 2)
    assert url.startswith("https://jobs.apple.com/en-us/search?") and "search=software+engineer" in url
    assert "location=new-york-city-NYC" in url and "page=2" in url


def test_adapter_offline():
    cfg = CompanyConfig(name="Apple", key="apple", adapter="apple", queries=["software engineer"],
                        locations=["new-york-city-NYC"], max_pages=3)
    client = FixtureClient(FIXTURES, "apple")
    adapter = get_adapter("apple")
    jobs = adapter.search(cfg, client)
    assert len(jobs) == 3
    assert "Minimum Qualifications" in adapter.enrich(jobs[0], client).qualifications_html
