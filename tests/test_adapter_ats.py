import json
from pathlib import Path

import pytest

from jobradar.adapters.ashby import parse_board as parse_ashby
from jobradar.adapters.base import get_adapter, iso_to_ts
from jobradar.adapters.greenhouse import parse_board as parse_greenhouse
from jobradar.adapters.lever import parse_board as parse_lever
from jobradar.config import CompanyConfig
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures"


def load(kind):
    return json.loads((FIXTURES / kind / "search.json").read_text())


def cfg(kind, board):
    return CompanyConfig(name=kind.title(), key=kind, adapter=kind, board=board)


def test_iso_to_ts():
    assert iso_to_ts("2026-08-30T12:00:00Z") == 1788091200
    assert iso_to_ts("2026-08-30T08:00:00-04:00") == 1788091200
    assert iso_to_ts(None) is None and iso_to_ts("garbage") is None


def test_greenhouse_parse_board():
    jobs = parse_greenhouse(load("greenhouse"), cfg("greenhouse", "anthropic"))
    assert len(jobs) == 3
    j = jobs[0]
    assert j.company == "greenhouse" and j.source_id.isdigit() and j.url.startswith("http")
    assert j.locations and j.description_html and j.posted_ts
    assert j.extra["company_name"] == "Greenhouse"


def test_lever_parse_board():
    jobs = parse_lever(load("lever"), cfg("lever", "palantir"))
    assert len(jobs) == 3
    j = jobs[0]
    assert j.source_id and j.title and j.url.startswith("http") and j.apply_url.startswith("http")
    assert j.locations and j.description_html and j.posted_ts


def test_ashby_parse_board():
    jobs = parse_ashby(load("ashby"), cfg("ashby", "openai"))
    assert len(jobs) == 3
    j = jobs[0]
    assert j.source_id and j.title and j.url.startswith("http")
    assert j.locations and j.description_html and j.posted_ts


@pytest.mark.parametrize("kind,board", [("greenhouse", "anthropic"), ("lever", "palantir"), ("ashby", "openai")])
def test_adapters_offline_and_normalizable(kind, board):
    adapter = get_adapter(kind)
    jobs = adapter.search(cfg(kind, board), FixtureClient(FIXTURES, kind))
    assert len(jobs) == 3 and adapter.enrich(jobs[0], None) is jobs[0]
    job = normalize(jobs[0], "X")
    assert job.description_text and job.location_class != ""
