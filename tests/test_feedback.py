import json

import pytest

from jobradar.feedback import append_feedback, applied_archive, apply_feedback, company_ignores, latest_verdicts, parse_feedback_text
from jobradar.models import Job


def test_parse_feedback_text_json_and_shorthand():
    text = '{"job_id": "g:1", "verdict": "good", "note": "nice"}\nbad g:2 too senior\n\napplied g:3\n'
    entries = parse_feedback_text(text)
    assert entries == [{"job_id": "g:1", "verdict": "good", "note": "nice"},
                       {"job_id": "g:2", "verdict": "bad", "note": "too senior"},
                       {"job_id": "g:3", "verdict": "applied", "note": ""}]


def test_parse_feedback_text_rejects_bad_verdict():
    with pytest.raises(ValueError, match="verdict"):
        parse_feedback_text("meh g:1")


def test_append_and_latest(tmp_path):
    p = tmp_path / "feedback.jsonl"
    assert append_feedback(p, [{"job_id": "g:1", "verdict": "good"}], ts="2026-09-01T10:00:00") == 1
    append_feedback(p, [{"job_id": "g:1", "verdict": "bad", "note": "changed my mind"}], ts="2026-09-02T10:00:00")
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["ts"] == "2026-09-01T10:00:00"
    latest = latest_verdicts(p)
    assert latest["g:1"]["verdict"] == "bad" and latest["g:1"]["note"] == "changed my mind"
    assert latest_verdicts(tmp_path / "none.jsonl") == {}


def test_apply_feedback_hides_bad_and_ignore():
    jobs = [Job(id="g:1", company="G", title="a", url="u"), Job(id="g:2", company="G", title="b", url="u"),
            Job(id="g:3", company="G", title="c", url="u")]
    apply_feedback(jobs, {"g:1": {"verdict": "bad"}, "g:2": {"verdict": "applied"}})
    assert jobs[0].hidden and jobs[0].verdict == "bad"
    assert not jobs[1].hidden and jobs[1].verdict == "applied"
    assert jobs[2].verdict is None and not jobs[2].hidden


def test_company_ignore_hides_every_future_role_from_that_company(tmp_path):
    p = tmp_path / "feedback.jsonl"
    entry = parse_feedback_text("ignore-company amazon not interested in this company")
    assert entry == [{"company_key": "amazon", "kind": "company_ignore", "note": "not interested in this company"}]
    append_feedback(p, entry, ts="2026-09-11T10:00:00")
    assert company_ignores(p) == {"amazon"}
    jobs = [Job(id="amazon:1", company="Amazon", title="a", url="u"), Job(id="meta:1", company="Meta", title="b", url="u")]
    apply_feedback(jobs, {}, company_ignores(p))
    assert jobs[0].hidden and jobs[0].verdict == "ignore"
    assert not jobs[1].hidden


def test_applied_archive_joins_seen_records(tmp_path):
    p = tmp_path / "feedback.jsonl"
    append_feedback(p, [{"job_id": "g:1", "verdict": "applied", "note": "referral from A"}], ts="2026-09-01T10:00:00")
    append_feedback(p, [{"job_id": "g:2", "verdict": "bad"}, {"job_id": "g:3", "verdict": "applied"}], ts="2026-09-02T10:00:00")
    seen = {"g:1": {"title": "SWE", "company": "G", "url": "https://g/1", "status": "closed", "first_seen": "2026-08-30"}}
    arch = applied_archive(p, seen)
    assert [a["id"] for a in arch] == ["g:3", "g:1"]                      # newest first
    assert arch[1]["title"] == "SWE" and arch[1]["status"] == "closed" and arch[1]["applied_on"] == "2026-09-01"
    assert arch[0]["title"] == "g:3" and arch[0]["status"] == "unknown"     # unseen id still listed


def test_stage_lines_and_latest_stage(tmp_path):
    entries = parse_feedback_text("applied g:1 via referral\nstage g:1 phone recruiter call Tue\n{\"job_id\": \"g:2\", \"stage\": \"offer\"}")
    assert entries[1] == {"job_id": "g:1", "verdict": "applied", "stage": "phone", "note": "recruiter call Tue"}
    assert entries[2]["verdict"] == "applied" and entries[2]["stage"] == "offer"
    p = tmp_path / "f.jsonl"
    append_feedback(p, entries[:1], ts="2026-09-01T09:00:00")
    append_feedback(p, entries[1:2], ts="2026-09-03T09:00:00")
    v = latest_verdicts(p)["g:1"]
    assert v["verdict"] == "applied" and v["stage"] == "phone" and v["applied_on"] == "2026-09-01"
    arch = applied_archive(p, {})
    assert arch[0]["stage"] == "phone" and arch[0]["applied_on"] == "2026-09-01"
    with pytest.raises(ValueError, match="stage"):
        parse_feedback_text("stage g:1 nope")


def test_referral_and_tailor_lines_parse_and_do_not_touch_verdicts(tmp_path):
    from jobradar.feedback import pending_tailors, referral_companies, referral_marks
    entries = parse_feedback_text("referral figma:1\nreferral figma:2 none\ntailor stripe:9\napplied figma:1")
    assert entries[0] == {"job_id": "figma:1", "kind": "referral", "state": "on"}
    assert entries[1] == {"job_id": "figma:2", "kind": "referral", "state": "off"}
    assert entries[2] == {"job_id": "stripe:9", "kind": "tailor"}
    p = tmp_path / "f.jsonl"
    assert append_feedback(p, entries, ts="2026-09-02T10:00:00") == 4
    v = latest_verdicts(p)
    assert v["figma:1"]["verdict"] == "applied" and "figma:2" not in v and "stripe:9" not in v
    assert referral_marks(p) == {"figma:1": True, "figma:2": False}
    seen = {"figma:1": {"company": "Figma"}, "figma:2": {"company": "Figma"}}
    assert referral_companies(p, seen) == {"Figma"}
    append_feedback(p, [{"job_id": "figma:1", "kind": "referral", "state": "off"}], ts="2026-09-03T10:00:00")
    assert referral_companies(p, seen) == set()
    append_feedback(p, [{"job_id": "acme:4", "kind": "referral", "state": "on"}])
    assert referral_companies(p, seen) == {"Acme"}                       # unseen id falls back to the key
    assert parse_feedback_text('{"job_id": "x:1", "kind": "tailor"}') == [{"job_id": "x:1", "kind": "tailor"}]


def test_pending_tailors_skips_jobs_with_an_overlay(tmp_path):
    from jobradar.feedback import pending_tailors
    p = tmp_path / "f.jsonl"
    append_feedback(p, parse_feedback_text("tailor stripe:9\ntailor mercor:2"))
    apps = tmp_path / "applications"
    (apps / "stripe-9").mkdir(parents=True)
    (apps / "stripe-9" / "overlay.yaml").write_text("job_id: stripe:9\n")
    assert pending_tailors(p, apps) == ["mercor:2"]


def test_stage_line_records_resume_version_and_archive_links_it(tmp_path):
    entries = parse_feedback_text("stage g:1 applied resume=ab12cd34 sent Tue")
    assert entries[0]["resume"] == "ab12cd34" and entries[0]["note"] == "sent Tue"
    p = tmp_path / "f.jsonl"
    append_feedback(p, entries, ts="2026-09-02T10:00:00")
    assert latest_verdicts(p)["g:1"]["resume"] == "ab12cd34"
    apps = tmp_path / "applications"
    (apps / "g-1").mkdir(parents=True)
    (apps / "g-1" / "resume.pdf").write_bytes(b"%PDF")
    arch = applied_archive(p, {}, applications_dir=apps)
    assert arch[0]["resume"] == "ab12cd34" and arch[0]["resume_path"] == "../data/applications/g-1/resume.pdf"
    assert applied_archive(p, {})[0]["resume_path"] == ""


def test_applied_archive_follows_resume_hub_pointer(tmp_path):
    import json
    from jobradar.feedback import applied_archive
    ledger = tmp_path / "feedback.jsonl"
    ledger.write_text(json.dumps({"ts": "2026-09-07", "job_id": "g:1", "verdict": "applied"}) + "\n")
    apps = tmp_path / "data" / "applications"
    app = apps / "g-1"
    app.mkdir(parents=True)
    relative = "Applied Job Resumes/g-1/Alex_Resume.pdf"
    pdf = tmp_path / relative
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    (app / "resume-location.json").write_text(json.dumps({"path": relative}))
    assert applied_archive(ledger, {}, apps)[0]["resume_path"] == "../" + relative
    pdf.unlink()
    assert applied_archive(ledger, {}, apps)[0]["resume_path"] == ""


def test_applied_archive_uses_submitted_resume_version(tmp_path):
    import json
    from jobradar.feedback import applied_archive
    ledger = tmp_path / "feedback.jsonl"
    ledger.write_text(json.dumps({"ts": "2026-09-07", "job_id": "g:1", "verdict": "applied", "resume": "old"}) + "\n")
    apps = tmp_path / "data" / "applications"
    app = apps / "g-1"
    app.mkdir(parents=True)
    old = "Applied Job Resumes/g-1/resume_old.pdf"
    pdf = tmp_path / old
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF previous version")
    (app / "resume-location.json").write_text(json.dumps({"path": "Applied Job Resumes/g-1/resume.pdf", "versions": {"old": old}}))
    assert applied_archive(ledger, {}, apps)[0]["resume_path"] == "../" + old
