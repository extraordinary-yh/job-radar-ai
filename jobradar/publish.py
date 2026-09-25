"""Publish the report behind a passphrase: AES-256-GCM in Python, decrypted in the browser with WebCrypto."""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from jinja2 import Environment, FileSystemLoader

ITERATIONS = 600_000
TEMPLATES = Path(__file__).parent / "templates"
GIT_IDENTITY = ["-c", "user.name=job-radar", "-c", "user.email=job-radar@users.noreply.github.com"]


def derive_key(passphrase: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def encrypt_html(html: str, passphrase: str, salt: bytes, iterations: int = ITERATIONS) -> dict[str, Any]:
    nonce = os.urandom(12)
    ct = AESGCM(derive_key(passphrase, salt, iterations)).encrypt(nonce, html.encode("utf-8"), None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iterations": iterations, "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct)}


def decrypt_html(payload: dict[str, Any], passphrase: str) -> str:
    key = derive_key(passphrase, base64.b64decode(payload["salt"]), int(payload["iterations"]))
    return AESGCM(key).decrypt(base64.b64decode(payload["nonce"]), base64.b64decode(payload["ct"]), None).decode("utf-8")


def load_publish_config(path: Path) -> dict[str, Any]:
    path = Path(path)
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def get_or_create_salt(config_path: Path) -> bytes:
    cfg = load_publish_config(config_path)
    if cfg.get("salt_b64"):
        return base64.b64decode(cfg["salt_b64"])
    salt = os.urandom(16)
    cfg["salt_b64"] = _b64(salt)
    Path(config_path).write_text(yaml.safe_dump(cfg, sort_keys=False))
    return salt


def load_dotenv(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), " ".join(shlex.split(value.strip())) if value.strip() else "")


def build_shell(payload: dict[str, Any], title: str, *, heading: str = "job-radar",
                prompt: str = "Enter the passphrase to open the latest report.") -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=False)
    return env.get_template("shell.html.j2").render(title=title, heading=heading, prompt=prompt,
                                                    payload_json=json.dumps(payload).replace("</", "<\\/"))


def build_site(root: Path, date: str, passphrase: str, site: Path) -> Path:
    root, site = Path(root), Path(site)
    html = (root / "reports" / "index.html").read_text()
    salt = get_or_create_salt(root / "config" / "publish.yaml")
    shell = build_shell(encrypt_html(html, passphrase, salt), f"job-radar · {date}")
    (site / "archive").mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(shell)
    (site / "archive" / f"{date}.html").write_text(shell)
    (site / ".nojekyll").write_text("")
    return site


EVENT_REPORTS = ("sf-events", "reports")   # the event scan's daily reports, published next to the job report's archive
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def build_events(root: Path, passphrase: str, site: Path) -> int:
    """Encrypt every dated event report (`sf-events/reports/<date>.html`) into `<site>/events/<date>.html`, the
    same shell, passphrase and salt as the job report's `archive/` copies, so the key the shell remembers opens
    them too and the hub's day page can show one in its Events tab. Reports gone from the folder are pruned.
    Returns the number of pages written."""
    root, site = Path(root), Path(site)
    src = root.joinpath(*EVENT_REPORTS)
    out = site / "events"
    written: set[Path] = set()
    if src.is_dir():
        salt = get_or_create_salt(root / "config" / "publish.yaml")
        out.mkdir(parents=True, exist_ok=True)
        for page in sorted(src.glob("*.html")):
            if not _DATED.match(page.stem):
                continue
            target = out / page.name
            target.write_text(build_shell(encrypt_html(page.read_text(), passphrase, salt), f"sf-events · {page.stem}",
                                          heading="sf-events", prompt="Enter the passphrase to open this event report."))
            written.add(target.resolve())
    if out.exists():
        for stale in sorted(out.glob("*.html")):
            if stale.resolve() not in written:
                stale.unlink()
    return len(written)


HUB_PLAIN = {"index.html"}          # the hub's redirect page carries only week ids: it stays plain so it can redirect


def build_hub(root: Path, hub_dir: Path, passphrase: str, site: Path) -> int:
    """Encrypt every page of the built hub (`studyplan hub build` -> study-plan/site/hub/) into `<site>/hub/`.

    One shell per page, same passphrase and salt as the report, so the key the shell remembers on the device
    opens every hub page and the relative links between them keep working. Pages that no longer exist in the
    build are removed from the site; `index.json` is never published. Returns the number of pages written.
    """
    root, hub_dir, site = Path(root), Path(hub_dir), Path(site)
    salt = get_or_create_salt(root / "config" / "publish.yaml")
    out = site / "hub"
    written: set[Path] = set()
    for page in sorted(hub_dir.rglob("*.html")):
        rel = page.relative_to(hub_dir)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if str(rel) in HUB_PLAIN:
            target.write_text(page.read_text())
        else:
            title = rel.with_suffix("").as_posix().replace("/", " · ")
            target.write_text(build_shell(encrypt_html(page.read_text(), passphrase, salt), f"study hub · {title}",
                                          heading="study hub", prompt="Enter the passphrase to open this page."))
        written.add(target.resolve())
    if out.exists():
        for stale in sorted(out.rglob("*"), reverse=True):
            if stale.is_file() and stale.resolve() not in written:
                stale.unlink()
            elif stale.is_dir() and not any(stale.iterdir()):
                stale.rmdir()
    return len(written)


def _git(site: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *GIT_IDENTITY, "-C", str(site), *args], check=check, capture_output=True, text=True)


def ensure_site_repo(site: Path, repo_url: str, branch: str = "main") -> None:
    site = Path(site)
    if (site / ".git").exists():
        return
    if site.exists() and any(site.iterdir()):
        raise RuntimeError(f"{site} exists and is not a git clone; remove it or point elsewhere")
    site.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(["git", "clone", "-q", "--branch", branch, repo_url, str(site)], capture_output=True, text=True)
    if clone.returncode != 0:                       # empty remote: start a fresh branch
        site.mkdir(parents=True, exist_ok=True)
        _git(site, "init", "-q", "-b", branch)
        _git(site, "remote", "add", "origin", repo_url)


def commit_and_push(site: Path, message: str, branch: str = "main") -> bool:
    site = Path(site)
    _git(site, "add", "-A")
    if _git(site, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    _git(site, "commit", "-q", "-m", message)
    _git(site, "push", "-q", "-u", "origin", branch)
    return True
