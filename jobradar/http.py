"""HTTP access with retries, pacing, and raw-response capture; plus an offline fixture client."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .errors import AdapterError

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 jobradar/0.1")


class HttpClient:
    def __init__(self, *, timeout: float = 30.0, retries: int = 3, pace_seconds: float = 0.5,
                 raw_dir: Path | None = None, sleep=time.sleep) -> None:
        self.retries = retries
        self.pace_seconds = pace_seconds
        self.raw_dir = raw_dir
        self._sleep = sleep
        self._n = 0
        self._client = httpx.Client(timeout=timeout, follow_redirects=True,
                                    headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

    def _get(self, url: str, params: dict | None, headers: dict | None, json_body: Any = None) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = (self._client.post(url, params=params, headers=headers, json=json_body) if json_body is not None
                     else self._client.get(url, params=params, headers=headers))
                if r.status_code == 429:
                    self._sleep(15 * (attempt + 1))           # rate limited: wait, then retry
                    raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"server error {r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    raise AdapterError(f"GET {url} -> {r.status_code}")
                if self.pace_seconds:
                    self._sleep(self.pace_seconds)
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                self._sleep(2 ** attempt)
        raise AdapterError(f"GET {url} failed after {self.retries} attempts: {last}")

    def _save(self, content: str, fixture_key: str, ext: str) -> None:
        if not self.raw_dir:
            return
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._n += 1
        safe = re.sub(r"[^a-z0-9]+", "-", fixture_key.lower()) or "resp"
        (self.raw_dir / f"{self._n:03d}-{safe}.{ext}").write_text(content)

    def get_text(self, url: str, *, params: dict | None = None, headers: dict | None = None,
                 fixture_key: str = "") -> str:
        text = self._get(url, params, headers).text
        self._save(text, fixture_key, "html")
        return text

    def get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None,
                 fixture_key: str = "") -> Any:
        r = self._get(url, params, {**(headers or {}), "Accept": "application/json"})
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"GET {url} returned non-JSON: {e}") from e
        self._save(json.dumps(data), fixture_key, "json")
        return data

    def post_json(self, url: str, *, json_body: Any, params: dict | None = None, headers: dict | None = None,
                  fixture_key: str = "") -> Any:
        r = self._get(url, params, {**(headers or {}), "Accept": "application/json"}, json_body=json_body)
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"POST {url} returned non-JSON: {e}") from e
        self._save(json.dumps(data), fixture_key, "json")
        return data

    def close(self) -> None:
        self._client.close()


class FixtureClient:
    """Serves recorded responses from tests/fixtures/<kind>/<fixture_key>.*; used by --offline and tests."""

    def __init__(self, fixtures_root: Path, kind: str) -> None:
        self.dir = Path(fixtures_root) / kind

    def _path(self, fixture_key: str) -> Path:
        for ext in ("html", "json", "txt"):
            p = self.dir / f"{fixture_key}.{ext}"
            if p.exists():
                return p
        raise FileNotFoundError(f"no fixture {self.dir}/{fixture_key}.(html|json|txt)")

    def get_text(self, url: str, *, params=None, headers=None, fixture_key: str = "") -> str:
        return self._path(fixture_key).read_text()

    def get_json(self, url: str, *, params=None, headers=None, fixture_key: str = "") -> Any:
        return json.loads(self._path(fixture_key).read_text())

    def post_json(self, url: str, *, json_body=None, params=None, headers=None, fixture_key: str = "") -> Any:
        return json.loads(self._path(fixture_key).read_text())

    def close(self) -> None:
        return None
