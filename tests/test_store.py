import json

from jobradar.models import Job, SourceResult
from jobradar.store import (SeenStore, breakage_warnings, days_between, list_snapshots, load_snapshot,
                            record_health, save_snapshot)


def job(i, company="google"):
    return Job(id=f"{company}:{i}", company=company.title(), title=f"T{i}", url=f"https://x/{i}")


def test_days_between():
    assert days_between("2026-09-01", "2026-09-04") == 3


def test_seen_store_transitions(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    a, b = job(1), job(2)
    store.update([a, b], "2026-09-01", {"google"})
    assert (a.status, a.first_seen, a.last_seen) == ("new", "2026-09-01", "2026-09-01")
    store.save()

    store = SeenStore(path)
    a2, c = job(1), job(3)
    store.update([a2, c], "2026-09-02", {"google"})
    assert a2.status == "open" and a2.first_seen == "2026-09-01" and a2.last_seen == "2026-09-02"
    assert c.status == "new"
    assert store.data["jobs"]["google:2"]["status"] == "closed"
    assert store.known_ids() == {"google:1", "google:2", "google:3"}


def test_seen_store_does_not_close_jobs_of_unfetched_company(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.update([job(1, "google"), job(9, "bloomberg")], "2026-09-01", {"google", "bloomberg"})
    store.update([job(1, "google")], "2026-09-02", {"google"})        # bloomberg failed today
    assert store.data["jobs"]["bloomberg:9"]["status"] == "new"        # untouched


def test_seen_store_purges_old_closed(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.update([job(1)], "2026-07-01", {"google"})
    store.update([], "2026-07-02", {"google"})
    assert store.data["jobs"]["google:1"]["status"] == "closed"
    store.update([], "2026-09-01", {"google"})
    assert "google:1" not in store.data["jobs"]


def test_seen_store_same_day_rerun_keeps_new(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.update([job(1)], "2026-09-01", {"google"})
    a = job(1)
    store.update([a], "2026-09-01", {"google"})
    assert a.status == "new"


def test_detail_stale(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.update([job(1)], "2026-08-01", {"google"})
    assert store.detail_stale("google:1", "2026-08-20") is True
    assert store.detail_stale("google:1", "2026-08-10") is False
    assert store.detail_stale("google:999", "2026-08-10") is True


def test_snapshot_round_trip(tmp_path):
    jobs = [job(1), job(2)]
    p = save_snapshot(tmp_path, "2026-09-01", jobs, {"sources": []})
    assert p.name == "2026-09-01.json"
    meta, back = load_snapshot(p)
    assert meta == {"sources": []} and [j.id for j in back] == ["google:1", "google:2"]
    save_snapshot(tmp_path, "2026-08-31", [], {})
    assert [x.name for x in list_snapshots(tmp_path)] == ["2026-08-31.json", "2026-09-01.json"]


def test_health_and_breakage(tmp_path):
    h = tmp_path / "health.json"
    record_health(h, "2026-09-01", [SourceResult("google", True, 20), SourceResult("bloomberg", True, 12)])
    record_health(h, "2026-09-02", [SourceResult("google", True, 0), SourceResult("bloomberg", False, 0, "timeout")])
    warnings = breakage_warnings(h, "2026-09-02")
    assert any("google" in w and "0" in w for w in warnings)
    assert not any("bloomberg" in w for w in warnings)         # failed outright, reported elsewhere
    assert json.loads(h.read_text())["2026-09-02"]["bloomberg"]["error"] == "timeout"


def test_record_health_merges_partial_runs(tmp_path):
    h = tmp_path / "health.json"
    record_health(h, "2026-09-02", [SourceResult("google", True, 20)])
    record_health(h, "2026-09-02", [SourceResult("apple", True, 5)])
    day = json.loads(h.read_text())["2026-09-02"]
    assert set(day) == {"google", "apple"}


def test_snapshot_drops_text_of_excluded_jobs(tmp_path):
    kept = job(1)
    kept.description_text, kept.qualifications_min = "full text", "quals"
    dropped = job(2)
    dropped.description_text, dropped.qualifications_min, dropped.qualifications_pref = "x" * 1000, "y" * 500, "z"
    dropped.excluded, dropped.exclude_reason, dropped.score = True, "title matches no target family", 0
    p = save_snapshot(tmp_path, "2026-09-08", [kept, dropped], {})
    raw = {j["id"]: j for j in json.loads(p.read_text())["jobs"]}
    assert raw["google:1"]["description_text"] == "full text"
    assert "description_text" not in raw["google:2"] and "qualifications_min" not in raw["google:2"]
    assert raw["google:2"]["exclude_reason"] == "title matches no target family" and raw["google:2"]["excluded"] is True
    assert {"id", "title", "company", "url", "score"} <= set(raw["google:2"])
    _, back = load_snapshot(p)                     # slim rows still load as Jobs with empty text
    slim = next(j for j in back if j.id == "google:2")
    assert slim.excluded and slim.description_text == "" and slim.title == "T2" and slim.exclude_reason == "title matches no target family"
