import re
from pathlib import Path

from jobradar.config import load_preferences
from jobradar.models import Job, Review
from jobradar.render import render_report, write_report, yoe_label

PREFS = load_preferences(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "preferences.yaml")
META = {"sources": [{"company": "google", "ok": True, "count": 20, "error": ""},
                    {"company": "bloomberg", "ok": False, "count": 0, "error": "timeout"}],
        "warnings": ["microsoft: 0 jobs today but 30 on 2026-08-31 (possible breakage)"],
        "generated_at": "2026-09-01T14:00:00", "reviewed": 1}


def job(i, **kw):
    base = dict(id=f"google:{i}", company="Google", title=f"Software Engineer {i}", url=f"https://g/{i}",
                locations=["New York, NY, USA"], location_class="nyc", arrangement="hybrid", level="early",
                yoe_min=2, flags=[], status="new", first_seen="2026-09-01", score=70 + i, rank_score=70.0 + i,
                score_parts={"title": 10, "location": 20, "experience": 20, "skills": 11, "recency": 10},
                matched_skills=["react", "llm"])
    base.update(kw)
    return Job(**base)


def test_yoe_label():
    assert yoe_label(None, 1.5) == "not stated"
    assert yoe_label(1, 1.5) == "match" and yoe_label(2, 1.5) == "stretch" and yoe_label(3, 1.5) == "stretch"
    assert yoe_label(4, 1.5) == "over"


def test_render_contains_jobs_sections_and_no_external_assets():
    reviewed = job(1, score_parts={"title": 10, "location": 20, "experience": 20, "skills": 36, "recency": 10}, score=96, rank_score=96.0,
                   review=Review(id="google:1", skills=36, yoe_match="match", experience_match="strong",
                                 reason="Ships LLM features end to end", gaps=["Go"], tags=["ai"]))
    excluded = job(2, excluded=True, exclude_reason="title matches exclude pattern 'staff'", title="Staff Engineer")
    hidden = job(3, hidden=True, verdict="bad")
    applied = job(4, verdict="applied", status="open")
    flagged = job(5, flags=["no_sponsorship"], score=31, rank_score=31.0)   # parts sum 71, penalty 40
    html = render_report([reviewed, excluded, hidden, applied, flagged], META, PREFS, "2026-09-01")
    assert "<title>" in html and "2026-09-01" in html
    assert 'href="https://g/1"' in html and "Ships LLM features end to end" in html and "★" not in html
    assert "Staff Engineer" in html and "exclude pattern" in html          # excluded section
    assert "https://g/3" not in html                                       # hidden job absent
    assert 'href="https://g/4"' in html and 'id="side"' in html and 'class="card done applied"' in html and "not looking again" not in html
    assert 'Applied (1)</button>' in html and 'select class="stage"' in html
    assert "no_sponsorship" in html
    assert "$150K–$200K" in render_report([job(7, salary_min=150000, salary_max=200000)], META, PREFS, "2026-09-01")
    assert "preferred 8+ yrs" in render_report([job(8, yoe_pref=8)], META, PREFS, "2026-09-01")
    assert "timeout" in html and "possible breakage" in html               # source strip + warnings
    assert re.search(r'data-company="google"', html) and 'data-metro="nyc"' in html
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?://', html)
    assert "prefers-color-scheme" in html and "feedback" in html.lower()
    assert "Find 1st-degree connections at Google" not in html          # Google is a skip company
    fig = job(9, company="Figma", score=80, rank_score=80.0)
    html2 = render_report([fig], META, PREFS, "2026-09-01", archive=[{"id": "x:1", "title": "Old role", "company": "Acme", "url": "https://acme/1", "status": "closed", "applied_on": "2026-08-20", "note": "", "first_seen": ""}])
    assert "Find 1st-degree connections at Figma" in html2 and "keywords=Figma" in html2
    assert "Old role" in html2 and "posting closed" in html2 and "Applied (1)</button>" in html2
    assert 'class="chart"' in html and "36/40" in html and "semantic review" in html          # reviewed card's chart
    assert "11/40" in html and "keyword match (not reviewed yet)" in html                     # unreviewed card's chart
    assert 'data-skills="36"' in html and "−40" in html                                        # penalties row on the flagged card


def test_write_report_writes_dated_and_index(tmp_path):
    dated, index = write_report("<html>x</html>", tmp_path, "2026-09-01")
    assert dated.name == "2026-09-01.html" and index.name == "index.html"
    assert dated.read_text() == index.read_text() == "<html>x</html>"


def test_pinned_matches_precede_higher_scores_and_static_report_points_to_saving_board():
    html = render_report([job(1, score=99), job(2, score=70)], META, PREFS, "2026-10-02",
                         pinned_jobs=["google:2"], local_board_url="http://127.0.0.1:8766/")
    assert html.index('data-id="google:2"') < html.index('data-id="google:1"')
    assert 'data-pinned="1"' in html and 'Pinned for you' in html
    assert 'href="http://127.0.0.1:8766/"' in html and 'drafts only' in html
    assert 'id="send"' not in html and 'id="token"' not in html


def test_referral_toggle_chip_and_resume_link():
    a, b = job(1, company="Figma", id="figma:1"), job(2, company="Figma", id="figma:2")
    html = render_report([a, b], META, PREFS, "2026-09-02", referral_marks={"figma:1": True}, referral_companies={"Figma"},
                         archive=[{"id": "x:1", "title": "Old role", "company": "Acme", "url": "https://acme/1", "status": "open",
                                   "applied_on": "2026-08-20", "note": "", "first_seen": "", "stage": "applied", "stage_on": "",
                                   "resume": "ab12cd34", "resume_path": "../data/applications/x-1/resume.pdf"}])
    assert html.count('class="refbtn on"') == 1 and html.count('class="refbtn"') == 1
    assert html.count('class="tag referral" data-server="1"') == 2                # chip on both Figma cards
    assert 'href="../data/applications/x-1/resume.pdf"' in html and "ab12cd34" in html
    assert 'data-verdict="tailor"' in html                                          # Tailor button in the drafter
    plain = render_report([a], META, PREFS, "2026-09-02")
    assert 'class="tag referral" data-server="0" hidden' in plain and 'class="refbtn"' in plain
