"""Keep the saving board available on macOS: uv run python scripts/install_local_board.py."""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

import yaml

LABEL = "com.jobradar.board"


def main():
    if sys.platform != "darwin":
        raise SystemExit("This installer uses macOS LaunchAgents. Run jobradar serve on other systems.")
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required.")
    config = yaml.safe_load((root / "config/publish.yaml").read_text())
    from urllib.parse import urlsplit
    port = urlsplit(config["local_board_url"]).port or 8766
    logs = root / "build/local-board"
    logs.mkdir(parents=True, exist_ok=True)
    target = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "--no-sync", "jobradar", "serve", "--port", str(port)],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(logs / "stdout.log"),
        "StandardErrorPath": str(logs / "stderr.log"),
        "EnvironmentVariables": {"PATH": f"{Path(uv).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
    }
    target.write_bytes(plistlib.dumps(plist))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    print(f"Saving board starts at login: {config['local_board_url']}")
    print(f"Remove with: launchctl bootout {domain}/{LABEL}; then delete {target}")


if __name__ == "__main__":
    main()
