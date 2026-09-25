import json
import subprocess
from pathlib import Path

import pytest

from jobradar import careerops

ROOT = Path(__file__).resolve().parents[1]


def test_unavailable_reason_without_node(monkeypatch, tmp_path):
    monkeypatch.setattr(careerops.shutil, "which", lambda name: None)
    assert "node is not installed" in careerops.unavailable_reason(tmp_path)
    assert not careerops.available(tmp_path)


def test_unavailable_reason_without_submodule(monkeypatch, tmp_path):
    monkeypatch.setattr(careerops.shutil, "which", lambda name: "/usr/bin/node")
    assert "git submodule update" in careerops.unavailable_reason(tmp_path)
    (tmp_path / "vendor" / "career-ops").mkdir(parents=True)
    (tmp_path / "vendor" / "career-ops" / "package.json").write_text("{}")
    assert "npm ci" in careerops.unavailable_reason(tmp_path)
    (tmp_path / "node_modules" / "js-yaml").mkdir(parents=True)
    assert careerops.unavailable_reason(tmp_path) == ""


def test_run_sets_data_root_and_parses_json(monkeypatch, tmp_path):
    (tmp_path / "vendor" / "career-ops").mkdir(parents=True)
    (tmp_path / "vendor" / "career-ops" / "tool.mjs").write_text("")
    calls = {}

    def fake_run(argv, **kw):
        calls["argv"], calls["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, stdout='Checking...\n{"ok": true, "n": 2}\n', stderr="")

    monkeypatch.setattr(careerops.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(careerops.subprocess, "run", fake_run)
    out = careerops.run_json(tmp_path, "tool.mjs", ["--json", "Acme"], env={"X": "1"})
    assert out == {"ok": True, "n": 2}
    assert calls["argv"][1:] == [str(tmp_path / "vendor" / "career-ops" / "tool.mjs"), "--json", "Acme"]
    assert calls["kw"]["env"]["CAREER_OPS_ROOT"] == str((tmp_path / "data" / "careerops").resolve())
    assert calls["kw"]["env"]["X"] == "1"
    assert (tmp_path / "data" / "careerops").is_dir()


def test_run_raises_with_stderr_tail(monkeypatch, tmp_path):
    (tmp_path / "vendor" / "career-ops").mkdir(parents=True)
    (tmp_path / "vendor" / "career-ops" / "tool.mjs").write_text("")
    monkeypatch.setattr(careerops.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(careerops.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom\nno index\n"))
    with pytest.raises(careerops.CareerOpsError, match="exited 1: boom | no index"):
        careerops.run(tmp_path, "tool.mjs")
    with pytest.raises(careerops.CareerOpsError, match="missing script"):
        careerops.run(tmp_path, "nope.mjs")


@pytest.mark.node
def test_vendored_self_test_runs():
    if not careerops.available(ROOT):
        pytest.skip(careerops.unavailable_reason(ROOT))
    proc = careerops.run(ROOT, "jd-skill-gap.mjs", ["--self-test"])
    assert "0 failed" in proc.stdout
