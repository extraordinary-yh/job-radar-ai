from __future__ import annotations

import datetime as _dt
from typing import Protocol

from ..config import CompanyConfig
from ..errors import AdapterError
from ..models import RawJob


class Adapter(Protocol):
    kind: str

    def search(self, cfg: CompanyConfig, client) -> list[RawJob]: ...

    def enrich(self, raw: RawJob, client) -> RawJob: ...


_REGISTRY: dict[str, type] = {}


def register(cls):
    _REGISTRY[cls.kind] = cls
    return cls


def get_adapter(kind: str) -> Adapter:
    try:
        return _REGISTRY[kind]()
    except KeyError:
        raise AdapterError(f"unknown adapter: {kind}") from None


def dedupe(raws: list[RawJob]) -> list[RawJob]:
    seen: set[str] = set()
    out: list[RawJob] = []
    for r in raws:
        if r.source_id not in seen:
            seen.add(r.source_id)
            out.append(r)
    return out


def iso_to_ts(s: str | None) -> int | None:
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return int(d.timestamp())


__all__ = ["Adapter", "AdapterError", "register", "get_adapter", "dedupe", "iso_to_ts"]
