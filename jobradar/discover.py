"""Turn career-ops discover-ats.mjs output into companies.yaml entries for job-radar's own adapters."""
from __future__ import annotations

import re
from typing import Any

NATIVE = {"greenhouse": "greenhouse", "ashby": "ashby", "lever": "lever", "workday": "workday"}


def slug_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "company"


def entry_for(r: dict[str, Any]) -> str:
    name, vendor, slug = str(r.get("name") or ""), str(r.get("vendor") or ""), str(r.get("slug") or "")
    url = str(r.get("careers_url") or "")
    count = r.get("jobCount")
    note = f"   # {count} postings via {vendor}" if count is not None else f"   # via {vendor}"
    lines = [f"  - name: {name}", f"    key: {slug_key(name)}"]
    if vendor in NATIVE and vendor != "workday":
        lines += [f"    adapter: {NATIVE[vendor]}", f"    board: {slug}{note}"]
    elif vendor == "workday":
        lines += ["    adapter: careerops", "    provider: workday", f"    careers_url: {url}{note}"]
    else:
        lines += ["    adapter: careerops", f"    provider: {vendor}", f"    careers_url: {url}{note}"]
    lines += ["    size: small", "    enabled: true"]
    return "\n".join(lines)


def format_entries(out: dict[str, Any]) -> str:
    resolved = out.get("resolved") or []
    unresolved = out.get("unresolved") or []
    parts = [entry_for(r) for r in resolved]
    text = "\n\n".join(parts) if parts else "(no boards resolved)"
    if unresolved:
        names = ", ".join(str(u.get("name") or u) for u in unresolved)
        text += f"\n\n# unresolved (JS-rendered portal, custom slug, or Workday without a hint): {names}"
    return text
