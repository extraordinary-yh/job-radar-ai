import json
from pathlib import Path

import pytest

from jobradar import careerops, liveness, reposts
from jobradar.models import Job

ROOT = Path(__file__).resolve().parents[1]


def test_check_normalizes_runner_output(monkeypatch, tmp_path):
    out = {"https://a": {"result": "active", "code": "greenhouse_api_ok", "reason": "live"},
           "https://b": {"result": "expired", "reason": "ATS API 404 — posting removed"}, "https://c": None}
    monkeypatch.setattr(liveness, "run_json", lambda root, script, args=(), **kw: out)
    got = liveness.check(tmp_path, ["https://a", "https://b", "https://c", "https://d"])
    assert got["https://a"]["result"] == "active" and got["https://b"]["result"] == "expired"
    assert got["https://c"]["result"] == "uncertain" and got["https://d"]["result"] == "uncertain"
    assert liveness.check(tmp_path, []) == {}


def test_annotate_archive_caches_one_day_and_forgets_old_urls(monkeypatch, tmp_path):
    monkeypatch.setattr(liveness, "unavailable_reason", lambda root: "")
    calls: list[list[str]] = []

    def fake_check(urls):
        calls.append(urls)
        return {u: {"result": "expired" if u.endswith("b") else "active", "reason": "r"} for u in urls}

    archive = [{"id": "x:1", "url": "https://a"}, {"id": "x:2", "url": "https://b"}, {"id": "x:3", "url": ""}]
    liveness.annotate_archive(archive, tmp_path, "2026-09-04", check_fn=fake_check)
    assert calls == [["https://a", "https://b"]]
    assert archive[0]["live"] == "active" and archive[1]["live"] == "expired" and "live" not in archive[2]
    liveness.annotate_archive(archive, tmp_path, "2026-09-04", check_fn=fake_check)
    assert len(calls) == 1                                           # same day: cached
    liveness.annotate_archive(archive[:1], tmp_path, "2026-09-05", check_fn=fake_check)
    assert calls[-1] == ["https://a"]
    store = json.loads((tmp_path / "data" / "careerops" / "liveness.json").read_text())
    assert set(store) == {"https://a"} and store["https://a"]["checked"] == "2026-09-05"


def test_annotate_archive_warns_once_without_node(monkeypatch, tmp_path):
    monkeypatch.setattr(liveness, "unavailable_reason", lambda root: "node is not installed")
    warnings: list[str] = []
    archive = [{"id": "x:1", "url": "https://a"}]
    liveness.annotate_archive(archive, tmp_path, "2026-09-04", warnings=warnings)
    assert warnings == ["liveness: node is not installed"] and "live" not in archive[0]


def test_export_history_writes_tsv_rows(tmp_path):
    seen = {"stripe:2": {"first_seen": "2026-09-02", "title": "SWE\tII", "company": "Stripe", "url": "https://s/2"},
            "stripe:1": {"first_seen": "2026-09-01", "title": "SWE", "company": "Stripe", "url": "https://s/1"},
            "bad:1": {"first_seen": "", "title": "x", "company": "y", "url": "https://z"}}
    p = reposts.export_history(tmp_path, seen)
    lines = p.read_text().splitlines()
    assert lines[0] == "url\tfirst_seen\tportal\ttitle\tcompany\tstatus\tlocation"
    assert lines[1] == "https://s/1\t2026-09-01\tstripe\tSWE\tStripe\tadded\t"
    assert lines[2] == "https://s/2\t2026-09-02\tstripe\tSWE II\tStripe\tadded\t" and len(lines) == 3


CLUSTERS = [{"company": "Stripe", "role": "Software Engineer", "repostCount": 2, "firstSeen": "2026-06-01", "lastSeen": "2026-08-20", "daysSpan": 80,
             "appearances": [{"url": "https://s/old", "date": "2026-06-01"}, {"url": "https://s/new", "date": "2026-08-20"}]}]


SEEN = {"stripe:old": {"url": "https://s/old", "last_seen": "2026-08-01"}, "stripe:new": {"url": "https://s/new", "last_seen": "2026-09-04"}}


def test_annotate_flags_urls_in_clusters(monkeypatch, tmp_path):
    monkeypatch.setattr(reposts, "unavailable_reason", lambda root: "")
    jobs = [Job(id="stripe:new", company="Stripe", title="Software Engineer", url="https://s/new", flags=["repost"]),
            Job(id="stripe:other", company="Stripe", title="SWE", url="https://s/other")]
    idx = reposts.annotate(jobs, tmp_path, SEEN, "2026-09-04", detect_fn=lambda: CLUSTERS)
    assert idx["https://s/new"]["count"] == 2 and idx["https://s/old"]["days"] == 80
    assert jobs[0].flags == ["repost"] and jobs[1].flags == []
    assert json.loads((tmp_path / "data" / "careerops" / "reposts.json").read_text())[0]["role"] == "Software Engineer"
    warnings: list[str] = []
    monkeypatch.setattr(reposts, "unavailable_reason", lambda root: "node is not installed")
    assert reposts.annotate(jobs, tmp_path, SEEN, "2026-09-04", warnings=warnings) == {} and warnings == ["reposts: node is not installed"]


def test_real_reposts_drops_clusters_whose_earlier_listings_are_still_open():
    siblings = {"m:1": {"url": "https://s/old", "last_seen": "2026-09-04"}, "m:2": {"url": "https://s/new", "last_seen": "2026-09-04"}}
    assert reposts.real_reposts(CLUSTERS, siblings, "2026-09-04") == []          # both still listed: parallel openings
    assert reposts.real_reposts(CLUSTERS, SEEN, "2026-09-04") == CLUSTERS         # the old one vanished: a repost
    assert reposts.real_reposts(CLUSTERS, {}, "2026-09-04") == CLUSTERS           # unknown earlier URL counts as gone


@pytest.mark.node
def test_detect_against_synthetic_history(tmp_path, monkeypatch):
    if not careerops.available(ROOT):
        pytest.skip(careerops.unavailable_reason(ROOT))
    monkeypatch.setattr(reposts, "data_root", lambda root: tmp_path)
    seen = {"acme:1": {"first_seen": "2026-06-01", "title": "Software Engineer", "company": "Acme", "url": "https://acme.example/jobs/1"},
            "acme:2": {"first_seen": "2026-08-20", "title": "Software Engineer", "company": "Acme", "url": "https://acme.example/jobs/2"},
            "acme:3": {"first_seen": "2026-08-20", "title": "Data Scientist", "company": "Acme", "url": "https://acme.example/jobs/3"}}
    reposts.export_history(ROOT, seen)
    clusters = reposts.detect(ROOT)
    assert len(clusters) == 1 and clusters[0]["company"] == "Acme" and clusters[0]["repostCount"] == 2


@pytest.mark.node
def test_liveness_runner_returns_null_for_unknown_hosts():
    if not careerops.available(ROOT):
        pytest.skip(careerops.unavailable_reason(ROOT))
    got = liveness.check(ROOT, ["https://example.com/jobs/1"])
    assert got == {"https://example.com/jobs/1": {"result": "uncertain", "reason": "no public ATS API for this host"}}
