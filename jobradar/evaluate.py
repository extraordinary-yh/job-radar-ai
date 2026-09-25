"""Measure the current scoring against the user's verdicts across stored snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Preferences
from .models import Job
from .score import apply_scores
from .store import load_snapshot

POSITIVE = {"good", "applied"}
NEGATIVE = {"bad"}


@dataclass
class EvalReport:
    n_jobs: int
    n_positive: int
    n_negative: int
    precision_at_10: float
    top10: list[str] = field(default_factory=list)
    regressions_bad_high: list[str] = field(default_factory=list)
    regressions_good_low: list[str] = field(default_factory=list)


def _label(j: Job) -> str:
    return f"{j.title} @ {j.company} ({j.id}) score={j.score}" + (f" excluded: {j.exclude_reason}" if j.excluded else "")


def evaluate(snapshot_paths: list[Path], verdicts: dict[str, dict[str, Any]], prefs: Preferences, today: str,
             high: int = 60, low: int = 40) -> EvalReport:
    latest: dict[str, Job] = {}
    for p in sorted(snapshot_paths):
        _, jobs = load_snapshot(p)
        for j in jobs:
            if j.id in verdicts:
                latest[j.id] = j
    jobs = list(latest.values())
    apply_scores(jobs, prefs, today)
    positives = {j.id for j in jobs if verdicts[j.id]["verdict"] in POSITIVE}
    negatives = {j.id for j in jobs if verdicts[j.id]["verdict"] in NEGATIVE}
    ranked = sorted((j for j in jobs if not j.excluded), key=lambda j: -j.score)
    top = ranked[:10]
    precision = (sum(1 for j in top if j.id in positives) / len(top)) if top else 0.0
    return EvalReport(
        n_jobs=len(jobs), n_positive=len(positives), n_negative=len(negatives), precision_at_10=round(precision, 3),
        top10=[_label(j) for j in top],
        regressions_bad_high=[_label(j) for j in jobs if j.id in negatives and not j.excluded and j.score >= high],
        regressions_good_low=[_label(j) for j in jobs if j.id in positives and (j.excluded or j.score < low)],
    )


def format_report(r: EvalReport) -> str:
    lines = [f"jobs with verdicts: {r.n_jobs} (positive {r.n_positive}, negative {r.n_negative})",
             f"precision@10: {r.precision_at_10}", "top 10 by current score:"]
    lines += [f"  {s}" for s in r.top10] or ["  (none)"]
    lines.append(f"regressions — marked bad but scoring high ({len(r.regressions_bad_high)}):")
    lines += [f"  {s}" for s in r.regressions_bad_high] or ["  none"]
    lines.append(f"regressions — marked good/applied but scoring low or excluded ({len(r.regressions_good_low)}):")
    lines += [f"  {s}" for s in r.regressions_good_low] or ["  none"]
    return "\n".join(lines)
