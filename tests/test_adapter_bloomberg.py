from pathlib import Path

from jobradar.adapters.base import get_adapter
from jobradar.adapters.bloomberg import parse_detail_page, parse_search_page, search_url
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = (FIXTURES / "bloomberg" / "search.html").read_text()
DETAIL = (FIXTURES / "bloomberg" / "detail.html").read_text()


def test_parse_search_page_maps_fields():
    jobs, total = parse_search_page(SEARCH)
    assert total > 12 and len(jobs) == 3
    j = jobs[0]
    assert j.company == "bloomberg" and j.source_id.isdigit()
    assert j.url.startswith("https://bloomberg.avature.net/careers/JobDetail/") and j.url.endswith("/" + j.source_id)
    assert j.title and "\n" not in j.title
    assert j.locations and j.extra["company_name"] == "Bloomberg"


def test_parse_detail_page_fills_description():
    raw = parse_search_page(SEARCH)[0][0]
    enriched = parse_detail_page(DETAIL, raw)
    assert len(enriched.description_html) > 500
    job = normalize(enriched, "Bloomberg")
    assert "need to have" in job.qualifications_min.lower()
    assert job.yoe_min is not None


def test_search_url():
    assert search_url("machine learning", 24) == "https://bloomberg.avature.net/careers/SearchJobs/machine%20learning/?jobRecordsPerPage=12&jobOffset=24"


def test_adapter_offline():
    cfg = CompanyConfig(name="Bloomberg", key="bloomberg", adapter="bloomberg", queries=["software engineer"], max_pages=3)
    client = FixtureClient(FIXTURES, "bloomberg")
    adapter = get_adapter("bloomberg")
    jobs = adapter.search(cfg, client)
    assert len(jobs) == 3
    assert adapter.enrich(jobs[0], client).description_html
