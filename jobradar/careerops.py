"""Bridge to the vendored career-ops scripts (vendor/career-ops), run through node.

This is the only module that spawns node. Every feature built on it must degrade to
"off, with one warning" when node, the submodule checkout, or its js-yaml dependency is
missing, so the daily scan never depends on the sidecar.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

VENDOR = Path("vendor") / "career-ops"
DATA_DIR = Path("data") / "careerops"
RUNNERS = Path("scripts") / "careerops"


class CareerOpsError(RuntimeError):
    """A vendored script failed or the sidecar is not installed."""


def vendor_dir(root: Path) -> Path:
    return Path(root) / VENDOR


def data_root(root: Path) -> Path:
    d = Path(root) / DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def node_path() -> str | None:
    return shutil.which("node")


def unavailable_reason(root: Path) -> str:
    """Empty string when the sidecar can run; otherwise a one-line reason for the warning."""
    if node_path() is None:
        return "node is not installed (career-ops features skipped)"
    if not (vendor_dir(root) / "package.json").exists():
        return "vendor/career-ops is empty; run `git submodule update --init` (career-ops features skipped)"
    if not (Path(root) / "node_modules" / "js-yaml").exists():
        return "node_modules/js-yaml is missing; run `npm ci --ignore-scripts` (career-ops features skipped)"
    return ""


def available(root: Path) -> bool:
    return unavailable_reason(root) == ""


def _env(root: Path, extra: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ)
    env["CAREER_OPS_ROOT"] = str(data_root(root).resolve())
    env["NODE_NO_WARNINGS"] = "1"
    if extra:
        env.update(extra)
    return env


def run(root: Path, script: str, args: list[str] | tuple[str, ...] = (), *, env: dict[str, str] | None = None,
        cwd: Path | None = None, timeout: float = 180, stdin: str | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    """Run `node <script> <args>`; `script` is relative to vendor/career-ops unless it starts with `scripts/`."""
    node = node_path()
    if node is None:
        raise CareerOpsError("node is not installed")
    path = Path(root) / script if script.startswith("scripts/") else vendor_dir(root) / script
    if not path.exists():
        raise CareerOpsError(f"missing script {path}")
    proc = subprocess.run([node, str(path), *map(str, args)], cwd=str(cwd or root), env=_env(root, env),
                          input=stdin, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise CareerOpsError(f"{script} exited {proc.returncode}: {' | '.join(tail)}")
    return proc


def run_json(root: Path, script: str, args: list[str] | tuple[str, ...] = (), **kw: Any) -> Any:
    proc = run(root, script, args, **kw)
    text = proc.stdout.strip()
    start = text.find("{") if text and text[0] not in "{[" else 0
    if start < 0:
        start = text.find("[")
    try:
        return json.loads(text[start:] if start > 0 else text)
    except json.JSONDecodeError as e:
        raise CareerOpsError(f"{script}: could not parse JSON output ({e}): {text[:200]!r}") from None
