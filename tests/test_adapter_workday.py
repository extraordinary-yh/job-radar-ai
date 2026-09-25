import json
from pathlib import Path

from jobradar.adapters.base import get_adapter
from jobradar.adapters.workday import parse_detail, parse_search
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "workday" / "search.json").read_text())
DETAIL = json.loads((FIXTURES / "workday" / "detail.json").read_text())
CFG = CompanyConfig(name="Salesforce", key="salesforce", adapter="workday", queries=["software engineer"], max_pages=2,
                    extra={"workday": {"host": "salesforce.wd12.myworkdayjobs.com", "tenant": "salesforce", "site": "External_Career_Site"}})


def test_parse_search_maps_fields():
    jobs, total = parse_search(SEARCH, CFG)
    assert total > 20 and len(jobs) == 3
    j = jobs[0]
    assert j.company == "salesforce" and j.source_id.startswith("JR")
    assert j.url.startswith("https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/")
    assert j.extra["company_name"] == "Salesforce" and j.extra["external_path"].startswith("/job/")


def test_parse_detail_fills_description_date_and_location():
    raw = parse_search(SEARCH, CFG)[0][0]
    enriched = parse_detail(DETAIL, raw)
    assert len(enriched.description_html) > 500 and enriched.locations and enriched.posted_ts
    job = normalize(enriched, "Salesforce")
    assert job.description_text and job.posted_at


def test_adapter_offline_search_and_enrich():
    client = FixtureClient(FIXTURES, "workday")
    adapter = get_adapter("workday")
    jobs = adapter.search(CFG, client)
    assert len(jobs) == 3
    assert adapter.enrich(jobs[0], client).description_html


def test_missing_workday_block_is_an_error():
    import pytest
    from jobradar.errors import AdapterError
    with pytest.raises(AdapterError, match="workday.host"):
        get_adapter("workday").search(CompanyConfig(name="X", key="x", adapter="workday"), FixtureClient(FIXTURES, "workday"))
