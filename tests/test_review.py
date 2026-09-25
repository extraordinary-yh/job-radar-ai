import json
from pathlib import Path

from jobradar.config import load_preferences
from jobradar.models import Job, Review
from jobradar.review import apply_reviews, load_review_history, load_reviews, review_template, select_candidates, write_candidates

PREFS = load_preferences(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "preferences.yaml")


def job(i, score=50, status="open", excluded=False, hidden=False, flags=()):
    parts = {"title": 10, "location": 20, "experience": 20, "skills": 8, "recency": 10}
    j = Job(id=f"g:{i}", company="G", title=f"T{i}", url=f"u{i}", status=status, score=score, rank_score=float(score),
            score_parts=parts, flags=list(flags), excluded=excluded, hidden=hidden,
            qualifications_min="q" * 2000, description_text="d" * 2000)
    return j


def load_reviews_from(entries):
    return {e["id"]: Review.from_dict(e) for e in entries}


def test_load_reviews_accepts_both_shapes_and_legacy_fit(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"reviews": [{"id": "g:1", "skills": 34, "reason": "x"}]}))
    r = load_reviews(p)
    assert r["g:1"].skills == 34 and r["g:1"].fit is None and r["g:1"].yoe_match == "match"
    p.write_text(json.dumps([{"id": "g:2", "fit": 9, "reason": "y", "gaps": ["k8s"]}, {"id": "g:3", "reason": "no score"}]))
    loaded = load_reviews(p)
    assert loaded["g:2"].fit == 5 and loaded["g:2"].gaps == ["k8s"] and "g:3" not in loaded
    assert load_reviews(tmp_path / "missing.json") == {}


def test_apply_reviews_replaces_skills_points_and_recomputes_total():
    from copy import deepcopy
    prefs = deepcopy(PREFS); prefs.penalties["late"] = -40
    jobs = [job(1, score=68), job(2, score=68), job(3, score=28, flags=["late"])]
    reviews = load_reviews_from([{"id": "g:1", "skills": 36, "reason": "strong"},
                                 {"id": "g:3", "skills": 40, "reason": "penalized"},
                                 {"id": "g:9", "skills": 40, "reason": "?"}])
    assert apply_reviews(jobs, reviews, prefs) == 2
    assert jobs[0].score_parts["skills"] == 36 and jobs[0].score == 96 and jobs[0].rank_score == 96.0
    assert jobs[1].review is None and jobs[1].score == 68 and jobs[1].rank_score == 68.0
    assert jobs[2].score == 10 + 20 + 20 + 40 + 10 - 40                     # penalties still apply


def test_apply_reviews_clamps_and_converts_legacy_fit():
    jobs = [job(1), job(2)]
    reviews = load_reviews_from([{"id": "g:1", "skills": 99, "reason": "too high"}, {"id": "g:2", "fit": 5, "reason": "legacy"}])
    apply_reviews(jobs, reviews, PREFS)
    assert jobs[0].score_parts["skills"] == 40 and jobs[1].score_parts["skills"] == 40


def test_apply_reviews_skips_excluded_jobs():
    jobs = [job(1, excluded=True)]
    assert apply_reviews(jobs, load_reviews_from([{"id": "g:1", "skills": 40, "reason": "x"}]), PREFS) == 0
    assert jobs[0].review is None


def load_reviews_from(entries):
    return {e["id"]: Review.from_dict(e) for e in entries}


def test_select_candidates_threshold_new_and_cap():
    jobs = [job(1, score=90), job(2, score=39), job(3, score=10, status="new"), job(4, score=95, excluded=True),
            job(5, score=70, hidden=True)] + [job(10 + i, score=45) for i in range(40)]
    picked = select_candidates(jobs, PREFS)
    ids = [j.id for j in picked]
    assert ids[0] == "g:1" and "g:3" in ids and "g:2" not in ids and "g:4" not in ids and "g:5" not in ids
    assert len(picked) == 42                                   # g:1 + g:3 (new) + 40 fillers
    from copy import deepcopy
    capped = deepcopy(PREFS); capped.review["max_candidates"] = 60
    jobs += [job(100 + i, score=45) for i in range(40)]
    assert len(select_candidates(jobs, capped)) == 60


def test_write_candidates_is_compact(tmp_path):
    p = write_candidates(tmp_path / "c.json", [job(1)])
    doc = json.loads(p.read_text())
    entry = doc["candidates"][0]
    assert entry["id"] == "g:1" and len(entry["qualifications_min"]) <= 1500 and len(entry["description_text"]) <= 1500
    assert "score_parts" in entry and "url" in entry


def test_review_template_lists_ids():
    t = review_template("2026-09-01", [job(1), job(2)])
    assert t["date"] == "2026-09-01" and [r["id"] for r in t["reviews"]] == ["g:1", "g:2"]
    assert t["reviews"][0]["skills"] is None


def test_load_review_history_latest_file_wins(tmp_path):
    (tmp_path / "2026-09-01.json").write_text(json.dumps({"reviews": [{"id": "g:1", "skills": 20}, {"id": "g:2", "skills": 10}]}))
    (tmp_path / "2026-09-02.json").write_text(json.dumps({"reviews": [{"id": "g:1", "skills": 30}]}))
    h = load_review_history(tmp_path)
    assert h["g:1"].skills == 30 and h["g:2"].skills == 10
    assert load_review_history(tmp_path / "missing") == {}


def test_write_candidates_marks_reviewed(tmp_path):
    a, b = job(1), job(2)
    a.review = Review(id="g:1", skills=33, reason="done")
    doc = json.loads(write_candidates(tmp_path / "c.json", [a, b]).read_text())
    assert doc["unreviewed"] == 1
    assert doc["candidates"][0]["reviewed"] is True and doc["candidates"][0]["review_skills"] == 33
    assert doc["candidates"][1]["reviewed"] is False
