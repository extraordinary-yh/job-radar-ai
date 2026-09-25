import json
from pathlib import Path

from jobradar.cli import main

REPO = Path(__file__).resolve().parents[1]


def test_cli_run_offline_and_status(tmp_path, monkeypatch, capsys):
    import shutil
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "config").mkdir(); (tmp_path / "profile").mkdir()
    shutil.copy(REPO / "tests" / "fixtures" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")
    (tmp_path / "config" / "companies.yaml").write_text(
        'companies:\n  - {name: Google, key: google, adapter: google, queries: ["software engineer"], max_pages: 1}\n')
    monkeypatch.setenv("JOBRADAR_ROOT", str(tmp_path))
    assert main(["run", "--offline", "--fixtures", str(REPO / "tests" / "fixtures"), "--date", "2026-09-01"]) == 0
    out = capsys.readouterr().out
    assert "google: 3 jobs" in out and "Report:" in out and "Candidates:" in out
    assert main(["status"]) == 0
    assert "2026-09-01" in capsys.readouterr().out
    assert main(["feedback", "add", "--job", "google:1", "--verdict", "ignore", "--note", "test"]) == 0
    assert (tmp_path / "data" / "feedback.jsonl").exists()
    assert main(["eval"]) == 0
    assert "precision@10" in capsys.readouterr().out
    assert main(["feedback", "stage", "--job", "google:1", "--stage", "phone"]) == 0
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert main(["notify", "--date", "2026-09-01"]) == 3
    assert "job-radar 2026-09-01" in capsys.readouterr().out


def test_status_lists_pending_tailors(tmp_path, monkeypatch, capsys):
    import shutil
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "config").mkdir(); (tmp_path / "profile").mkdir()
    shutil.copy(REPO / "tests" / "fixtures" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")
    (tmp_path / "config" / "companies.yaml").write_text(
        'companies:\n  - {name: Google, key: google, adapter: google, queries: ["software engineer"], max_pages: 1}\n')
    monkeypatch.setenv("JOBRADAR_ROOT", str(tmp_path))
    assert main(["run", "--offline", "--fixtures", str(REPO / "tests" / "fixtures"), "--date", "2026-09-01"]) == 0
    capsys.readouterr()
    (tmp_path / "data" / "feedback.jsonl").write_text('{"ts": "2026-09-02T10:00:00", "job_id": "google:1", "kind": "tailor"}\n')
    assert main(["status"]) == 0
    assert "tailor requests pending: google:1" in capsys.readouterr().out
