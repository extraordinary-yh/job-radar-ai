import json
from pathlib import Path

import pytest

from jobradar.adapters.base import get_adapter
from jobradar.adapters.hackernews import latest_thread_id, parse_header, parse_thread
from jobradar.config import CompanyConfig
from jobradar.errors import AdapterError
from jobradar.http import FixtureClient
from jobradar.normalize import normalize

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CFG = CompanyConfig(name="Hacker News", key="hackernews", adapter="hackernews", extra={"aggregator": True})


def test_latest_thread_id_skips_who_wants_to_be_hired():
    search = json.loads((FIXTURES / "hackernews" / "search.json").read_text())
    assert latest_thread_id(search) == "49522897"
    with pytest.raises(AdapterError):
        latest_thread_id({"hits": [{"objectID": "1", "title": "Ask HN: Who wants to be hired?"}]})


def test_parse_header_forms():
    assert parse_header("Modash.io | Senior Product Engineer | Remote (Europe) | Full-time | €75k") == ("Modash.io", "Senior Product Engineer", "Remote (Europe)")
    assert parse_header('Snout <a href="https://snout.com/">https://snout.com/</a> | Multiple roles | NYC<p>body') == ("Snout", "Multiple roles", "NYC")
    assert parse_header("yeet | Chicago, IL / Remote | Full-Time<p>Building things") == ("yeet", "Chicago, IL / Remote", "Full-Time")
    assert parse_header("Just a sentence with no pipes<p>more") == ("", "Just a sentence with no pipes", "")


def test_parse_thread_maps_comments_to_raw_jobs():
    item = json.loads((FIXTURES / "hackernews" / "item.json").read_text())
    raws = parse_thread(item, CFG)
    assert len(raws) == 6 and raws[0].source_id == "49522903" and raws[0].company == "hackernews"
    assert raws[0].url == "https://news.ycombinator.com/item?id=49522903" and raws[0].apply_url.startswith("https://modash.io")
    assert raws[0].extra["company_name"] == "Modash.io" and raws[0].locations == ["Remote (Europe)"]
    assert raws[0].posted_ts and "<" in raws[0].description_html
    job = normalize(raws[0], raws[0].extra["company_name"])
    assert job.company == "Modash.io" and job.title == "Senior Product Engineer" and job.id == "hackernews:49522903"
    assert job.location_class == "non_us"


def test_fixture_search_end_to_end():
    raws = get_adapter("hackernews").search(CFG, FixtureClient(FIXTURES, "hackernews"))
    assert [r.extra["company_name"] for r in raws][:2] == ["Modash.io", "We The Flywheel"]
