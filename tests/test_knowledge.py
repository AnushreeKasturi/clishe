"""Tests for knowledge.py - the offline command dictionary and error-pattern
matcher. No network, no providers, no AI - these should be fast and free."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge import lookup_command, format_explanation, diagnose_error


# ---------- lookup_command ----------

def test_lookup_known_command():
    entry = lookup_command("ls -la")
    assert entry is not None
    assert "summary" in entry


def test_lookup_uses_first_word_only():
    entry = lookup_command("chmod 755 script.sh")
    assert entry is not None
    assert "permission" in entry["summary"].lower()


def test_lookup_unknown_command_returns_none():
    assert lookup_command("some-made-up-tool --flag") is None


def test_lookup_empty_string_returns_none():
    assert lookup_command("") is None
    assert lookup_command("   ") is None


def test_lookup_handles_unbalanced_quotes_without_crashing():
    # shlex.split raises ValueError on unbalanced quotes - make sure we
    # degrade gracefully instead of propagating the exception.
    result = lookup_command('echo "unterminated')
    assert result is None or isinstance(result, dict)


# ---------- format_explanation ----------

def test_format_explanation_includes_summary():
    entry = {"summary": "Does a thing.", "flags": {}, "example": None}
    text = format_explanation(entry)
    assert "Does a thing." in text


def test_format_explanation_includes_danger_warning():
    entry = {"summary": "Deletes stuff.", "danger": "Be careful!"}
    text = format_explanation(entry)
    assert "Be careful!" in text
    assert "⚠" in text


def test_format_explanation_includes_flags():
    entry = {"summary": "Lists things.", "flags": {"-l": "long format"}}
    text = format_explanation(entry)
    assert "-l" in text
    assert "long format" in text


# ---------- diagnose_error ----------

def test_diagnose_permission_denied():
    hint = diagnose_error("bash: ./script.sh: Permission denied")
    assert hint is not None
    assert "permission" in hint.lower()


def test_diagnose_no_such_file():
    hint = diagnose_error("cat: missing.txt: No such file or directory")
    assert hint is not None


def test_diagnose_is_case_insensitive():
    hint_lower = diagnose_error("permission denied")
    hint_upper = diagnose_error("PERMISSION DENIED")
    assert hint_lower is not None
    assert hint_lower == hint_upper


def test_diagnose_unmatched_error_returns_none():
    assert diagnose_error("a completely novel error string xyz123") is None


def test_diagnose_empty_string_returns_none():
    assert diagnose_error("") is None
    assert diagnose_error(None) is None


# ---------- per-flag explanations ----------

from knowledge import explain_flags


def test_combined_short_flags_are_split():
    entry = lookup_command("tar -xzvf a.tgz")
    known, unknown = explain_flags("tar -xzvf a.tgz", entry)
    assert [f for f, _ in known] == ["-x", "-z", "-v", "-f"]
    assert unknown == []


def test_old_style_tar_flags_without_dash():
    entry = lookup_command("tar xzvf a.tgz")
    known, _ = explain_flags("tar xzvf a.tgz", entry)
    assert [f for f, _ in known] == ["-x", "-z", "-v", "-f"]


def test_unknown_flags_are_reported():
    entry = lookup_command("ls -laZ")
    known, unknown = explain_flags("ls -laZ", entry)
    assert [f for f, _ in known] == ["-l", "-a"]
    assert unknown == ["-Z"]


def test_subcommands_are_explained():
    entry = lookup_command("git status")
    known, _ = explain_flags("git status", entry)
    assert known and known[0][0] == "status"


def test_sudo_is_skipped():
    assert lookup_command("sudo apt install htop") is lookup_command("apt")


def test_format_explanation_mentions_used_flags():
    entry = lookup_command("grep -rn foo .")
    text = format_explanation(entry, "grep -rn foo .")
    assert "In 'grep -rn foo .'" in text
    assert "-r" in text and "-n" in text
    assert "Common flags" not in text


def test_format_explanation_without_flags_lists_common_ones():
    entry = lookup_command("chmod 755 x")
    text = format_explanation(entry, "chmod 755 x")
    assert "Common flags" in text


# ---------- programs that aren't installed ----------

import pytest  # noqa: E402
from knowledge import missing_program_hint, output_guide  # noqa: E402


@pytest.mark.parametrize("family,expected", [
    (["pop", "ubuntu", "debian"], "sudo apt install dnsutils"),
    (["fedora"], "sudo dnf install bind-utils"),
    (["endeavouros", "arch"], "sudo pacman -S bind"),
    (["opensuse-tumbleweed", "opensuse"], "sudo zypper install bind-utils"),
    (["alpine"], "sudo apk add dig"),
])
def test_install_hint_uses_the_distros_package_manager(family, expected):
    assert expected in missing_program_hint("dig", family)


def test_install_hint_same_name_package():
    assert "sudo apt install htop" in missing_program_hint("htop", ["ubuntu"])


def test_install_hint_unknown_distro_stays_generic():
    hint = missing_program_hint("htop", ["nixos"])
    assert "isn't installed" in hint and "sudo" not in hint


def test_python_points_to_python3():
    assert "python3" in missing_program_hint("python", ["ubuntu"])


def test_command_not_found_names_the_program():
    hint = diagnose_error("bash: line 3: htop: command not found")
    assert "'htop' isn't installed" in hint


@pytest.mark.parametrize("error,expected", [
    ("git@github.com: Permission denied (publickey).", "SSH key"),
    ("error: externally-managed-environment", "virtual environment"),
    ("E: Could not open lock file /var/lib/dpkg/lock-frontend", "sudo"),
    ("E: Unable to locate package htopp", "apt update"),
    ("fatal: not a git repository (or any of the parent directories): .git", "git init"),
    ("curl: (6) Could not resolve host: example.invalid", "internet"),
    ("cp: failed: No space left on device", "disk is full"),
    ("touch: cannot touch 'a.txt': Read-only file system", "doesn't allow writes"),
    ("Error: listen tcp :8080: bind: Address already in use", "already using"),
    ("bash: /usr/bin/rm: Argument list too long", "too many files"),
    ("Segmentation fault (core dumped)", "crashed"),
    ("! [rejected] main -> main (non-fast-forward)", "git pull"),
    ("fatal: refusing to merge unrelated histories", "--allow-unrelated-histories"),
    # npm's text also contains "permission denied", so the npm hint must win
    ("npm ERR! Error: EACCES: permission denied, mkdir '/usr/lib/node_modules'", "npm config set prefix"),
])
def test_common_beginner_errors_are_explained(error, expected):
    assert expected in diagnose_error(error)


# ---------- output guides ----------

@pytest.mark.parametrize("command,label", [
    ("ls -la", "ls -l"),
    ("ls", "ls"),
    ("sudo df -h", "df"),
    ("du -sh * | sort -h", "du"),
    ("git status", "git status"),
    ("FOO=1 uptime", "uptime"),
])
def test_output_guide_matches(command, label):
    assert output_guide(command)[0] == label


@pytest.mark.parametrize("command", ["git push", "cat notes.txt", "", "echo 'unterminated"])
def test_output_guide_none(command):
    assert output_guide(command) is None
