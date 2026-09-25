import json
from pathlib import Path

import httpx
import pytest

from jobradar.adapters.base import get_adapter, register
from jobradar.errors import AdapterError
from jobradar.http import FixtureClient, HttpClient


def make_client(handler, **kw):
    client = HttpClient(retries=3, pace_seconds=0, sleep=lambda s: None, **kw)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return client


def test_get_text_retries_on_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(500) if len(calls) < 3 else httpx.Response(200, text="hello")

    assert make_client(handler).get_text("https://x/a") == "hello"
    assert len(calls) == 3


def test_get_text_raises_adapter_error_after_retries():
    def handler(request):
        return httpx.Response(503)

    with pytest.raises(AdapterError, match="after 3 attempts"):
        make_client(handler).get_text("https://x/a")


def test_get_json_parses_and_saves_raw(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"a": 1})

    client = make_client(handler, raw_dir=tmp_path)
    assert client.get_json("https://x/j", fixture_key="search") == {"a": 1}
    saved = list(tmp_path.glob("*.json"))
    assert saved and json.loads(saved[0].read_text()) == {"a": 1}


def test_fixture_client_reads_files(tmp_path):
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "search.json").write_text('{"jobs": []}')
    (tmp_path / "acme" / "detail.html").write_text("<p>x</p>")
    fc = FixtureClient(tmp_path, "acme")
    assert fc.get_json("https://ignored", fixture_key="search") == {"jobs": []}
    assert fc.get_text("https://ignored", fixture_key="detail") == "<p>x</p>"
    with pytest.raises(FileNotFoundError):
        fc.get_text("https://ignored", fixture_key="missing")


def test_adapter_registry():
    @register
    class Dummy:
        kind = "dummy"

        def search(self, cfg, client):
            return []

        def enrich(self, raw, client):
            return raw

    assert isinstance(get_adapter("dummy"), Dummy)
    with pytest.raises(AdapterError, match="unknown adapter"):
        get_adapter("nope")


def test_post_json_sends_body_and_parses(tmp_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"total": 1})

    client = make_client(handler, raw_dir=tmp_path)
    assert client.post_json("https://x/jobs", json_body={"searchText": "swe"}, fixture_key="search") == {"total": 1}
    assert seen == {"method": "POST", "body": {"searchText": "swe"}}


def test_get_text_retries_on_429_with_backoff():
    calls, slept = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 2 else httpx.Response(200, text="ok")

    client = HttpClient(retries=3, pace_seconds=0, sleep=lambda s: slept.append(s))
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert client.get_text("https://x/a") == "ok" and len(calls) == 2 and 15 in slept
