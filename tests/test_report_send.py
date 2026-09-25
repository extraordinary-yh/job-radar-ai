"""The report's Send-to-repo button: draft lines → data/feedback.jsonl records committed through the GitHub API."""
import base64
import json
from pathlib import Path

import pytest

from jobradar.feedback import latest_verdicts, referral_marks
from jobradar.render import render_report
from tests.test_render import META, PREFS, job

REPO = Path(__file__).resolve().parents[1]
WRITE = {"repo": "owner/job-radar", "branch": "main", "api": "http://api.test"}




def test_send_button_only_with_a_write_target():
    html = render_report([job(1)], META, PREFS, "2026-09-10", write=WRITE)
    assert 'id="send"' in html and "owner/job-radar" in html and "function HubWriter" in html
    assert html.index("function HubWriter") < html.index('id="send"') or html.index("function HubWriter") < html.index("var WRITE")
    plain = render_report([job(1)], META, PREFS, "2026-09-10")
    assert '<button id="send"' not in plain and "function HubWriter" not in plain and "paste it to your agent" in plain


@pytest.mark.browser
def test_fit_reason_and_company_ignore_are_saved_as_distinct_feedback(tmp_path, browser):
    html = render_report([job(1, id="apple:1", company="Apple"), job(2, id="apple:2", company="Apple")], META, PREFS, "2026-09-11")
    page_file = tmp_path / "report.html"
    page_file.write_text(html)
    page = browser.new_page()
    page.goto(page_file.as_uri())
    page.click('.card[data-id="apple:1"] .fb button[data-verdict="bad"]')
    assert page.locator("#fit-dialog").evaluate("el => el.open")
    page.click('#fit-form button[value="save"]')
    assert "bad apple:1 years of experience too high" in page.input_value("#feedback")
    page.click('.card[data-id="apple:2"] .fb button[data-role-ignore]')
    assert "bad apple:2 not interested in this posting" in page.input_value("#feedback")
    page.click('.card[data-id="apple:2"] .fb button[data-company-ignore]')
    value = page.input_value("#feedback")
    assert '"kind":"company_ignore"' in value and '"company_key":"apple"' in value
    assert "done" in page.get_attribute('.card[data-id="apple:1"]', "class")
    assert "done" in page.get_attribute('.card[data-id="apple:2"]', "class")
    page.close()


@pytest.mark.browser
def test_role_not_interested_is_unselected_by_default(tmp_path, browser):
    html = render_report([job(1, id="apple:1", company="Apple")], META, PREFS, "2026-09-12")
    page_file = tmp_path / "report.html"
    page_file.write_text(html)
    page = browser.new_page()
    page.goto(page_file.as_uri())
    role_button = page.locator('.card[data-id="apple:1"] [data-role-ignore]')
    assert "on" not in (role_button.get_attribute("class") or "").split()
    assert page.input_value("#feedback") == ""
    page.close()


@pytest.mark.browser
def test_send_commits_feedback_lines_the_cli_can_read(tmp_path, browser):
    html = render_report([job(1, id="google:1"), job(2, id="figma:2", company="Figma")], META, PREFS, "2026-09-10", write=WRITE)
    page_file = tmp_path / "report.html"
    page_file.write_text(html)
    puts: list[dict] = []

    def api(route, request):
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"}
        if request.method == "OPTIONS":
            route.fulfill(status=204, headers=cors)
        elif request.method == "GET":
            route.fulfill(status=404, headers={**cors, "content-type": "application/json"}, body=json.dumps({"message": "Not Found"}))
        else:
            puts.append({"url": request.url, "body": json.loads(request.post_data or "{}")})
            route.fulfill(status=201, headers={**cors, "content-type": "application/json"},
                          body=json.dumps({"commit": {"sha": "abc1234def"}, "content": {"sha": "x"}}))

    page = browser.new_page()
    page.route("http://api.test/**", api)
    page.goto(page_file.as_uri())
    page.evaluate("localStorage.setItem('hub.token', 'ghp_test')")
    page.click('.card[data-id="google:1"] .fb button[data-verdict="applied"]')
    page.click('.card[data-id="figma:2"] .refbtn')
    assert "applied google:1" in page.input_value("#feedback") and "referral figma:2" in page.input_value("#feedback")
    page.click("#send")
    page.wait_for_function("document.getElementById('sendmsg').textContent.startsWith('committed')", timeout=10000)
    assert len(puts) == 1
    put = puts[0]
    assert put["url"].endswith("/repos/owner/job-radar/contents/data/feedback.jsonl")
    assert put["body"]["message"] == "feedback: 2026-09-10 2 line(s) from the report" and put["body"]["branch"] == "main"
    text = base64.b64decode(put["body"]["content"]).decode()
    fb = tmp_path / "feedback.jsonl"
    fb.write_text(text)
    assert latest_verdicts(fb)["google:1"]["verdict"] == "applied" and latest_verdicts(fb)["google:1"]["stage"] == "applied"
    assert referral_marks(fb) == {"figma:2": True}
    # the box is empty again, the card stays applied, and a second send has nothing to do
    assert page.input_value("#feedback") == ""
    assert "applied" in page.get_attribute('.card[data-id="google:1"]', "class")
    page.click("#send")
    page.wait_for_function("document.getElementById('sendmsg').textContent === 'nothing to send'", timeout=5000)
    assert len(puts) == 1
    page.close()


@pytest.mark.browser
def test_unmarked_referral_chip_is_hidden(tmp_path, browser):
    path=tmp_path/'report.html'
    path.write_text(render_report([job(1)], META, PREFS, '2026-09-10'))
    page=browser.new_page()
    page.goto(path.as_uri())
    assert page.locator('.tag.referral').is_hidden()
    page.close()
