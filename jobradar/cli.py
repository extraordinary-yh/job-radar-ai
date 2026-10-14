"""Command-line entry point: uv run jobradar <command>."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

from .config import load_preferences, repo_root
from .evaluate import evaluate, format_report
from .feedback import append_feedback, applied_archive, latest_verdicts, parse_feedback_text, pending_tailors
from .notify import build_digest, send_telegram, telegram_credentials
from .pipeline import run
from .publish import (build_events, build_hub, build_site, commit_and_push, ensure_site_repo, load_dotenv,
                      load_publish_config)
from .store import SeenStore, breakage_warnings, list_snapshots, load_snapshot


def _today() -> str:
    return dt.date.today().isoformat()


def cmd_run(args) -> int:
    root = repo_root()
    r = run(root, args.date, offline=args.offline, fixtures_root=Path(args.fixtures) if args.fixtures else None,
            company_filter=set(args.company) if args.company else None,
            review_path=Path(args.review) if args.review else None, skip_fetch=args.skip_fetch)
    for s in r.sources:
        print(f"  {s.company}: {s.count} jobs" if s.ok else f"  {s.company}: FAILED {s.error}")
    visible = [j for j in r.jobs if not j.excluded and not j.hidden]
    new = [j for j in visible if j.status == "new"]
    print(f"{len(visible)} open, {len(new)} new, {sum(1 for j in r.jobs if j.excluded)} excluded, {r.reviewed} reviewed")
    for j in visible[:10]:
        tag = f" skills={j.score_parts.get('skills', 0)}{'*' if j.review else ''}" if j.score_parts else ""
        print(f"  {j.rank_score:5.1f}{tag}  {j.title} — {j.company} [{j.location_class}] {j.url}")
    for w in r.warnings:
        print(f"WARNING: {w}")
    print(f"Snapshot: {r.snapshot_path}")
    print(f"Candidates: {r.candidates_path}")
    print(f"Report: {r.report_path}")
    print(f"[View Today's Openings (HTML)](<{r.report_path.resolve()}>)")
    return 0 if any(s.ok for s in r.sources) or args.skip_fetch else 1


def cmd_render(args) -> int:
    args.offline, args.fixtures, args.company, args.skip_fetch = False, None, None, True
    return cmd_run(args)


def cmd_serve(args) -> int:
    from .local import serve
    return serve(repo_root(), args.port, args.date)


def cmd_status(args) -> int:
    root = repo_root()
    snaps = list_snapshots(root / "data" / "jobs")
    if not snaps:
        print("no runs yet")
        return 0
    meta, jobs = load_snapshot(snaps[-1])
    date = snaps[-1].stem
    print(f"last run: {date} ({meta.get('generated_at', '?')})")
    for s in meta.get("sources", []):
        print(f"  {s['company']}: {s['count']} jobs" if s["ok"] else f"  {s['company']}: FAILED {s['error']}")
    print(f"  {sum(1 for j in jobs if not j.excluded and not j.hidden)} open, {sum(1 for j in jobs if j.status == 'new')} new, "
          f"{sum(1 for j in jobs if j.review)} reviewed, {len(latest_verdicts(root / 'data' / 'feedback.jsonl'))} verdicts on file")
    pending = pending_tailors(root / "data" / "feedback.jsonl", root / "data" / "applications")
    if pending:
        print(f"  tailor requests pending: {', '.join(pending)}")
    from . import followup
    overdue = [a for a in followup.annotate_archive(applied_archive(root / "data" / "feedback.jsonl", SeenStore(root / "data" / "seen.json").data["jobs"]), _today())
               if a["followup"]["urgency"] == "overdue"]
    if overdue:
        print(f"  follow-ups overdue: {len(overdue)} (run `jobradar followups --due`)")
    for w in breakage_warnings(root / "data" / "health.json", date):
        print(f"WARNING: {w}")
    return 0


def cmd_h1b(args) -> int:
    from . import h1b
    from .careerops import CareerOpsError, unavailable_reason
    root = repo_root()
    reason = unavailable_reason(root)
    if reason:
        print(reason)
        return 3
    try:
        if args.install:
            print(h1b.install_index(root, force=args.force))
            return 0
        if not args.name:
            print("usage: jobradar h1b <company name> | jobradar h1b --install [--force]")
            return 1
        if not h1b.has_index(root):
            print("DOL index not installed; run `uv run jobradar h1b --install`")
            return 3
        s = h1b.summarize(h1b.lookup(root, " ".join(args.name), refresh=args.refresh))
        print(f"{s['tier']}: {s['note']}")
        return 0
    except CareerOpsError as e:
        print(f"error: {e}")
        return 3


def cmd_connections(args) -> int:
    from . import connections
    from .careerops import CareerOpsError, unavailable_reason
    from .config import load_companies
    root = repo_root()
    if not connections.has_export(root):
        print(f"no LinkedIn export at {connections.csv_path(root)}\n"
              "LinkedIn > Settings > Data privacy > Get a copy of your data > Connections, then drop Connections.csv there.")
        return 1
    reason = unavailable_reason(root)
    if reason:
        print(reason)
        return 3
    names = [" ".join(args.name)] if args.name else [c.name for c in load_companies(root / "config" / "companies.yaml")]
    try:
        found = connections.join(root, names, include_weak=args.weak)
    except CareerOpsError as e:
        print(f"error: {e}")
        return 3
    for name in names:
        people = found.get(name, [])
        print(f"{name}: {len(people)} connection{'s' if len(people) != 1 else ''}")
        for k in people:
            bits = [b for b in (k["title"], k["linkedin"], f"{k['match']} match: {k['linkedin_company']}" if k["match"] != "exact" else "") if b]
            print(f"  · {k['name']}" + (f" — {' — '.join(bits)}" if bits else ""))
    return 0


def cmd_liveness(args) -> int:
    from . import liveness
    from .careerops import CareerOpsError, unavailable_reason
    root = repo_root()
    reason = unavailable_reason(root)
    if reason:
        print(reason)
        return 3
    urls = list(args.url)
    if not urls:
        fb = root / "data" / "feedback.jsonl"
        seen = SeenStore(root / "data" / "seen.json").data["jobs"]
        urls = [a["url"] for a in applied_archive(fb, seen) if a.get("url")]
        if not urls:
            print("nothing applied yet; pass URLs to check")
            return 0
    try:
        found = liveness.check(root, urls)
    except CareerOpsError as e:
        print(f"error: {e}")
        return 3
    icons = {"active": "open   ", "expired": "closed ", "uncertain": "unknown"}
    for u in urls:
        r = found[u]
        print(f"{icons[r['result']]} {u}" + (f"  ({r['reason']})" if r["result"] != "active" else ""))
    return 1 if any(r["result"] == "expired" for r in found.values()) else 0


def cmd_reposts(args) -> int:
    from . import reposts
    from .careerops import CareerOpsError, unavailable_reason
    root = repo_root()
    reason = unavailable_reason(root)
    if reason:
        print(reason)
        return 3
    seen = SeenStore(root / "data" / "seen.json").data["jobs"]
    reposts.export_history(root, seen)
    try:
        clusters = reposts.detect(root, window_days=args.window)
    except CareerOpsError as e:
        print(f"error: {e}")
        return 3
    if not args.all:
        clusters = reposts.real_reposts(clusters, seen, dt.date.today().isoformat())
    if not clusters:
        print("no reposted roles detected")
        return 0
    for c in clusters:
        print(f"{c.get('company')}: {c.get('role')} — {c.get('repostCount')} listings over {c.get('daysSpan')} days ({c.get('firstSeen')} → {c.get('lastSeen')})")
        for a in c.get("appearances") or []:
            print(f"    {a.get('date')}  {a.get('url')}")
    return 0


def cmd_discover(args) -> int:
    """Resolve company names to scannable ATS boards (career-ops discover-ats.mjs) and print companies.yaml entries."""
    from .careerops import CareerOpsError, data_root, run_json, unavailable_reason
    from .discover import format_entries
    root = repo_root()
    reason = unavailable_reason(root)
    if reason:
        print(reason)
        return 3
    scratch = data_root(root) / "discover-portals.yml"
    env = {"CAREER_OPS_PORTALS": str(scratch)}            # preview only; discover-ats never writes without --write
    try:
        out = run_json(root, "discover-ats.mjs", list(args.name), env=env, timeout=300)
    except CareerOpsError as e:
        print(f"error: {e}")
        return 3
    print(format_entries(out))
    return 0 if not out.get("unresolved") else 1


def cmd_followups(args) -> int:
    from . import followup
    root = repo_root()
    fb = root / "data" / "feedback.jsonl"
    seen = SeenStore(root / "data" / "seen.json").data["jobs"]
    rows = followup.annotate_archive(applied_archive(fb, seen, root / "data/applications"), args.date)
    print(followup.format_rows(rows, only_due=args.due))
    return 0


def cmd_eval(args) -> int:
    root = repo_root()
    prefs = load_preferences(root / "profile" / "preferences.yaml")
    report = evaluate(list_snapshots(root / "data" / "jobs"), latest_verdicts(root / "data" / "feedback.jsonl"), prefs, _today())
    print(format_report(report))
    return 0


def cmd_feedback(args) -> int:
    root = repo_root()
    path = root / "data" / "feedback.jsonl"
    if args.feedback_cmd == "add":
        n = append_feedback(path, [{"job_id": args.job, "verdict": args.verdict, "note": args.note or ""}])
    elif args.feedback_cmd == "stage":
        n = append_feedback(path, [{"job_id": args.job, "verdict": "applied", "stage": args.stage, "note": args.note or ""}])
    else:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
        n = append_feedback(path, parse_feedback_text(text))
    print(f"recorded {n} verdict(s) in {path}. Re-render with: uv run jobradar render --date <date>")
    return 0


def cmd_open(args) -> int:
    root = repo_root()
    pub = load_publish_config(root / "config" / "publish.yaml")
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if pub.get("feedback_mode") == "local" and pub.get("local_board_url"):
        subprocess.run([opener, str(pub["local_board_url"])], check=False)
        return 0
    index = root / "reports" / "index.html"
    if not index.exists():
        print("no report yet; run `uv run jobradar run` first")
        return 1
    subprocess.run([opener, str(index)], check=False)
    return 0


def cmd_publish(args) -> int:
    root = repo_root()
    load_dotenv(root / ".env")
    passphrase = os.environ.get("JOBRADAR_PASSPHRASE", "")
    if not passphrase:
        print("JOBRADAR_PASSPHRASE is not set (env or .env); skipping publish. The report is still in reports/index.html.")
        return 3
    cfg = load_publish_config(root / "config" / "publish.yaml")
    site = root / "site"
    if args.push:
        if not cfg.get("reports_repo"):
            print("config/publish.yaml has no reports_repo")
            return 2
        ensure_site_repo(site, cfg["reports_repo"], cfg.get("branch", "main"))
    build_site(root, args.date, passphrase, site)
    n_events = build_events(root, passphrase, site)
    print(f"events: {n_events} report(s) encrypted from {root / 'sf-events' / 'reports'} into {site / 'events'}")
    hub_dir = Path(args.hub) if args.hub else root / "study-plan" / "site" / "hub"
    message = f"report {args.date}"
    if args.no_hub:
        print("hub: skipped (--no-hub)")
    elif (hub_dir / "index.html").exists():
        n = build_hub(root, hub_dir, passphrase, site)
        print(f"hub: {n} page(s) encrypted from {hub_dir} into {site / 'hub'}")
        message += " + hub"
    else:
        print(f"hub: nothing built at {hub_dir} (run `cd study-plan && uv run studyplan hub build`); report only")
    if args.push:
        changed = commit_and_push(site, message, cfg.get("branch", "main"))
        print(f"{'Published' if changed else 'No change'}: {cfg.get('pages_url', cfg['reports_repo'])}")
    else:
        print(f"Built {site / 'index.html'} (not pushed; add --push)")
    return 0


def cmd_notify(args) -> int:
    root = repo_root()
    load_dotenv(root / ".env")
    snap = root / "data" / "jobs" / f"{args.date}.json"
    if not snap.exists():
        print(f"no snapshot for {args.date}")
        return 1
    _, jobs = load_snapshot(snap)
    pages = load_publish_config(root / "config" / "publish.yaml").get("pages_url", "")
    text = build_digest(args.date, jobs, pages, hot=args.hot)
    print(text)
    report_file = root / "reports" / f"{args.date}.html"
    if report_file.exists():
        print(f"[View Today's Openings (HTML)](<{report_file.resolve()}>)")
    token, chat = telegram_credentials()
    if not (token and chat):
        print("\nTELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; digest printed only.")
        return 3
    if args.dry_run:
        return 0
    send_telegram(text, token, chat)
    print("\nsent to Telegram")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobradar", description="Daily job scanner ranked against your profile.")
    sub = p.add_subparsers(dest="cmd", required=True)

    local = sub.add_parser("serve", help="local job board with automatic feedback saving")
    local.add_argument("--port", type=int, default=8766)
    local.add_argument("--date", help="saved snapshot date (default: latest available)")
    local.set_defaults(func=cmd_serve)

    r = sub.add_parser("run", help="fetch, score, and render today's report")
    r.add_argument("--date", default=_today())
    r.add_argument("--offline", action="store_true", help="use recorded fixtures instead of the network")
    r.add_argument("--fixtures", help="fixtures root for --offline (default tests/fixtures)")
    r.add_argument("--company", action="append", help="limit to these company keys (repeatable)")
    r.add_argument("--review", help="path to a reviews JSON to merge (copied to data/reviews/<date>.json)")
    r.add_argument("--skip-fetch", action="store_true", help="re-score and re-render the stored snapshot")
    r.set_defaults(func=cmd_run)

    rr = sub.add_parser("render", help="re-render a stored snapshot (optionally merging a review)")
    rr.add_argument("--date", default=_today())
    rr.add_argument("--review")
    rr.set_defaults(func=cmd_render)

    sub.add_parser("status", help="summarize the last run").set_defaults(func=cmd_status)
    sub.add_parser("eval", help="measure scoring against recorded verdicts").set_defaults(func=cmd_eval)

    f = sub.add_parser("feedback", help="record verdicts")
    fs = f.add_subparsers(dest="feedback_cmd", required=True)
    fa = fs.add_parser("add")
    fa.add_argument("--job", required=True)
    fa.add_argument("--verdict", required=True, choices=["good", "bad", "applied", "ignore"])
    fa.add_argument("--note")
    fst = fs.add_parser("stage", help="record an application stage")
    fst.add_argument("--job", required=True)
    fst.add_argument("--stage", required=True, choices=["applied", "oa", "phone", "onsite", "offer", "rejected", "withdrawn"])
    fst.add_argument("--note")
    fi = fs.add_parser("import", help="import lines like 'bad google:123 note', 'stage google:123 phone', 'followup google:123 note', or JSON objects; '-' for stdin")
    fi.add_argument("file")
    f.set_defaults(func=cmd_feedback)

    sub.add_parser("open", help="open the latest report").set_defaults(func=cmd_open)

    hb = sub.add_parser("h1b", help="H-1B sponsorship tier for a company from the local DOL index")
    hb.add_argument("name", nargs="*", help="company name as written on the card")
    hb.add_argument("--install", action="store_true", help="download the DOL index into data/careerops/h1b")
    hb.add_argument("--force", action="store_true", help="replace an installed index")
    hb.add_argument("--refresh", action="store_true", help="bypass the lookup cache")
    hb.set_defaults(func=cmd_h1b)

    cn = sub.add_parser("connections", help="first-degree LinkedIn connections at tracked companies (needs data/careerops/Connections.csv)")
    cn.add_argument("name", nargs="*", help="one company name; default: every company in companies.yaml")
    cn.add_argument("--weak", action="store_true", help="include weak name matches")
    cn.set_defaults(func=cmd_connections)

    fu = sub.add_parser("followups", help="follow-up cadence for every application: overdue, waiting, cold")
    fu.add_argument("--due", action="store_true", help="only what is overdue")
    fu.add_argument("--date", default=_today())
    fu.set_defaults(func=cmd_followups)

    dc = sub.add_parser("discover", help="find the ATS board for company names and print companies.yaml entries")
    dc.add_argument("name", nargs="+", help="company names, e.g. Ramp Vercel Notion")
    dc.set_defaults(func=cmd_discover)

    lv = sub.add_parser("liveness", help="check whether applied postings (or given URLs) are still open, via public ATS APIs")
    lv.add_argument("url", nargs="*")
    lv.set_defaults(func=cmd_liveness)

    rp = sub.add_parser("reposts", help="companies re-listing the same title under new URLs")
    rp.add_argument("--window", type=int, default=90, help="days (default 90)")
    rp.add_argument("--all", action="store_true", help="include clusters whose earlier listings are all still open (siblings, not reposts)")
    rp.set_defaults(func=cmd_reposts)

    nt = sub.add_parser("notify", help="send the daily digest to Telegram")
    nt.add_argument("--date", default=_today())
    nt.add_argument("--hot", type=int, default=85, help="score that triggers the 🔥 line")
    nt.add_argument("--dry-run", action="store_true")
    nt.set_defaults(func=cmd_notify)

    pb = sub.add_parser("publish", help="encrypt the latest report and push it to the reports repo")
    pb.add_argument("--push", action="store_true")
    pb.add_argument("--date", default=_today())
    pb.add_argument("--hub", help="a built hub to publish under /hub/ (default: study-plan/site/hub when it exists)")
    pb.add_argument("--no-hub", dest="no_hub", action="store_true", help="publish the report only")
    pb.set_defaults(func=cmd_publish)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
