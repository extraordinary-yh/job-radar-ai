from pathlib import Path

import pytest

from jobradar.config import load_preferences
from jobradar.models import Job
from jobradar.score import apply_scores, match_title_family, score_job

PREFS = load_preferences(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "preferences.yaml")
TODAY = "2026-09-01"


def make(**kw):
    base = dict(id="google:1", company="Google", title="Software Engineer II", url="u",
                location_class="nyc", level="early", yoe_min=1, posted_at="2026-08-31",
                description_text="We build LLM agents in TypeScript, React and Python with RAG.")
    base.update(kw)
    return Job(**base)


@pytest.mark.parametrize("title,family", [
    ("Software Engineer II", "swe"), ("Member of Technical Staff", "swe"), ("Full-Stack Developer", "swe"),
    ("Machine Learning Engineer", "ml_ai"), ("AI Engineer, Agents", "ml_ai"),
    ("AI Product Engineer", "product_eng"), ("Forward Deployed Engineer", "fde"),
    ("Solutions Engineer", "fde"), ("Founding Engineer", "founding"),
])
def test_title_families(title, family):
    assert match_title_family(title, PREFS) == (family, None)


@pytest.mark.parametrize("title", ["Product Manager, AI", "Engineering Manager", "Principal Software Engineer",
                                   "Staff Software Engineer", "Software Engineering Intern", "Site Reliability Engineer",
                                   "Software Engineer, PhD, Early Career"])
def test_title_exclusions(title):
    family, pattern = match_title_family(title, PREFS)
    assert family is None and pattern


def test_unmatched_title_is_excluded_when_family_required():
    r = score_job(make(title="Technical Writer"), PREFS, TODAY)
    assert r.excluded and "no target family" in r.reason


def test_full_score_example():
    r = score_job(make(), PREFS, TODAY)
    assert not r.excluded and r.family == "swe"
    assert r.parts["title"] == 10 and r.parts["location"] == 20 and r.parts["experience"] == 20 and r.parts["recency"] == 10
    assert set(r.matched_skills) >= {"llm", "typescript", "react", "python", "rag", "agent"}
    assert r.parts["skills"] == 40 and r.total == 100


def test_location_scores_and_non_us_exclusion():
    assert score_job(make(location_class="bay"), PREFS, TODAY).parts["location"] == 15
    assert score_job(make(location_class="remote_us"), PREFS, TODAY).parts["location"] == 20
    assert score_job(make(location_class="other_us"), PREFS, TODAY).parts["location"] == 4
    r = score_job(make(location_class="non_us"), PREFS, TODAY)
    assert r.excluded and "non-US" in r.reason


def test_experience_band():
    assert score_job(make(yoe_min=1), PREFS, TODAY).parts["experience"] == 20
    assert score_job(make(yoe_min=2), PREFS, TODAY).parts["experience"] == 10    # 2 full-time years asked: 10 points
    assert score_job(make(yoe_min=3), PREFS, TODAY).parts["experience"] == 0     # 3 years at a small company: shown, bottom
    assert score_job(make(yoe_min=None, level="unknown"), PREFS, TODAY).parts["experience"] == 16
    assert score_job(make(yoe_min=None, level="new_grad", title="Software Engineer, New Grad"), PREFS, TODAY).parts["experience"] == 20   # overqualified = full match
    assert score_job(make(yoe_min=1, level="senior", title="Senior Software Engineer"), PREFS, TODAY).parts["experience"] == 10
    r = score_job(make(level="manager", title="Software Engineering Team Lead"), PREFS, TODAY)
    assert r.excluded and "manager" in r.reason


def test_years_caps_by_company_size():
    r = score_job(make(yoe_min=4), PREFS, TODAY)                          # small company, 4 years
    assert r.excluded and r.reason == "requires 4+ years at a small company"
    r = score_job(make(yoe_min=3, company_size="big"), PREFS, TODAY)      # big company, 3 years
    assert r.excluded and r.reason == "requires 3+ years at a big company"
    assert not score_job(make(yoe_min=2, company_size="big"), PREFS, TODAY).excluded
    assert not score_job(make(yoe_min=3, company_size="small"), PREFS, TODAY).excluded


def test_company_max_yoe_overrides_size_cap():
    r = score_job(make(yoe_min=2, company="Stripe", company_size="big", company_max_yoe=1), PREFS, TODAY)
    assert r.excluded and r.reason == "requires 2+ years (Stripe accepts up to 1)"
    assert not score_job(make(yoe_min=1, company="Stripe", company_size="big", company_max_yoe=1), PREFS, TODAY).excluded


def test_skills_partial_and_cpp_term():
    r = score_job(make(description_text="Modern C++ and SQL on Postgres."), PREFS, TODAY)
    assert set(r.matched_skills) == {"c++", "sql", "postgres"}
    assert r.parts["skills"] == round(3 * 40 / 15)


def test_recency():
    assert score_job(make(posted_at="2026-08-20"), PREFS, TODAY).parts["recency"] == 4
    assert score_job(make(posted_at=None, first_seen="2026-06-01"), PREFS, TODAY).parts["recency"] == 1


@pytest.mark.parametrize("flag", ["no_sponsorship", "clearance", "us_person", "phd_required", "masters_required"])
def test_flags_are_hard_exclusions(flag):
    r = score_job(make(flags=[flag]), PREFS, TODAY)
    assert r.excluded and r.reason == f"flag: {flag}"


def test_salary_floor_optional():
    assert not score_job(make(salary_max=90000), PREFS, TODAY).excluded          # no floor set
    from copy import deepcopy
    prefs = deepcopy(PREFS); prefs.salary["floor"] = 150000
    r = score_job(make(salary_max=120000), prefs, TODAY)
    assert r.excluded and "salary below floor" in r.reason
    assert not score_job(make(salary_max=None), prefs, TODAY).excluded


def test_apply_scores_sets_fields():
    jobs = [make(), make(id="google:2", title="Product Manager")]
    apply_scores(jobs, PREFS, TODAY)
    assert jobs[0].score == 100 and jobs[0].rank_score == 100.0 and jobs[0].score_parts["title"] == 10
    assert jobs[1].excluded and jobs[1].score == 0 and jobs[1].exclude_reason


def test_preferred_years_of_four_or_more_cap_experience():
    assert score_job(make(yoe_min=None, level="unknown", yoe_pref=8), PREFS, TODAY).parts["experience"] == 5
    assert score_job(make(yoe_min=None, level="unknown", yoe_pref=4), PREFS, TODAY).parts["experience"] == 5
    assert score_job(make(yoe_min=None, level="unknown", yoe_pref=3), PREFS, TODAY).parts["experience"] == 16
    assert score_job(make(yoe_min=1, yoe_pref=6), PREFS, TODAY).parts["experience"] == 5
