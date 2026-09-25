import json

from jobradar import followup
from jobradar.feedback import append_feedback, applied_archive, followup_events, parse_feedback_text


def test_parse_and_append_followup_events(tmp_path):
    entries = parse_feedback_text("followup stripe:1 emailed the recruiter\nfollowup stripe:2\n" + json.dumps({"job_id": "x:1", "kind": "followup", "note": "pinged"}))
    assert entries == [{"job_id": "stripe:1", "kind": "followup", "note": "emailed the recruiter"},
                       {"job_id": "stripe:2", "kind": "followup", "note": ""}, {"job_id": "x:1", "kind": "followup", "note": "pinged"}]
    fb = tmp_path / "feedback.jsonl"
    append_feedback(fb, [{"job_id": "stripe:1", "verdict": "applied", "note": ""}], ts="2026-09-01T10:00:00")
    append_feedback(fb, entries, ts="2026-09-08T09:00:00")
    assert followup_events(fb) == {"stripe:1": [{"date": "2026-09-08", "note": "emailed the recruiter"}],
                                   "stripe:2": [{"date": "2026-09-08", "note": ""}], "x:1": [{"date": "2026-09-08", "note": "pinged"}]}
    arch = applied_archive(fb, {"stripe:1": {"title": "SWE", "company": "Stripe", "url": "u"}})
    assert arch[0]["followups"] == [{"date": "2026-09-08", "note": "emailed the recruiter"}]
    assert "stripe:2" not in {a["id"] for a in arch}          # a touch alone does not make an application


def test_applied_cadence():
    a = {"stage": "applied", "applied_on": "2026-09-01", "followups": []}
    assert followup.assess(a, "2026-09-05") == {"touches": 0, "last_touch": "", "urgency": "waiting", "next_due": "2026-09-08", "why": "applied 2026-09-01: first follow-up at 7 days"}
    assert followup.assess(a, "2026-09-08")["urgency"] == "overdue"
    one = {**a, "followups": [{"date": "2026-09-08", "note": ""}]}
    assert followup.assess(one, "2026-09-10") == {"touches": 1, "last_touch": "2026-09-08", "urgency": "waiting", "next_due": "2026-09-15", "why": "followed up 2026-09-08: next in 7 days"}
    assert followup.assess(one, "2026-09-16")["urgency"] == "overdue"
    two = {**a, "followups": [{"date": "2026-09-08"}, {"date": "2026-09-15"}]}
    assert followup.assess(two, "2026-09-30")["urgency"] == "cold"
    assert followup.assess({"stage": "applied", "followups": []}, "2026-09-30")["why"] == "applied date unknown"


def test_interview_and_done_cadence():
    p = {"stage": "phone", "applied_on": "2026-09-01", "stage_on": "2026-09-10", "followups": [{"date": "2026-09-08"}]}
    r = followup.assess(p, "2026-09-11")
    assert r["urgency"] == "overdue" and r["next_due"] == "2026-09-11" and r["why"] == "phone on 2026-09-10: send the thank-you note"
    thanked = {**p, "followups": [{"date": "2026-09-08"}, {"date": "2026-09-11"}]}
    r = followup.assess(thanked, "2026-09-12")
    assert r["urgency"] == "waiting" and r["next_due"] == "2026-09-14"
    assert followup.assess(thanked, "2026-09-14")["urgency"] == "overdue"
    assert followup.assess({"stage": "rejected", "applied_on": "2026-09-01"}, "2026-09-14") == {"touches": 0, "last_touch": "", "urgency": "done", "next_due": "", "why": "rejected: nothing to chase"}


def test_annotate_archive_sorts_overdue_first_and_formats():
    rows = [{"id": "a:1", "company": "A", "title": "t", "stage": "offer", "applied_on": "2026-08-01"},
            {"id": "b:1", "company": "B", "title": "t", "stage": "applied", "applied_on": "2026-09-01"},
            {"id": "c:1", "company": "C", "title": "t", "stage": "applied", "applied_on": "2026-08-20"}]
    out = followup.annotate_archive(rows, "2026-09-04")
    assert [a["id"] for a in out] == ["c:1", "b:1", "a:1"]
    text = followup.format_rows(out)
    assert text.startswith("overdue  2026-08-27  C — t") and "waiting  2026-09-08  B — t" in text and "done" in text
    assert followup.format_rows(out, only_due=True).count("\n") == 1
    assert followup.format_rows([], only_due=True) == "nothing overdue"


def test_sidebar_shows_due_badge_and_touch_button():
    from pathlib import Path
    from jobradar.config import load_preferences
    from jobradar.render import render_report
    prefs = load_preferences(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "preferences.yaml")
    archive = followup.annotate_archive([{"id": "s:1", "title": "SWE", "company": "Stripe", "url": "u", "stage": "applied", "applied_on": "2026-08-20", "followups": []}], "2026-09-04")
    html = render_report([], {}, prefs, "2026-09-04", archive=archive)
    assert '<div class="due overdue" title="applied 2026-08-20: first follow-up at 7 days">' in html
    assert 'follow-up overdue since 2026-08-27 <button class="touch" data-id="s:1"' in html
    assert 'lines.push("followup " + id)' in html
