import json
import shutil
import threading
import uuid
from pathlib import Path

import httpx
import pytest

from jobradar.feedback import latest_verdicts
from jobradar.local import Board, make_server
from jobradar.models import Job
from jobradar.store import save_snapshot


@pytest.fixture
def board_root(tmp_path):
    (tmp_path / 'profile').mkdir()
    shutil.copy(Path(__file__).resolve().parents[1] / 'examples/profile/preferences.yaml', tmp_path / 'profile/preferences.yaml')
    jobs = [Job(id=f'example:{i}', company='Example', title=f'Engineer {i}', url=f'https://example.com/{i}',
                score=80, rank_score=80, status='new') for i in (1, 2)]
    save_snapshot(tmp_path / 'data/jobs', '2026-10-01', jobs, {})
    return tmp_path


@pytest.fixture
def local_server(board_root):
    server = make_server(board_root, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    yield server, url
    server.shutdown()
    server.server_close()
    thread.join()


def test_persistence_retry_and_batch_validation(board_root):
    board = Board(board_root)
    request_id = str(uuid.uuid4())
    board.save('applied example:1', request_id)
    # Retry after a full backend restart is idempotent.
    restarted = Board(board_root)
    restarted.save('applied example:1', request_id)
    assert len(board.feedback.read_text().splitlines()) == 1
    assert latest_verdicts(board.feedback)['example:1']['verdict'] == 'applied'
    assert 'Applied (1)' in restarted.html()
    with pytest.raises(ValueError):
        board.save('applied example:2\nstage missing:1 phone', str(uuid.uuid4()))
    with pytest.raises(ValueError):
        board.save('stage example:2 invented', str(uuid.uuid4()))
    with pytest.raises(ValueError):
        board.save('applied example:2', request_id)
    assert len(board.feedback.read_text().splitlines()) == 1
    board.save('stage example:1 phone', str(uuid.uuid4()))
    assert latest_verdicts(board.feedback)['example:1']['stage'] == 'phone'


def test_not_fit_and_applied_survive_next_scan_and_backend_restart(board_root):
    board = Board(board_root)
    board.save('bad example:1 role feels too technical right now\napplied example:2', str(uuid.uuid4()))
    _, meta, jobs = board.snapshot()
    save_snapshot(board_root / 'data/jobs', '2026-10-02', jobs, meta)
    restarted = Board(board_root)
    html = restarted.html()
    assert restarted.snapshot()[0] == '2026-10-02'
    assert 'data-id="example:1"' not in html
    assert 'data-verdict="applied"' in html and 'Applied (1)' in html


def test_http_rejects_external_writes_and_private_files(local_server):
    server, url = local_server
    payload = {'text': 'applied example:1', 'request_id': str(uuid.uuid4())}
    with httpx.Client(trust_env=False) as client:
        assert client.get(url + '/').status_code == 200
        assert client.get(url + '/.env').status_code == 404
        assert client.get(url + '/data/feedback.jsonl').status_code == 404
        assert client.get(url + '/', headers={'Host': 'attacker.example'}).status_code == 403
        assert client.post(url + '/api/feedback', json=payload).status_code == 403
        assert client.post(url + '/api/feedback', json=payload, headers={
            'Origin': 'https://attacker.example', 'X-JobRadar-Token': server.board.token}).status_code == 403
        assert not server.board.feedback.exists()
        result = client.post(url + '/api/feedback', json=payload, headers={
            'Origin': url, 'X-JobRadar-Token': server.board.token})
        assert result.status_code == 200 and result.json()['saved'] == 1


@pytest.mark.browser
def test_click_refresh_new_browser_and_stage(browser, local_server):
    server, url = local_server
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url)
    page.locator('[data-id="example:1"] button[data-verdict="applied"]').click()
    page.wait_for_function("document.querySelector('#local-status').textContent === 'Saved on this computer'")
    assert latest_verdicts(server.board.feedback)['example:1']['verdict'] == 'applied'
    assert 'Applied (1)' in page.locator('#sidebtn').inner_text()
    page.reload()
    assert page.locator('#cards [data-id="example:1"]').get_attribute('data-verdict') == 'applied'
    # A fresh context has no localStorage: persistence must come from the ledger.
    context = browser.new_context()
    fresh = context.new_page()
    fresh.goto(url)
    fresh.locator('#sidebtn').click()
    fresh.locator('#side select.stage').select_option('phone')
    fresh.wait_for_function("document.querySelector('#local-status').textContent === 'Saved on this computer'")
    fresh.reload()
    assert fresh.locator('#side select.stage').input_value() == 'phone'
    assert not errors
    context.close()
    page.close()


@pytest.mark.browser
def test_failed_save_retains_draft_and_retry(browser, local_server):
    server, url = local_server
    page = browser.new_page()
    page.goto(url)
    page.route('**/api/feedback', lambda route: route.abort())
    page.locator('[data-id="example:2"] button[data-verdict="applied"]').click()
    page.wait_for_function("document.querySelector('#local-status').textContent.startsWith('Not confirmed saved:')")
    assert not server.board.feedback.exists()
    assert 'applied example:2' in page.locator('#feedback').input_value()
    page.unroute('**/api/feedback')
    page.locator('#local-save').click()
    page.wait_for_function("document.querySelector('#local-status').textContent === 'Saved on this computer'")
    assert len(server.board.feedback.read_text().splitlines()) == 1
    page.close()


@pytest.mark.browser
def test_not_fit_stays_hidden_after_sort_reload_and_new_browser(browser, local_server):
    server, url = local_server
    page = browser.new_page()
    page.goto(url)
    page.locator('[data-id="example:1"] button[data-verdict="bad"]').click()
    page.locator('#fit-form button[value="save"]').click()
    page.wait_for_function("document.querySelector('#local-status').textContent === 'Saved on this computer'")
    page.locator('#sort').select_option('company')
    assert page.locator('#cards [data-id="example:1"]').count() == 0
    page.reload()
    assert page.locator('#cards [data-id="example:1"]').count() == 0
    assert latest_verdicts(server.board.feedback)['example:1']['verdict'] == 'bad'
    context = browser.new_context()
    fresh = context.new_page()
    fresh.goto(url)
    assert fresh.locator('#cards [data-id="example:1"]').count() == 0
    context.close()
    page.close()


@pytest.mark.browser
def test_invalid_recovery_can_be_corrected_without_losing_the_draft(browser, local_server):
    server, url = local_server
    page = browser.new_page()
    page.goto(url)
    page.locator('#feedback').fill('applied missing:1')
    page.locator('#local-save').click()
    page.wait_for_function("document.querySelector('#local-status').textContent.startsWith('Not confirmed saved:')")
    assert page.locator('#feedback').input_value() == 'applied missing:1'
    assert page.locator('#feedback').is_editable()
    page.locator('#feedback').fill('applied example:1')
    page.locator('#local-save').click()
    page.wait_for_function("document.querySelector('#local-status').textContent === 'Saved on this computer'")
    assert latest_verdicts(server.board.feedback)['example:1']['verdict'] == 'applied'
    page.close()
