import json
from pathlib import Path

import pytest

from jobradar.adapters.base import get_adapter
from jobradar.adapters.careerops import build_entry, parse_jobs, source_id_for
from jobradar.config import CompanyConfig, load_companies
from jobradar.errors import AdapterError
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def cfg(**extra):
    return CompanyConfig(name="Amazon", key="amazon_nyc", adapter="careerops", size="big", extra=extra)


def test_build_entry_passes_provider_config_through():
    e = build_entry(cfg(provider="amazon", amazon={"base_query": "sde", "normalized_location": ["New York, New York, USA"]}, aggregator=False, h1b_name="Amazon.com Services LLC"))
    assert e == {"name": "Amazon", "provider": "amazon", "amazon": {"base_query": "sde", "normalized_location": ["New York, New York, USA"]}}
    with pytest.raises(AdapterError, match="set provider:"):
        build_entry(cfg())
    c = cfg(careers_url="https://jobs.smartrecruiters.com/Acme")
    c.max_pages = 3
    assert build_entry(c)["max_pages"] == 3 and build_entry(c)["careers_url"].endswith("/Acme")


def test_source_id_prefers_dedup_key_then_numeric_or_uuid_segment_then_hash():
    assert source_id_for("https://x/jobs/1", "R-123") == "R-123"
    assert source_id_for("https://www.amazon.jobs/en/jobs/10530460/software-dev-engineer", None) == "10530460"
    assert source_id_for("https://jobs.lever.co/acme/5F2C1D3E-1111-2222-3333-444444444444/apply", None) == "5f2c1d3e-1111-2222-3333-444444444444"
    assert len(source_id_for("https://acme.example/careers/senior-swe", None)) == 16


def test_parse_jobs_maps_fields_and_company_rule():
    payload = json.loads((FIXTURES / "careerops" / "search.json").read_text())
    raws = parse_jobs(payload, cfg(provider="amazon"))
    assert len(raws) == 3 and raws[0].source_id == "10530460" and raws[0].company == "amazon_nyc"
    assert raws[0].locations == ["New York, New York, USA"] and raws[0].posted_ts == 1788505200
    assert raws[0].extra["company_name"] == "Amazon" and raws[0].extra["source_company"].startswith("Amazon Development Center")
    agg = parse_jobs(payload, cfg(provider="amazon", aggregator=True))
    assert agg[0].extra["company_name"] == "Amazon Development Center U.S., Inc."
    assert normalize(raws[0], raws[0].extra["company_name"]).company == "Amazon"
    with pytest.raises(AdapterError, match="unexpected runner output"):
        parse_jobs({"provider": "amazon"}, cfg(provider="amazon"))


def test_fixture_search_and_page_enrich():
    adapter = get_adapter("careerops")
    client = FixtureClient(FIXTURES, "careerops")
    raws = adapter.search(cfg(provider="amazon"), client)
    assert [r.title for r in raws][:2] == ["Software Dev Engineer, GuardDuty", raws[1].title]
    enriched = adapter.enrich(raws[0], client)
    assert enriched.extra["enriched"] == "page"
    job = normalize(enriched, "Amazon")
    assert job.yoe_min == 3 and "GuardDuty" in job.description_text
    amazon_summary = adapter.enrich(raws[1].__class__(**{**raws[1].__dict__, "description_html": "<p>given</p>",
                                                      "extra": dict(raws[1].extra)}), client)
    assert amazon_summary.extra["enriched"] == "page"
    non_amazon = raws[1].__class__(**{**raws[1].__dict__, "description_html": "<p>given</p>",
                                      "extra": {**raws[1].extra, "provider": "workday"}})
    already = adapter.enrich(non_amazon, client)
    assert "enriched" not in already.extra
