import json
import yaml
import shutil
from pathlib import Path

import pytest

from jobradar.pipeline import carry_forward, run
from jobradar.models import Job
from jobradar.normalize import renormalize

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "profile").mkdir()
    # the recorded fixtures are all senior postings, so widen the years caps for this offline root
    prefs = (REPO / "tests" / "fixtures" / "preferences.yaml").read_text()
    assert "max_yoe_by_size:" in prefs
    doc = yaml.safe_load(prefs)
    doc["experience"]["max_yoe_by_size"] = {"small": 9, "big": 9}
    prefs = yaml.safe_dump(doc)
    (tmp_path / "profile" / "preferences.yaml").write_text(prefs)
    (tmp_path / "config" / "companies.yaml").write_text("""
companies:
  - {name: Google, key: google, adapter: google, size: big, queries: ["software engineer"], locations: ["New York, NY, USA"], max_pages: 1}
  - {name: Microsoft, key: microsoft, adapter: microsoft, queries: ["software engineer"], locations: ["New York, United States"], max_pages: 1}
  - {name: Bloomberg, key: bloomberg, adapter: bloomberg, queries: ["software engineer"], max_pages: 1}
  - {name: Anthropic, key: anthropic, adapter: greenhouse, board: anthropic}
  - {name: Broken, key: broken, adapter: nosuch, board: nope}
""")
    return tmp_path


def test_offline_run_produces_snapshot_report_and_candidates(root):
    r = run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES)
    by = {s.company: s for s in r.sources}
    assert by["google"].ok and by["google"].count == 3
    assert by["microsoft"].ok and by["bloomberg"].ok and by["anthropic"].ok
    assert not by["broken"].ok and "unknown adapter" in by["broken"].error
    assert r.snapshot_path.exists() and r.report_path.exists() and r.candidates_path.exists()
    assert (root / "reports" / "index.html").exists() and (root / "data" / "seen.json").exists()
    assert (root / "data" / "health.json").exists()
    snap = json.loads(r.snapshot_path.read_text())
    assert len(snap["jobs"]) == len(r.jobs) >= 9
    assert all(j["status"] == "new" for j in snap["jobs"])
    assert any(j["description_text"] for j in snap["jobs"] if j["id"].startswith("microsoft:"))
    html = r.report_path.read_text()
    assert "Job Radar AI · 2026-09-01" in html and "broken" in html
    assert all(j.company_size == "big" for j in r.jobs if j.id.startswith("google:"))
    assert all(j.company_size == "small" for j in r.jobs if j.id.startswith("anthropic:"))


def test_second_day_marks_open_and_carries_descriptions(root):
    run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES)
    r2 = run(root, "2026-09-02", offline=True, fixtures_root=FIXTURES)
    ms = [j for j in r2.jobs if j.id.startswith("microsoft:")]
    assert ms and all(j.status == "open" and j.first_seen == "2026-09-01" for j in ms)
    assert all(j.description_text for j in ms if not j.excluded)   # not re-fetched, carried from day one
    assert (root / "data" / "jobs" / "2026-09-02.json").exists()


def test_skip_fetch_rerenders_from_snapshot_with_review(root, tmp_path):
    r1 = run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES)
    target = next(j for j in r1.jobs if not j.excluded)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviews": [{"id": target.id, "fit": 5, "reason": "Perfect match for you"}]}))
    r2 = run(root, "2026-09-01", skip_fetch=True, review_path=review)
    assert r2.reviewed == 1 and "Perfect match for you" in r2.report_path.read_text()
    assert (root / "data" / "reviews" / "2026-09-01.json").exists()


def test_feedback_hides_jobs(root):
    r1 = run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES)
    target = next(j for j in r1.jobs if not j.excluded)
    (root / "data" / "feedback.jsonl").write_text(json.dumps({"ts": "t", "job_id": target.id, "verdict": "bad", "note": ""}) + "\n")
    r2 = run(root, "2026-09-01", skip_fetch=True)
    assert f'href="{target.url}"' not in r2.report_path.read_text()


def test_carry_forward_copies_detail_fields_only_when_missing():
    new = Job(id="a:1", company="A", title="t", url="u", arrangement="unknown")
    prev = Job(id="a:1", company="A", title="t", url="u", description_text="desc", qualifications_min="q",
               yoe_min=3, flags=["clearance"], arrangement="hybrid")
    carry_forward(new, prev)
    assert new.description_text == "desc" and new.yoe_min == 3 and new.flags == ["clearance"] and new.arrangement == "hybrid"
    new2 = Job(id="a:1", company="A", title="t", url="u", description_text="fresh", arrangement="remote")
    carry_forward(new2, prev)
    assert new2.description_text == "fresh" and new2.arrangement == "remote"


def test_renormalize_keeps_parsed_requirement_fields_when_excluded_text_is_slimmed():
    job = Job(id="amazon:1", company="Amazon", title="Software Development Engineer", url="u",
              locations=["New York, NY, USA"], yoe_min=3, yoe_pref=3, flags=["us_person"])
    renormalize(job)
    assert job.yoe_min == 3 and job.yoe_pref == 3 and job.flags == ["us_person"]


def test_partial_run_keeps_other_companies_from_todays_snapshot(root):
    run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES)
    r2 = run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES, company_filter={"google"})
    companies = {j.id.split(":", 1)[0] for j in r2.jobs}
    assert {"google", "microsoft", "bloomberg", "anthropic"} <= companies
    assert [s.company for s in r2.sources] == ["google"]


def test_reviews_carry_forward_to_the_next_day(root, tmp_path):
    r1 = run(root, "2026-09-01", offline=True, fixtures_root=FIXTURES)
    target = next(j for j in r1.jobs if not j.excluded)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviews": [{"id": target.id, "skills": 39, "reason": "Carried forward"}]}))
    run(root, "2026-09-01", skip_fetch=True, review_path=review)
    r2 = run(root, "2026-09-02", offline=True, fixtures_root=FIXTURES)
    again = next(j for j in r2.jobs if j.id == target.id)
    assert again.review is not None and again.score_parts["skills"] == 39 and r2.reviewed >= 1
    assert "Carried forward" in r2.report_path.read_text()
