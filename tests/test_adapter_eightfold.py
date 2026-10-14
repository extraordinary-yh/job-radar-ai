import datetime as dt
import json
from pathlib import Path

import pytest

from jobradar.adapters.base import get_adapter
from jobradar.adapters.careerops import parse_eightfold_detail, parse_jobs
from jobradar.config import CompanyConfig
from jobradar.errors import AdapterError
from jobradar.http import FixtureClient
from jobradar.models import RawJob
from jobradar.normalize import normalize

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_netflix_detail_excludes_site_config_and_uses_posting_date():
    raw = RawJob(company="netflix", source_id="790298118429",
                 title="Distributed Systems Engineer 5 - Content & Business Products",
                 url="https://explore.jobs.netflix.net/careers/job/790298118429",
                 locations=["Remote, United States"], posted_ts=1721692800,
                 extra={"provider": "eightfold"})
    enriched = get_adapter("careerops").enrich(raw, FixtureClient(FIXTURES, "netflix"))
    job = normalize(enriched, "Netflix")
    assert enriched.extra["enriched"] == "jsonld"
    assert job.yoe_min == 5 and "distributed systems" in job.qualifications_min
    assert job.location_class == "remote_us"
    assert job.posted_at == "2026-09-09"
    assert "window." not in job.description_text and "site_config" not in job.description_text


@pytest.mark.parametrize("container", [lambda p: p, lambda p: [p], lambda p: {"@graph": [p]}])
def test_eightfold_jsonld_containers_and_offset_date(container):
    posting = {"@type": ["JobPosting"], "description": "<p>Build product APIs.</p>",
               "datePosted": "2026-09-09T12:00:00-07:00"}
    html = '<script type="application/ld+json">broken</script>'
    html += "<script type='application/ld+json'>" + json.dumps(container(posting)) + "</script>"
    description, timestamp = parse_eightfold_detail(html)
    assert description == posting["description"]
    assert timestamp == int(dt.datetime(2026, 9, 9, 19, tzinfo=dt.timezone.utc).timestamp())


@pytest.mark.parametrize("date", [None, "invalid"])
def test_eightfold_invalid_date_preserves_description(date):
    posting = {"@type": "JobPosting", "description": "Build product APIs.", "datePosted": date}
    html = '<script type="application/ld+json">' + json.dumps(posting) + "</script>"
    assert parse_eightfold_detail(html) == ("Build product APIs.", None)


@pytest.mark.parametrize("payload", [{"@type": "Organization", "description": "Company"},
                                     {"@type": "JobPosting", "description": ""}, {"@type": None}])
def test_eightfold_missing_description_is_an_enrichment_error(payload):
    html = '<script type="application/ld+json">' + json.dumps(payload) + "</script>"
    with pytest.raises(AdapterError, match="no JobPosting description"):
        parse_eightfold_detail(html)


def test_eightfold_canonical_url_preserves_numeric_job_id():
    payload = {"provider": "eightfold", "jobs": [{
        "title": "AI Engineer 6 - AI Foundation & Tooling, Ads Platform",
        "url": "https://explore.jobs.netflix.net/careers/job/790298014263",
        "company": "Netflix", "location": "Remote, United States", "postedAt": 1721692800000,
    }]}
    raw, = parse_jobs(payload, CompanyConfig(name="Netflix", key="netflix", adapter="careerops", size="big"))
    assert raw.source_id == "790298014263" and raw.extra["provider"] == "eightfold"
