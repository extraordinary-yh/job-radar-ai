"""H-1B sponsorship tier per company, from the DOL LCA/PERM index shipped with career-ops.

The lookup runs locally (`plugins/h1b-sponsor/check.mjs` against `data/careerops/h1b/`),
so which employers the user checks never leaves the machine. Tiers are informational: they
never change a score. Results are cached in data/careerops/h1b_tiers.json for 30 days.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

from .careerops import CareerOpsError, data_root, run, run_json, unavailable_reason
from .models import Job

TIERS = ("strong", "moderate", "staffing-shop", "weak", "none", "unknown")
REFRESH_DAYS = 30
CHECK = "plugins/h1b-sponsor/check.mjs"
INSTALLER = "plugins/h1b-sponsor/install-h1b-index.mjs"
TIER_TEXT = {
    "strong": "files H-1B and green cards, recent and steady",
    "moderate": "recent H-1B filings, little or no green-card evidence",
    "staffing-shop": "most filings place workers at client sites",
    "weak": "few or stale filings",
    "none": "no DOL filings in the window",
    "unknown": "name not found in the DOL index",
}


def index_path(root: Path) -> Path:
    return data_root(root) / "h1b" / "index.ndjson.gz"


def has_index(root: Path) -> bool:
    return index_path(root).exists()


def _env(root: Path) -> dict[str, str]:
    return {"H1B_INDEX_PATH": str(index_path(root).resolve())}


def install_index(root: Path, force: bool = False) -> str:
    """Download the public DOL index (about 8 MiB) through career-ops's checksum-verified installer."""
    index_path(root).parent.mkdir(parents=True, exist_ok=True)
    args = ["--force"] if force else []
    proc = run(root, INSTALLER, args, env=_env(root), timeout=600)
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "installed"


def lookup(root: Path, name: str, *, refresh: bool = False, index: Path | None = None) -> dict[str, Any]:
    """Raw check.mjs JSON for one company name (found, displayName, totals, friendlinessTier, ...)."""
    env = {"H1B_INDEX_PATH": str(Path(index).resolve())} if index else _env(root)
    cache = data_root(root) / "cache" / "h1b"
    args = [name, "--json", "--cache-dir", str(cache)] + (["--refresh"] if refresh else [])
    return run_json(root, CHECK, args, env=env, timeout=120)


def search(root: Path, name: str) -> list[dict[str, str]]:
    """Matching employer entities ranked by filing volume: [{id, name}, ...]."""
    out = run_json(root, CHECK, [name, "--search", "--json"], env=_env(root), timeout=120)
    return [r for r in (out.get("results") or []) if isinstance(r, dict) and r.get("name")]


LOW_VOLUME = 5


def lookup_best(root: Path, name: str, *, refresh: bool = False) -> dict[str, Any]:
    """Summarized lookup that escapes a zero-volume exact match ("Microsoft" is a 0-LCA entity;
    "Microsoft Corporation" has tens of thousands) by trying the largest search hit instead."""
    best = summarize(lookup(root, name, refresh=refresh), name)
    if best["found"] and best["n_lca"] + best["n_perm"] + best["n_pwd"] >= LOW_VOLUME:
        return best
    try:
        hits = search(root, name)
    except CareerOpsError:
        return best
    top = hits[0]["name"] if hits else ""
    if not top or top.strip().lower() == best["employer"].strip().lower():
        return best
    alt = summarize(lookup(root, top, refresh=refresh), name)
    if alt["found"] and alt["n_lca"] + alt["n_perm"] + alt["n_pwd"] > best["n_lca"] + best["n_perm"] + best["n_pwd"]:
        alt["resolved_from"] = name
        return alt
    return best


_SUFFIXES = ("incorporated", "corporation", "company", "limited", "holdings", "inc", "llc", "corp", "ltd", "plc", "pbc", "co", "lp", "the")


def name_tokens(name: str) -> list[str]:
    """Lower-case alphanumeric words with common legal suffixes removed: 'C3.ai, Inc.' -> ['c3', 'ai']."""
    import re
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    while words and words[-1] in _SUFFIXES:
        words.pop()
    while words and words[0] in _SUFFIXES:
        words.pop(0)
    return words


def fold_name(name: str) -> str:
    return "".join(name_tokens(name))


def names_agree(query: str, employer: str) -> bool:
    """Does the DOL entity plausibly *be* the company on the card, not just the closest string?

    The card's name must appear as whole words, in order, inside the entity name ('Stripe' in 'Stripe, LLC';
    'C3 AI' in 'C3.ai, Inc.'), or the two must be the same once spaces go ('Acme Media' vs 'AcmeMedia')."""
    q, e = name_tokens(query), name_tokens(employer)
    if not q or not e:
        return False
    if "".join(q) == "".join(e):
        return True
    n = len(q)
    return any(e[i:i + n] == q for i in range(len(e) - n + 1))


def summarize(result: dict[str, Any], query: str | None = None) -> dict[str, Any]:
    """The subset we keep per company: tier, counts, years, and a one-line note for the card.

    With `query`, a resolved entity whose name does not contain the query (or vice versa) is demoted to
    unknown: the index resolver returns the closest string, and for a small startup that is often a
    different employer entirely."""
    tier = str(result.get("friendlinessTier") or "unknown")
    if tier not in TIERS:
        tier = "unknown"
    t = result.get("totals") or {}
    out = {"tier": tier, "found": bool(result.get("found")), "employer": str(result.get("displayName") or ""),
           "n_lca": int(t.get("n_lca") or 0), "n_perm": int(t.get("n_perm") or 0), "n_pwd": int(t.get("n_pwd") or 0),
           "first_year": t.get("first_year"), "last_year": t.get("last_year")}
    if query is not None and out["found"] and not names_agree(query, out["employer"]):
        out.update(tier="unknown", found=False, name_mismatch=out["employer"])
        out["note"] = f"closest DOL entity is '{out['name_mismatch']}', which does not look like the same employer"
        return out
    out["note"] = note_for(out)
    return out


def note_for(s: dict[str, Any]) -> str:
    if not s.get("found"):
        return TIER_TEXT["unknown"]
    years = ""
    if s.get("first_year") and s.get("last_year"):
        years = f" · active {s['first_year']}–{s['last_year']}"
    counts = f"{s['n_lca']:,} LCAs · {s['n_perm']:,} PERMs"
    return f"{s['employer']} · {counts}{years} · {TIER_TEXT.get(s['tier'], '')}".strip(" ·")


def tiers_path(root: Path) -> Path:
    return data_root(root) / "h1b_tiers.json"


def load_tiers(root: Path) -> dict[str, dict[str, Any]]:
    p = tiers_path(root)
    return json.loads(p.read_text()) if p.exists() else {}


def save_tiers(root: Path, tiers: dict[str, dict[str, Any]]) -> None:
    tiers_path(root).write_text(json.dumps(dict(sorted(tiers.items())), indent=1, ensure_ascii=False) + "\n")


def _stale(entry: dict[str, Any], today: str) -> bool:
    try:
        checked = dt.date.fromisoformat(str(entry.get("checked", "")))
    except ValueError:
        return True
    return (dt.date.fromisoformat(today) - checked).days >= REFRESH_DAYS


MAX_NEW_PER_RUN = 40


def annotate(jobs: list[Job], root: Path, today: str, *, lookup_fn: Callable[..., dict[str, Any]] | None = None,
             warnings: list[str] | None = None, aliases: dict[str, str] | None = None,
             max_new: int = MAX_NEW_PER_RUN) -> dict[str, dict[str, Any]]:
    """Set job.h1b_tier / job.h1b_note on visible jobs, looking up each distinct company at most once per 30 days.

    Excluded jobs are skipped (an aggregator thread brings hundreds of employers nobody will apply to) and at
    most `max_new` fresh lookups run per call, each costing about two seconds of index scan; the rest wait
    for the next run. `lookup_fn(name)` must return a summarized entry (see `lookup_best`); `aliases` maps a
    card's company name to the employer name as filed with DOL (`h1b_name` in companies.yaml).
    """
    warnings = warnings if warnings is not None else []
    aliases = aliases or {}
    reason = unavailable_reason(root)
    if reason:
        warnings.append(f"h1b: {reason}")
        return {}
    if not has_index(root):
        warnings.append("h1b: DOL index not installed; run `uv run jobradar h1b --install`")
        return {}
    do_lookup = lookup_fn or (lambda name: lookup_best(root, name))
    tiers = load_tiers(root)
    failed: list[str] = []
    deferred = 0
    wanted = sorted({j.company for j in jobs if not j.excluded})
    for name in wanted:
        entry = tiers.get(name)
        query = aliases.get(name, name)
        if entry is None or _stale(entry, today) or entry.get("query", name) != query:
            if max_new <= 0:
                deferred += 1
                continue
            max_new -= 1
            try:
                entry = do_lookup(query)
            except CareerOpsError as e:
                failed.append(f"{name} ({str(e)[:80]})")
                continue
            entry["checked"] = today
            if query != name:
                entry["query"] = query
            tiers[name] = entry
    save_tiers(root, tiers)
    for j in jobs:
        entry = tiers.get(j.company)
        if entry:
            j.h1b_tier, j.h1b_note = entry["tier"], entry["note"]
    if failed:
        warnings.append("h1b: lookup failed for " + ", ".join(failed[:5]))
    if deferred:
        warnings.append(f"h1b: {deferred} companies not looked up yet (budget of {MAX_NEW_PER_RUN} per run); they get tiers on later runs")
    return tiers
