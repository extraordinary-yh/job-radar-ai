from pathlib import Path

import pytest

from jobradar.config import CompanyConfig, load_companies, load_preferences, repo_root

ROOT = Path(__file__).resolve().parents[1]


def test_repo_root_finds_pyproject(monkeypatch):
    monkeypatch.delenv("JOBRADAR_ROOT", raising=False)
    monkeypatch.chdir(ROOT / "tests")
    assert repo_root() == ROOT


def test_repo_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBRADAR_ROOT", str(tmp_path))
    assert repo_root() == tmp_path


def test_load_companies_parses_shipped_config():
    companies = load_companies(ROOT / "examples" / "config" / "companies.yaml")
    keys = {c.key for c in companies}
    assert {"google", "microsoft", "bloomberg"} <= keys
    google = next(c for c in companies if c.key == "google")
    assert google.adapter == "google" and google.enabled is True and google.size == "big"
    assert "software engineer" in google.queries and google.max_pages >= 1
    ats = [c for c in companies if c.adapter in {"greenhouse", "lever", "ashby"}]
    assert {"greenhouse", "ashby"} <= {c.adapter for c in ats}
    assert all(c.board for c in ats)
    stripe = next(c for c in companies if c.key == "stripe")
    assert stripe.enabled is True and stripe.size == "big" and stripe.max_yoe is None
    assert all(c.enabled is True for c in ats if c.key in {"anthropic", "openai"})
    assert "palantir" not in {c.key for c in companies}
    assert prefs_flags_ok()


def prefs_flags_ok():
    prefs = load_preferences(ROOT / "examples" / "profile" / "preferences.yaml")
    return prefs.flags["exclude"] == [] and prefs.salary["floor"] is None


def test_load_companies_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("companies:\n  - name: Acme\n    key: acme\n    adapter: greenhouse\n    board: acme\n")
    (c,) = load_companies(p)
    assert c == CompanyConfig(name="Acme", key="acme", adapter="greenhouse", enabled=True,
                              queries=[], locations=[], max_pages=1, board="acme", size="small", max_yoe=None, extra={})


def test_load_companies_rejects_duplicate_keys(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("companies:\n  - {name: A, key: a, adapter: lever, board: a}\n  - {name: B, key: a, adapter: lever, board: b}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_companies(p)


def test_load_preferences_shipped_file_has_required_sections():
    prefs = load_preferences(ROOT / "examples" / "profile" / "preferences.yaml")
    assert prefs.candidate["effective_yoe"] == 2
    assert prefs.weights == {"title": 10, "location": 20, "experience": 20, "skills": 40, "recency": 10}
    assert prefs.locations["scores"]["nyc"] == prefs.locations["scores"]["remote_us"] == 20 and prefs.locations["scores"]["bay"] == 15
    assert prefs.flags["exclude"] == [] and prefs.penalties == {}
    assert {"include", "exclude_patterns"} <= set(prefs.titles)
    assert prefs.review["candidate_min_score"] == 40
    assert prefs.referrals["min_score"] == 75 and prefs.referrals["skip_companies"] == []


def test_load_companies_reads_max_yoe(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("companies:\n  - {name: Stripe, key: stripe, adapter: greenhouse, board: stripe, size: big, max_yoe: 1}\n")
    (c,) = load_companies(p)
    assert c.size == "big" and c.max_yoe == 1
