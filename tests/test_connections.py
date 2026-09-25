import json
from pathlib import Path

import pytest
import yaml

from jobradar import careerops, connections
from jobradar.config import load_preferences
from jobradar.models import Job
from jobradar.render import render_report

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CSV = ROOT / "tests" / "fixtures" / "careerops" / "Connections.csv"

JOIN_OUT = {"targets": [
    {"company": "Stripe", "source": "portals", "secondDegreeSearch": "https://www.linkedin.com/search/people/?keywords=Stripe",
     "connections": [
         {"name": "Ada Lovelace", "title": "Staff Software Engineer", "linkedinCompany": "Stripe", "linkedin": "https://www.linkedin.com/in/ada-example",
          "connectedOn": "2025-03-12", "match": "exact"},
         {"name": "Grace Hopper", "title": "Engineering Manager", "linkedinCompany": "Stripe, Inc.", "linkedin": "https://www.linkedin.com/in/grace-example",
          "connectedOn": "2024-01-03", "match": "strong"}]},
    {"company": "figma", "source": "portals", "connections": [{"name": "Linus Torvalds", "title": "Senior Software Engineer", "linkedin": "", "match": "exact"}]},
], "totals": {"connections": 4, "targets": 3, "matchedCompanies": 2, "matchedConnections": 3}, "quality": {}}


def test_parse_join_maps_back_to_requested_names():
    found = connections.parse_join(JOIN_OUT, ["Stripe", "Figma", "Google"])
    assert list(found) == ["Stripe", "Figma"]
    assert [c["name"] for c in found["Stripe"]] == ["Ada Lovelace", "Grace Hopper"]
    assert found["Stripe"][1] == {"name": "Grace Hopper", "title": "Engineering Manager", "linkedin": "https://www.linkedin.com/in/grace-example",
                                  "match": "strong", "connected_on": "2024-01-03", "linkedin_company": "Stripe, Inc."}


def test_write_portals_lists_every_company_once(tmp_path):
    p = connections.write_portals(tmp_path, ["Stripe", "Figma", "Stripe", " "])
    doc = yaml.safe_load(p.read_text())
    assert doc == {"tracked_companies": [{"name": "Figma"}, {"name": "Stripe"}]}


def test_annotate_is_silent_without_export(tmp_path):
    warnings: list[str] = []
    assert connections.annotate([Job(id="s:1", company="Stripe", title="t", url="u")], tmp_path, warnings=warnings) == {}
    assert warnings == []


def test_annotate_joins_and_stores(monkeypatch, tmp_path):
    (tmp_path / "data" / "careerops").mkdir(parents=True)
    (tmp_path / "data" / "careerops" / "Connections.csv").write_text("x")
    monkeypatch.setattr(connections, "unavailable_reason", lambda root: "")
    asked: list[list[str]] = []

    def fake_join(names):
        asked.append(names)
        return connections.parse_join(JOIN_OUT, names)

    jobs = [Job(id="s:1", company="Stripe", title="t", url="u"), Job(id="f:1", company="Figma", title="t", url="u"), Job(id="g:1", company="Google", title="t", url="u")]
    found = connections.annotate(jobs, tmp_path, join_fn=fake_join)
    assert asked == [["Figma", "Google", "Stripe"]] and set(found) == {"Stripe", "Figma"}
    assert json.loads((tmp_path / "data" / "careerops" / "connections.json").read_text())["Figma"][0]["name"] == "Linus Torvalds"

    def broken(names):
        raise careerops.CareerOpsError("linkedin-join.mjs exited 1: bad csv")

    warnings: list[str] = []
    again = connections.annotate(jobs, tmp_path, warnings=warnings, join_fn=broken)
    assert again == found and warnings == ["connections: linkedin-join.mjs exited 1: bad csv"]   # falls back to the last good join


def test_card_lists_connections_with_profile_links():
    prefs = load_preferences(ROOT / "tests" / "fixtures" / "preferences.yaml")
    job = Job(id="stripe:1", company="Stripe", title="Software Engineer", url="https://x", score=80, rank_score=80)
    found = connections.parse_join(JOIN_OUT, ["Stripe"])
    html = render_report([job], {}, prefs, "2026-09-04", connections=found)
    assert "You know 2 people at Stripe" in html
    assert '<a href="https://www.linkedin.com/in/ada-example" target="_blank" rel="noopener">Ada Lovelace</a> <span class="sub">Staff Software Engineer</span>' in html
    assert "Find 1st-degree connections" not in html and "2nd-degree" in html


@pytest.mark.node
def test_join_against_fixture_csv(tmp_path, monkeypatch):
    if not careerops.available(ROOT):
        pytest.skip(careerops.unavailable_reason(ROOT))
    monkeypatch.setattr(connections, "data_root", lambda root: tmp_path)
    (tmp_path / "Connections.csv").write_bytes(FIXTURE_CSV.read_bytes())
    found = connections.join(ROOT, ["Stripe", "Figma", "Google"])
    assert [c["name"] for c in found["Stripe"]] == ["Ada Lovelace", "Grace Hopper"]
    assert found["Stripe"][1]["match"] == "strong" and found["Figma"][0]["name"] == "Linus Torvalds"
    assert "Google" not in found
