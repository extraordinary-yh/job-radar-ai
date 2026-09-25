from pathlib import Path

from jobradar.config import load_preferences
from jobradar.evaluate import evaluate, format_report
from jobradar.models import Job
from jobradar.store import save_snapshot

PREFS = load_preferences(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "preferences.yaml")


def job(i, title="Software Engineer", desc="LLM agents in TypeScript React Python RAG", loc="nyc", yoe=2):
    return Job(id=f"g:{i}", company="G", title=title, url=f"u{i}", location_class=loc, yoe_min=yoe,
               level="early", description_text=desc, posted_at="2026-08-30", first_seen="2026-08-30")


def test_evaluate_precision_and_regressions(tmp_path):
    good = job(1)
    bad_but_high = job(2)                                    # user said bad, scores high -> regression
    good_but_low = job(3, title="Staff Software Engineer")   # user said applied, now excluded -> regression
    unrated = job(4)
    save_snapshot(tmp_path, "2026-08-30", [good, bad_but_high, unrated], {})
    save_snapshot(tmp_path, "2026-08-31", [good, bad_but_high, good_but_low], {})
    verdicts = {"g:1": {"verdict": "good"}, "g:2": {"verdict": "bad"}, "g:3": {"verdict": "applied"}}
    r = evaluate(sorted(tmp_path.glob("*.json")), verdicts, PREFS, "2026-09-01")
    assert r.n_jobs == 3 and r.n_positive == 2 and r.n_negative == 1
    assert 0 < r.precision_at_10 <= 1
    assert any("g:2" in s for s in r.regressions_bad_high)
    assert any("g:3" in s for s in r.regressions_good_low)
    text = format_report(r)
    assert "precision@10" in text and "g:2" in text
