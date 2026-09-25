from pathlib import Path

from jobradar.adapters.base import get_adapter
from jobradar.adapters.google import extract_ds, parse_results_page, search_url
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient

FIXTURES = Path(__file__).parent / "fixtures"
HTML = (FIXTURES / "google" / "search.html").read_text()


def test_extract_ds_returns_payload():
    data = extract_ds(HTML, "ds:1")
    assert isinstance(data, list) and len(data[0]) == 3
    assert extract_ds(HTML, "ds:9") is None


def test_parse_results_page_maps_fields():
    jobs, total = parse_results_page(HTML)
    assert total > 100 and len(jobs) == 3
    j = jobs[0]
    assert j.company == "google" and j.source_id.isdigit()
    assert j.title and j.url.startswith("https://www.google.com/about/careers/applications/jobs/results/" + j.source_id + "-")
    assert j.apply_url.startswith("https://www.google.com/about/careers/applications/")
    assert j.locations and all("," in loc for loc in j.locations)
    assert "<li>" in j.responsibilities_html and "qualifications" in j.qualifications_html.lower()
    assert j.posted_ts and j.posted_ts > 1_700_000_000
    assert j.extra["company_name"] in {"Google", "DeepMind", "YouTube", "GFiber", "Fitbit", "Waymo", "Verily", "X"}


def test_search_url_encodes_query_locations_and_page():
    url = search_url("software engineer", ["New York, NY, USA", "Remote"], 2)
    assert url.startswith("https://www.google.com/about/careers/applications/jobs/results/?")
    assert "q=%22software+engineer%22" in url and url.count("location=") == 2 and "page=2" in url


def test_adapter_search_dedupes_and_stops_on_short_page():
    cfg = CompanyConfig(name="Google", key="google", adapter="google",
                        queries=["software engineer", "ai engineer"], locations=["New York, NY, USA"], max_pages=3)
    jobs = get_adapter("google").search(cfg, FixtureClient(FIXTURES, "google"))
    assert len(jobs) == 3                       # 2 queries x same fixture -> deduped by source_id
    assert get_adapter("google").enrich(jobs[0], None) is jobs[0]
