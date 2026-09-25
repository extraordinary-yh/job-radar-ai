import json
from pathlib import Path

import pytest

from jobradar import careerops, h1b
from jobradar.config import load_preferences
from jobradar.models import Job
from jobradar.render import render_report

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_INDEX = ROOT / "tests" / "fixtures" / "careerops" / "h1b-index.ndjson.gz"

STRIPE = {"found": True, "employerId": "270465600", "displayName": "Stripe, LLC", "hasSponsorshipHistory": True,
          "totals": {"n_lca": 1819, "n_certified": 1785, "n_pwd": 689, "n_perm": 475, "first_year": 2019, "last_year": 2026, "does_gc": True},
          "redFlags": {"staffing_shop": {"value": False, "share": 0}}, "friendlinessTier": "strong",
          "source": "local:h1b-index@sha256-1e11", "fetchedAt": "2026-09-04T22:29:27.783Z"}
NOWHERE = {"found": False, "displayName": "Nowhere Corp", "totals": None, "friendlinessTier": "unknown"}


def test_summarize_found_and_not_found():
    s = h1b.summarize(STRIPE)
    assert s["tier"] == "strong" and s["n_lca"] == 1819 and s["n_perm"] == 475
    assert s["note"] == "Stripe, LLC · 1,819 LCAs · 475 PERMs · active 2019–2026 · files H-1B and green cards, recent and steady"
    u = h1b.summarize(NOWHERE)
    assert u["tier"] == "unknown" and not u["found"] and u["note"] == "name not found in the DOL index"
    assert h1b.summarize({"friendlinessTier": "made-up", "found": True, "displayName": "X"})["tier"] == "unknown"


def test_fold_and_names_agree():
    assert h1b.fold_name("C3.ai, Inc.") == "c3ai" and h1b.fold_name("Stripe, LLC") == "stripe" and h1b.fold_name("The Trade Desk, Inc") == "tradedesk"
    assert h1b.names_agree("Microsoft", "Microsoft Corporation") and h1b.names_agree("C3 AI", "C3.ai, Inc.")
    assert h1b.names_agree("Acme Media", "AcmeMedia Inc.") and h1b.names_agree("Mercor", "Mercor.io Corporation")
    assert h1b.names_agree("Acme Media", "AcmeMedia Inc.") and h1b.names_agree("Bloomberg", "Bloomberg L.P.")
    assert not h1b.names_agree("Stripe", "Striped Bass Consulting LLC") and not h1b.names_agree("AiMi", "Aimee Staffing Solutions LLC")
    assert not h1b.names_agree("", "X")
    assert h1b.names_agree("Ramp", "Ramp Up Staffing")        # a whole-word hit passes; the tooltip names the entity so the user can judge



def test_summarize_demotes_a_mismatched_entity_to_unknown():
    s = h1b.summarize(dict(STRIPE, displayName="Striped Bass Consulting LLC"), "Stripe")
    assert s["tier"] == "unknown" and not s["found"] and s["name_mismatch"] == "Striped Bass Consulting LLC"
    assert s["note"].startswith("closest DOL entity is 'Striped Bass Consulting LLC'")
    assert h1b.summarize(STRIPE, "Stripe")["tier"] == "strong"


def _ready(monkeypatch, tmp_path):
    monkeypatch.setattr(h1b, "unavailable_reason", lambda root: "")
    (tmp_path / "data" / "careerops" / "h1b").mkdir(parents=True)
    (tmp_path / "data" / "careerops" / "h1b" / "index.ndjson.gz").write_bytes(b"")


def test_annotate_caches_per_company_for_30_days(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_lookup(name):
        calls.append(name)
        return h1b.summarize(STRIPE if name == "Stripe" else NOWHERE)

    jobs = [Job(id="stripe:1", company="Stripe", title="SWE", url="u"), Job(id="stripe:2", company="Stripe", title="SWE II", url="u2"),
            Job(id="x:1", company="Nowhere Corp", title="SWE", url="u3")]
    warnings: list[str] = []
    h1b.annotate(jobs, tmp_path, "2026-09-04", lookup_fn=fake_lookup, warnings=warnings)
    assert calls == ["Nowhere Corp", "Stripe"] and warnings == []
    assert jobs[0].h1b_tier == "strong" and jobs[1].h1b_tier == "strong" and jobs[2].h1b_tier == "unknown"
    assert "1,819 LCAs" in jobs[0].h1b_note
    saved = json.loads((tmp_path / "data" / "careerops" / "h1b_tiers.json").read_text())
    assert saved["Stripe"]["checked"] == "2026-09-04" and saved["Stripe"]["tier"] == "strong"

    calls.clear()
    h1b.annotate(jobs, tmp_path, "2026-10-03", lookup_fn=fake_lookup, warnings=warnings)   # 29 days: cache hit
    assert calls == []
    h1b.annotate(jobs, tmp_path, "2026-10-04", lookup_fn=fake_lookup, warnings=warnings)   # 30 days: refresh
    assert calls == ["Nowhere Corp", "Stripe"]


def test_annotate_skips_with_one_warning_when_sidecar_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(h1b, "unavailable_reason", lambda root: "node is not installed (career-ops features skipped)")
    jobs = [Job(id="stripe:1", company="Stripe", title="SWE", url="u")]
    warnings: list[str] = []
    assert h1b.annotate(jobs, tmp_path, "2026-09-04", warnings=warnings) == {}
    assert warnings == ["h1b: node is not installed (career-ops features skipped)"] and jobs[0].h1b_tier == ""
    monkeypatch.setattr(h1b, "unavailable_reason", lambda root: "")
    warnings.clear()
    h1b.annotate(jobs, tmp_path, "2026-09-04", warnings=warnings)
    assert warnings == ["h1b: DOL index not installed; run `uv run jobradar h1b --install`"]


def test_annotate_skips_excluded_jobs_and_respects_the_budget(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_lookup(name):
        calls.append(name)
        return h1b.summarize(dict(STRIPE, displayName=name))

    jobs = [Job(id="a:1", company="A", title="t", url="u"), Job(id="b:1", company="B", title="t", url="u"),
            Job(id="c:1", company="C", title="t", url="u"), Job(id="x:1", company="Excluded Co", title="t", url="u", excluded=True)]
    warnings: list[str] = []
    h1b.annotate(jobs, tmp_path, "2026-09-04", lookup_fn=fake_lookup, warnings=warnings, max_new=2)
    assert calls == ["A", "B"] and jobs[2].h1b_tier == "" and jobs[3].h1b_tier == ""
    assert warnings == ["h1b: 1 companies not looked up yet (budget of 40 per run); they get tiers on later runs"]
    h1b.annotate(jobs, tmp_path, "2026-09-05", lookup_fn=fake_lookup, max_new=2)
    assert calls == ["A", "B", "C"]                    # the deferred one runs next time; cached ones do not


def test_annotate_uses_alias_and_refreshes_when_alias_changes(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_lookup(name):
        calls.append(name)
        return h1b.summarize(dict(STRIPE, displayName=name))

    jobs = [Job(id="microsoft:1", company="Microsoft", title="SWE", url="u")]
    h1b.annotate(jobs, tmp_path, "2026-09-04", lookup_fn=fake_lookup, aliases={"Microsoft": "Microsoft Corporation"})
    assert calls == ["Microsoft Corporation"] and jobs[0].h1b_note.startswith("Microsoft Corporation")
    saved = json.loads((tmp_path / "data" / "careerops" / "h1b_tiers.json").read_text())
    assert saved["Microsoft"]["query"] == "Microsoft Corporation"
    calls.clear()
    h1b.annotate(jobs, tmp_path, "2026-09-05", lookup_fn=fake_lookup, aliases={"Microsoft": "Microsoft Corporation"})
    assert calls == []                                        # same alias, cached
    h1b.annotate(jobs, tmp_path, "2026-09-05", lookup_fn=fake_lookup)
    assert calls == ["Microsoft"]                             # alias removed: look the plain name up again


def test_lookup_best_escapes_zero_volume_exact_match(monkeypatch, tmp_path):
    seen: list[str] = []
    zero = {"found": True, "displayName": "Microsoft", "friendlinessTier": "weak",
            "totals": {"n_lca": 0, "n_pwd": 0, "n_perm": 0, "first_year": 2023, "last_year": 2023}}
    big = {"found": True, "displayName": "Microsoft Corporation", "friendlinessTier": "strong",
           "totals": {"n_lca": 40000, "n_pwd": 900, "n_perm": 8000, "first_year": 2019, "last_year": 2026}}
    monkeypatch.setattr(h1b, "lookup", lambda root, name, refresh=False, index=None: seen.append(name) or (big if name == "Microsoft Corporation" else zero))
    monkeypatch.setattr(h1b, "search", lambda root, name: [{"id": "1", "name": "Microsoft Corporation"}, {"id": "2", "name": "Smith Micro Software, Inc."}])
    s = h1b.lookup_best(tmp_path, "Microsoft")
    assert s["tier"] == "strong" and s["resolved_from"] == "Microsoft" and seen == ["Microsoft", "Microsoft Corporation"]
    monkeypatch.setattr(h1b, "search", lambda root, name: [])
    assert h1b.lookup_best(tmp_path, "Microsoft")["tier"] == "weak"       # nothing better: keep the exact match
    monkeypatch.setattr(h1b, "lookup", lambda root, name, refresh=False, index=None: big)
    monkeypatch.setattr(h1b, "search", lambda root, name: (_ for _ in ()).throw(AssertionError("search must not run")))
    assert h1b.lookup_best(tmp_path, "Microsoft Corporation")["tier"] == "strong"


def test_annotate_reports_failed_lookups_without_caching_them(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)

    def boom(name):
        raise careerops.CareerOpsError("check.mjs exited 1: index unreadable")

    jobs = [Job(id="stripe:1", company="Stripe", title="SWE", url="u")]
    warnings: list[str] = []
    h1b.annotate(jobs, tmp_path, "2026-09-04", lookup_fn=boom, warnings=warnings)
    assert warnings == ["h1b: lookup failed for Stripe (check.mjs exited 1: index unreadable)"]
    assert json.loads((tmp_path / "data" / "careerops" / "h1b_tiers.json").read_text()) == {}


def test_card_shows_tier_chip_with_note():
    prefs = load_preferences(ROOT / "tests" / "fixtures" / "preferences.yaml")
    job = Job(id="stripe:1", company="Stripe", title="Software Engineer", url="https://x", score=80, rank_score=80,
              h1b_tier="strong", h1b_note="Stripe, LLC · 1,819 LCAs · 475 PERMs")
    html = render_report([job, Job(id="y:1", company="Y", title="SWE", url="https://y", h1b_tier="unknown")], {}, prefs, "2026-09-04")
    assert 'class="tag h1b h1b-strong" title="Stripe, LLC · 1,819 LCAs · 475 PERMs">' in html
    assert html.count("H-1B strong") == 1 and html.count("H-1B ") == 1   # unknown tiers stay silent


def test_job_roundtrip_keeps_h1b_fields():
    j = Job(id="a:1", company="A", title="t", url="u", h1b_tier="moderate", h1b_note="n")
    assert Job.from_dict(j.to_dict()).h1b_tier == "moderate"


@pytest.mark.node
def test_lookup_against_fixture_index():
    if not careerops.available(ROOT):
        pytest.skip(careerops.unavailable_reason(ROOT))
    s = h1b.summarize(h1b.lookup(ROOT, "Stripe", index=FIXTURE_INDEX, refresh=True))
    assert s["tier"] == "strong" and s["employer"] == "STRIPE, LLC"
    assert h1b.summarize(h1b.lookup(ROOT, "Acme Staffing Solutions", index=FIXTURE_INDEX, refresh=True))["tier"] == "staffing-shop"
    assert h1b.summarize(h1b.lookup(ROOT, "Nowhere Corp", index=FIXTURE_INDEX, refresh=True))["tier"] == "unknown"
