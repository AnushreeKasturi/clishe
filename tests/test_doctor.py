"""Tests for doctor.py - `clishe doctor`. Nothing is changed by doctor;
the AI checks are faked so no server is contacted."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import doctor  # noqa: E402


def test_python_and_bash():
    assert doctor.python().status == "ok"
    assert doctor.bash("3.2.57(1)-release") == doctor.Check("ok", "bash 3.2.57")


def test_on_path():
    assert doctor.on_path("/home/sam/.local/bin/clishe").status == "ok"
    note = doctor.on_path("")
    assert note.status == "note" and "PATH" in note.fix


@pytest.mark.parametrize("shell,rc", [("/bin/bash", ".bashrc"), ("/usr/bin/zsh", ".zshrc")])
def test_shortcut(tmp_path, shell, rc):
    missing = doctor.shortcut(shell, str(tmp_path))
    assert missing.status == "note" and f"~/{rc}" in missing.fix
    assert f"--init {os.path.basename(shell)}" in missing.fix
    (tmp_path / rc).write_text('eval "$(clishe --init bash)"\n')
    assert doctor.shortcut(shell, str(tmp_path)).status == "ok"


def test_shortcut_other_shells():
    assert "not available for fish" in doctor.shortcut("/usr/bin/fish", "/tmp").title


def test_config_file(tmp_path):
    path = tmp_path / "config.json"
    assert doctor.config_file(path)[0].status == "ok"            # none yet
    path.write_text('{"trash": "ask"}')
    assert [c.status for c in doctor.config_file(path)] == ["ok"]
    path.write_text('{"learnmode": "always"}')
    checks = doctor.config_file(path)
    assert checks[1].status == "note" and "learnmode" in checks[1].title
    path.write_text("{oops")
    fail = doctor.config_file(path)[0]
    assert fail.status == "fail" and "line 1" in fail.detail and str(path) in fail.fix
    path.write_text("[]")
    assert doctor.config_file(path)[0].status == "fail"


def test_data_folder(tmp_path):
    assert doctor.data_folder(tmp_path).status == "ok"


def test_data_folder_not_created_yet_is_fine(tmp_path):
    """Clishe makes this folder when it first has something to save, so a
    fresh install must not be told its data folder is broken."""
    missing = tmp_path / "clishe"
    check = doctor.data_folder(missing)
    assert check.status == "note"
    assert "create" in check.fix


def test_data_folder_that_cannot_be_created_is_a_problem(tmp_path):
    import os
    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o500)
    try:
        assert doctor.data_folder(locked / "clishe").status == "fail"
    finally:
        os.chmod(locked, 0o700)


def test_data_folder_that_exists_but_is_read_only(tmp_path):
    import os
    read_only = tmp_path / "clishe"
    read_only.mkdir()
    os.chmod(read_only, 0o500)
    try:
        assert doctor.data_folder(read_only).status == "fail"
    finally:
        os.chmod(read_only, 0o700)


@pytest.fixture
def no_ai(monkeypatch):
    import setup_check
    result = {"ollama_running": False, "ollama_models": [], "configured_model": "llama3.2",
              "other_servers": []}
    monkeypatch.setattr(setup_check, "check", lambda: result)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return result


def test_ai_none_is_fine(no_ai):
    checks = doctor.ai({})
    assert [c.status for c in checks] == ["note", "ok"]
    assert "clishe setup" in checks[0].fix


def test_ai_model_not_downloaded(no_ai):
    no_ai.update(ollama_running=True, ollama_models=["qwen2.5:3b"])
    assert "ollama pull llama3.2" in doctor.ai({})[0].fix


def test_ai_remote_host_is_a_problem(no_ai):
    checks = doctor.ai({"ollama": {"host": "http://8.8.8.8:11434"}})
    assert any(c.status == "fail" and "allow_remote_ai" in c.fix for c in checks)
    checks = doctor.ai({"ollama": {"host": "http://8.8.8.8:11434"}, "allow_remote_ai": True})
    assert not any(c.status == "fail" for c in checks)


def test_cloud_ai(no_ai, monkeypatch):
    checks = doctor.ai({"anthropic": {"enabled": True}})
    assert any(c.status == "fail" and "API key" in c.title for c in checks)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    checks = doctor.ai({"anthropic": {"enabled": True}})
    assert any(c.status == "note" and "Cloud AI" in c.title for c in checks)


def test_run_returns_every_check(no_ai):
    checks = doctor.run("5.2", "/usr/bin/clishe", "/bin/bash")
    titles = " | ".join(c.title for c in checks)
    for part in ("Python", "bash 5.2", "PATH", "Ctrl+G", "System", "Data folder",
                 "tldr-pages", "man", "Trash", "Local"):
        assert part in titles
    assert all(c.status in ("ok", "note", "fail") for c in checks)
