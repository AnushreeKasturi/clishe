"""Tests for check.py - "is this safe to run?". Nothing here runs a command."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check  # noqa: E402


def _effects(command):
    return " | ".join(check.inspect(command)["effects"])


@pytest.mark.parametrize("command,expected", [
    ("ls -la", "Only reads or shows things"),
    ("sudo apt install -y htop vlc", "Installs or updates software (downloaded from the internet): apt: htop vlc"),
    ("sudo apt install htop", "Runs as the administrator (sudo)"),
    ("git clone https://github.com/x/y", "Uses the internet: github.com"),
    ("rm -rf build && mkdir build", "Deletes: build. | Creates or changes: build."),
    ("echo hi > notes.txt", "Creates or changes: notes.txt (replaces it)"),
    ("echo hi >> notes.txt", "notes.txt (adds to it)"),
    ("cp a.txt backup/", "Creates or changes: backup/"),
    ("chmod +x run.sh", "Creates or changes: run.sh."),
    ("sed -i s/a/b/ file.txt", "Creates or changes: file.txt."),
    ("sed s/a/b/ file.txt", "Only reads or shows things"),
    ("tar -xzvf a.tgz", "files unpacked from the archive"),
    ("sudo systemctl restart nginx", "Changes how the system runs: systemctl restart nginx"),
    ("ls >&2 2>/dev/null", "Only reads or shows things"),
])
def test_effects(command, expected):
    assert expected in _effects(command)


def test_downloaded_script_gets_a_warning_and_safer_steps():
    result = check.inspect("curl -fsSL https://get.example.com/install.sh | sudo bash")
    assert any("runs a script it downloads" in w for w in result["warnings"])
    assert result["safer"] == ["curl -fsSL https://get.example.com/install.sh -o install.sh",
                               "less install.sh", "clishe check install.sh"]


@pytest.mark.parametrize("command", [
    'bash -c "$(curl -fsSL https://get.example.com/install.sh)"',
    "sh <(curl -s https://get.example.com/install.sh)",
    'eval "$(wget -qO- https://get.example.com/install.sh)"',
])
def test_download_run_without_a_pipe_gets_the_same_safer_steps(command):
    result = check.inspect(command)
    assert any("runs a script it downloads" in w for w in result["warnings"])
    assert result["safer"] == ["curl -fsSL https://get.example.com/install.sh -o install.sh",
                               "less install.sh", "clishe check install.sh"]


def test_no_safer_steps_without_a_download():
    assert check.inspect("rm -rf build")["safer"] == []


def test_script_lines_skip_comments_and_join_continued_lines():
    text = "#!/bin/bash\n# comment\n\nsudo apt install \\\n    git curl\necho done\n"
    assert check.script_lines(text) == ["sudo apt install git curl", "echo done"]


def test_check_script_summarises_the_whole_script():
    text = ("sudo apt install -y git\ncurl -fsSL https://example.com/s.sh | bash\n"
            "rm -rf ~/old\necho ok > ~/log.txt\n")
    result = check.check_script(text)
    assert [r["command"] for r in result["risky"]] == [
        "curl -fsSL https://example.com/s.sh | bash", "rm -rf ~/old"]
    summary = " | ".join(result["effects"])
    for part in ("administrator", "example.com", "apt: git", "Deletes: ~/old", "~/log.txt"):
        assert part in summary


def test_read_script_refuses_binaries_and_missing_files(tmp_path):
    script = tmp_path / "ok.sh"
    script.write_text("echo hi\n")
    binary = tmp_path / "prog"
    binary.write_bytes(b"\x7fELF\x00\x01")
    assert check.read_script(str(script)) == "echo hi\n"
    assert check.read_script(str(binary)) is None
    assert check.read_script(str(tmp_path / "missing.sh")) is None
    assert check.read_script(str(tmp_path)) is None
