import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jobradar.publish import (build_shell, build_site, commit_and_push, decrypt_html, encrypt_html, ensure_site_repo,
                              get_or_create_salt, load_dotenv, load_publish_config)

NODE = shutil.which("node")


def test_encrypt_decrypt_round_trip_and_wrong_passphrase():
    salt = b"0123456789abcdef"
    payload = encrypt_html("<html>secret</html>", "correct horse", salt, iterations=1000)
    assert set(payload) >= {"v", "kdf", "iterations", "salt", "nonce", "ct"}
    assert base64.b64decode(payload["salt"]) == salt
    assert decrypt_html(payload, "correct horse") == "<html>secret</html>"
    with pytest.raises(Exception):
        decrypt_html(payload, "wrong")


def test_salt_persists_in_config(tmp_path):
    cfg = tmp_path / "publish.yaml"
    cfg.write_text("reports_repo: https://example.com/r.git\n")
    s1 = get_or_create_salt(cfg)
    s2 = get_or_create_salt(cfg)
    assert s1 == s2 and len(s1) == 16 and "salt_b64" in cfg.read_text()
    assert load_publish_config(cfg)["reports_repo"] == "https://example.com/r.git"


def test_load_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBRADAR_PASSPHRASE", raising=False)
    (tmp_path / ".env").write_text("# comment\nJOBRADAR_PASSPHRASE='a b c'\nOTHER=1\n")
    load_dotenv(tmp_path / ".env")
    import os
    assert os.environ["JOBRADAR_PASSPHRASE"] == "a b c" and os.environ["OTHER"] == "1"
    load_dotenv(tmp_path / "missing.env")   # no error


def test_build_shell_embeds_payload_and_has_no_external_assets():
    payload = encrypt_html("<p>x</p>", "pw", b"s" * 16, iterations=1000)
    html = build_shell(payload, "job-radar · 2026-09-01")
    assert payload["ct"] in html and "PBKDF2" in html and "AES-GCM" in html and "SHA-256" in html
    assert "<title>job-radar · 2026-09-01</title>" in html
    assert 'src="http' not in html and 'href="http' not in html


def test_build_site_writes_index_archive_and_nojekyll(tmp_path):
    root = tmp_path / "repo"
    (root / "reports").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "publish.yaml").write_text("reports_repo: x\n")
    (root / "reports" / "index.html").write_text("<html>report</html>")
    site = build_site(root, "2026-09-01", "pw", tmp_path / "site")
    assert (site / "index.html").exists() and (site / "archive" / "2026-09-01.html").exists() and (site / ".nojekyll").exists()
    assert "<html>report</html>" not in (site / "index.html").read_text()      # encrypted, not plain


def test_ensure_site_repo_and_push_to_local_bare(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    site = tmp_path / "site"
    ensure_site_repo(site, str(bare))
    (site / "index.html").write_text("one")
    assert commit_and_push(site, "first") is True
    assert commit_and_push(site, "nothing") is False
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "--oneline", "main"], capture_output=True, text=True).stdout
    assert "first" in log
    ensure_site_repo(site, str(bare))                              # idempotent on an existing clone


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_shell_algorithm_decrypts_in_webcrypto(tmp_path):
    payload = encrypt_html("<html>from python</html>", "pass phrase", b"z" * 16, iterations=1000)
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload))
    script = Path(__file__).parent / "decrypt_shell.mjs"
    out = subprocess.run([NODE, str(script), str(p), "pass phrase"], capture_output=True, text=True, check=True).stdout
    assert out == "<html>from python</html>"


# ---------------------------------------------------------------- the hub next to the report

def _hub(tmp_path):
    hub = tmp_path / "hub"
    (hub / "week").mkdir(parents=True)
    (hub / "day").mkdir()
    (hub / "index.html").write_text('<!doctype html><script>location.replace("week/2026-W37.html")</script>')
    (hub / "index.json").write_text('{"days": {}}')
    (hub / "week" / "2026-W37.html").write_text('<html><body><h1 id="w">2026-W37</h1><a id="to-day" href="../day/2026-09-07.html">Mon 7</a></body></html>')
    (hub / "day" / "2026-09-07.html").write_text('<html><body><h1 id="d">Study board · 2026-09-07</h1></body></html>')
    return hub


def _root(tmp_path):
    root = tmp_path / "repo"
    (root / "reports").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "publish.yaml").write_text("reports_repo: x\n")
    (root / "reports" / "index.html").write_text("<html>report</html>")
    return root


def test_build_hub_encrypts_every_page_keeps_the_redirect_plain_and_prunes(tmp_path):
    from jobradar.publish import build_hub
    root, hub, site = _root(tmp_path), _hub(tmp_path), tmp_path / "site"
    build_site(root, "2026-09-07", "pw", site)
    assert build_hub(root, hub, "pw", site) == 3
    week = (site / "hub" / "week" / "2026-W37.html").read_text()
    assert "2026-W37" not in week.split("<script id=\"payload\"")[0] or "<title>study hub · week · 2026-W37</title>" in week
    assert 'id="w"' not in week and "AES-GCM" in week and "<h1>study hub</h1>" in week      # ciphertext, hub-branded shell
    assert (site / "hub" / "index.html").read_text().startswith("<!doctype html><script>")   # the redirect stays plain
    assert not (site / "hub" / "index.json").exists()                                         # data is never published
    payload = json.loads(week.split('<script id="payload" type="application/json">')[1].split("</script>")[0])
    assert 'id="to-day" href="../day/2026-09-07.html"' in decrypt_html(payload, "pw")          # relative links survive
    assert (site / "archive" / "2026-09-07.html").exists()                                    # the report is untouched

    (hub / "day" / "2026-09-07.html").unlink()
    assert build_hub(root, hub, "pw", site) == 2
    assert not (site / "hub" / "day").exists()                                                # stale page and empty dir gone


def test_build_events_encrypts_the_dated_event_reports_next_to_the_archive_and_prunes(tmp_path):
    from jobradar.publish import build_events
    root, site = _root(tmp_path), tmp_path / "site"
    assert build_events(root, "pw", site) == 0 and not (site / "events").exists()       # no sf-events reports: nothing
    reports = root / "sf-events" / "reports"
    reports.mkdir(parents=True)
    (reports / "2026-09-06.html").write_text("<html><h1 id='e'>events 06</h1></html>")
    (reports / "2026-09-07.html").write_text("<html><h1 id='e'>events 07</h1></html>")
    (reports / "index.html").write_text("<html>latest</html>")                              # not dated: never published
    build_site(root, "2026-09-07", "pw", site)
    assert build_events(root, "pw", site) == 2
    assert sorted(p.name for p in (site / "events").glob("*.html")) == ["2026-09-06.html", "2026-09-07.html"]
    page = (site / "events" / "2026-09-07.html").read_text()
    assert "events 07" not in page and "<title>sf-events · 2026-09-07</title>" in page and "<h1>sf-events</h1>" in page
    payload = json.loads(page.split('<script id="payload" type="application/json">')[1].split("</script>")[0])
    assert "events 07" in decrypt_html(payload, "pw")
    assert payload["salt"] == json.loads((site / "archive" / "2026-09-07.html").read_text()
                                         .split('<script id="payload" type="application/json">')[1].split("</script>")[0])["salt"]
    (reports / "2026-09-06.html").unlink()
    assert build_events(root, "pw", site) == 1
    assert not (site / "events" / "2026-09-06.html").exists()                                # pruned like the hub's pages




@pytest.mark.browser
def test_decrypted_hub_opens_in_chromium_and_navigates_with_the_remembered_key(tmp_path, browser):
    from jobradar.publish import build_hub
    root, hub, site = _root(tmp_path), _hub(tmp_path), tmp_path / "site"
    build_site(root, "2026-09-07", "correct horse", site)
    build_hub(root, hub, "correct horse", site)
    page = browser.new_page()
    page.goto((site / "hub" / "week" / "2026-W37.html").as_uri())
    page.fill("#p", "correct horse")
    page.click("button[type=submit]")
    page.wait_for_selector("#w", timeout=15000)                          # decrypted in the browser with WebCrypto
    assert page.inner_text("#w") == "2026-W37"
    page.click("#to-day")                                                # the next shell opens with the remembered key
    page.wait_for_selector("#d", timeout=15000)
    assert "2026-09-07" in page.inner_text("#d") and page.url.endswith("/hub/day/2026-09-07.html")
    page.close()
