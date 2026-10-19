"""Tests for ClisheBrain's knowledge-base, logging, and prediction logic.
Run with: pytest tests/
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A ClisheBrain instance backed by a throwaway temp HOME, so tests never
    touch the real ~/.clishe_kb.json etc."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # No man pages unless a test brings its own, so results don't depend on
    # what's installed on the machine running the tests.
    import manual
    monkeypatch.setattr(manual, "read_manual", lambda name: ("", ""))
    import importlib
    import clishe_brain
    importlib.reload(clishe_brain)  # re-evaluate KB_FILE/DATA_FILE against new HOME
    return clishe_brain.ClisheBrain()


def test_query_miss_returns_empty_string(brain):
    assert brain.query("nonexistent phrase") == ""


def test_learn_then_query_roundtrip(brain):
    assert brain.learn("list files", "ls -la") is True
    assert brain.query("list files") == "ls -la"


def test_query_is_case_and_whitespace_insensitive(brain):
    brain.learn("list files", "ls -la")
    assert brain.query("  List Files  ") == "ls -la"


def test_learn_rejects_empty_phrase_or_command(brain):
    assert brain.learn("", "ls -la") is False
    assert brain.learn("list files", "") is False


def test_learn_persists_to_disk(brain, tmp_path):
    import clishe_brain
    brain.learn("list files", "ls -la")
    assert clishe_brain.KB_FILE.exists()
    with open(clishe_brain.KB_FILE) as f:
        saved = json.load(f)
    assert saved["list files"] == "ls -la"


def test_corrupted_kb_file_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".clishe_kb.json").write_text("{not valid json")

    import importlib
    import clishe_brain
    importlib.reload(clishe_brain)
    brain = clishe_brain.ClisheBrain()
    assert brain.kb == {}  # falls back to empty instead of raising


def test_predict_needs_minimum_sequences(brain):
    # Only 2 sequences logged - below MIN_SEQUENCES_FOR_PREDICTION (3)
    brain.data["sequences"] = [["cd", "ls"], ["cd", "mkdir"]]
    assert brain.predict("cd") == ""


def test_predict_picks_most_frequent_follower(brain):
    brain.data["sequences"] = [
        ["cd", "ls", "mkdir"],
        ["cd", "ls", "ls"],
        ["cd", "ls", "mkdir"],
    ]
    # After "cd", "ls" always follows -> should predict "ls"
    assert brain.predict("cd") == "ls"
    # After "ls", "mkdir" appears twice vs "ls" once -> should predict "mkdir"
    assert brain.predict("ls") == "mkdir"


def test_predict_never_predicts_same_command(brain):
    brain.data["sequences"] = [
        ["ls", "ls"], ["ls", "ls"], ["ls", "ls"],
    ]
    # Only observed follower is itself, so there's nothing valid to predict
    assert brain.predict("ls") == ""


def test_log_flushes_current_into_sequences_at_threshold(brain):
    for i in range(10):
        brain.log(f"cmd{i}")
    assert brain.data["current"] == []
    assert len(brain.data["sequences"]) == 1
    assert len(brain.data["sequences"][0]) == 10


# ---------- explain() offline-dictionary integration ----------

def test_explain_uses_offline_dictionary_for_known_command(brain):
    result = brain.explain("chmod 755 script.sh")
    assert result["status"] == "ok"
    assert result["provider"].startswith("offline dictionary")
    assert "permission" in result["explanation"].lower()


def test_explain_falls_through_to_unavailable_for_unknown_command_with_no_providers(brain):
    result = brain.explain("some-made-up-tool --flag")
    assert result["status"] == "unavailable"


# ---------- diagnose() ----------

def test_diagnose_matches_known_error(brain):
    result = brain.diagnose("Permission denied")
    assert result["status"] == "ok"
    assert "hint" in result


def test_diagnose_unmatched_error(brain):
    result = brain.diagnose("a totally novel error nobody has documented")
    assert result["status"] == "unmatched"


# ---------- phrase normalization ----------

@pytest.mark.parametrize("raw,expected", [
    ("  Show Me Disk Usage??  ", "show me disk usage"),
    ("please show me disk usage", "show me disk usage"),
    ("hey, can you list files please", "list files"),
    ("what’s my ip", "what's my ip"),
    ("list   files.", "list files"),
])
def test_normalize_phrase(raw, expected):
    import clishe_brain
    assert clishe_brain.normalize_phrase(raw) == expected


def test_query_ignores_punctuation_and_filler(brain):
    brain.learn("deploy my site", "./deploy.sh")
    assert brain.query("Please deploy my site!") == "./deploy.sh"


def test_old_unnormalized_kb_keys_still_match(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    kb_dir = tmp_path / ".local" / "share" / "clishe"
    kb_dir.mkdir(parents=True)
    (kb_dir / "kb.json").write_text(json.dumps({"Deploy My Site?": "./deploy.sh"}))
    import importlib
    import clishe_brain
    importlib.reload(clishe_brain)
    assert clishe_brain.ClisheBrain().query("deploy my site") == "./deploy.sh"


# ---------- fuzzy suggestions ----------

def test_suggest_finds_near_miss_in_seed_kb(brain):
    assert brain.suggest("show disk usage") == ("show me disk usage", "df -h")


def test_suggest_prefers_users_own_phrases(brain):
    brain.learn("show me disk usage", "duf")
    assert brain.suggest("show disk usage") == ("show me disk usage", "duf")


def test_suggest_returns_none_for_unrelated_phrase(brain):
    assert brain.suggest("book a flight to paris") is None


@pytest.mark.parametrize("said,expected", [
    ("remove a directory", "delete a folder"),
    ("erase a directory", "delete a folder"),
    ("how much disk is left", "how much disk space is left"),
    ("how much ram is available", "how much memory is free"),
    ("what programs are running", "show running processes"),
    ("display my files", "list files"),
    ("find a file", "search for a file"),
])
def test_suggest_matches_on_meaning(brain, said, expected):
    match = brain.suggest(said)
    assert match is not None and match[0] == expected, match


@pytest.mark.parametrize("said", [
    "delete my photos",      # not "delete a file": half of it ("photos") would be ignored
    "make me a sandwich",    # not "make a new folder"
    "change my password",    # not "what did i change"
    "open youtube",          # not "open a file"
    "make a zip file of a folder",         # exactly half: not "make a new folder"
    "delete all files in my home folder",  # exactly half: not "delete a file"
])
def test_suggest_by_meaning_needs_more_than_half_of_what_was_said(brain, said):
    assert brain.suggest(said) is None


@pytest.mark.parametrize("said", [
    "my files",              # must not turn into "delete a file"
    "unzip a file",
    "files",
    "kill chrome",
    "where am i going",
])
def test_suggest_by_meaning_never_adds_an_action(brain, said):
    match = brain.suggest(said)
    assert match is None or not match[1].startswith(("rm", "kill", "pkill")), match


def test_meaning_tokens_drop_filler_and_map_synonyms():
    import clishe_brain
    assert clishe_brain.meaning_tokens("Please remove the directories") == {"delete", "folder"}
    assert clishe_brain.meaning_tokens("can you show me all of it") == frozenset()


def test_suggest_by_meaning_prefers_users_own_phrases(brain):
    brain.learn("delete a folder", "trash-put <folder>")
    assert brain.suggest("remove a directory") == ("delete a folder", "trash-put <folder>")


def test_suggest_returns_none_for_exact_match(brain):
    # Exact matches are query()'s job; suggest is only for near misses.
    assert brain.suggest("show me disk usage") is None


# ---------- forget / learned ----------

def test_forget_removes_taught_phrase(brain):
    brain.learn("deploy", "./deploy.sh")
    assert brain.forget("Deploy") is True
    assert brain.query("deploy") == ""


def test_forget_unknown_phrase(brain):
    assert brain.forget("never taught") is False


def test_teaching_a_seed_phrase_overrides_it(brain):
    brain.learn("list files", "ls -1")
    assert brain.query("list files") == "ls -1"
    brain.forget("list files")
    assert brain.query("list files") == "ls -la"  # seed value is back


def test_learned_lists_only_user_phrases(brain):
    brain.learn("b phrase", "cmd-b")
    brain.learn("a phrase", "cmd-a")
    assert brain.learned() == [("a phrase", "cmd-a"), ("b phrase", "cmd-b")]


# ---------- storage hygiene ----------

def test_saved_files_are_private(brain):
    import clishe_brain
    brain.learn("list files", "ls -la")
    brain.log("ls")
    assert (clishe_brain.KB_FILE.stat().st_mode & 0o777) == 0o600
    assert (clishe_brain.DATA_FILE.stat().st_mode & 0o777) == 0o600


def test_history_is_capped(brain):
    import clishe_brain
    brain.data["sequences"] = [["a", "b"]] * (clishe_brain.MAX_SEQUENCES + 50)
    brain.data["current"] = ["x"] * (clishe_brain.SEQUENCE_FLUSH_LENGTH - 1)
    brain.log("newest")  # fills "current", which flushes and trims
    assert len(brain.data["sequences"]) == clishe_brain.MAX_SEQUENCES
    assert brain.data["sequences"][-1][-1] == "newest"


# ---------- resolve() keeps the model's explanation ----------

def test_resolve_returns_command_and_explanation(brain, monkeypatch):
    import clishe_brain
    from providers.base import Resolution

    class Fake:
        name = "fake"

        def resolve_with_explanation(self, phrase):
            return Resolution("df -h", "Shows free disk space.")

    monkeypatch.setattr(clishe_brain, "build_provider_chain", lambda config: [Fake()])
    result = brain.resolve("disk space")
    assert result == {"status": "ok", "command": "df -h",
                      "explanation": "Shows free disk space.", "provider": "fake",
                      "manual": [], "unverified": []}


def test_resolve_falls_through_failing_provider(brain, monkeypatch):
    import clishe_brain
    from providers import ProviderError
    from providers.base import Resolution

    class Broken:
        name = "broken"

        def resolve_with_explanation(self, phrase):
            raise ProviderError("down")

    class Works:
        name = "works"

        def resolve_with_explanation(self, phrase):
            return Resolution("uptime")

    monkeypatch.setattr(clishe_brain, "build_provider_chain", lambda c: [Broken(), Works()])
    assert brain.resolve("how long up")["provider"] == "works"


def test_check_action(brain):
    assert brain.check("ls")["status"] == "safe"
    result = brain.check("rm -rf build")
    assert result["status"] == "danger" and result["reasons"]


def test_one_line_output_keeps_what_runs_visible():
    import clishe_brain
    assert clishe_brain._one_line("cd /tmp\nls") == "cd /tmp; ls"
    assert clishe_brain._encoded("a\nb") == "a\\nb"


# ---------- tips: helping people outgrow Clishe ----------

def test_tip_after_third_use(brain):
    phrase = "show me disk usage"
    assert brain.record_use("df -h", phrase) == []
    assert brain.record_use("df -h", phrase) == []
    tips = brain.record_use("df -h", phrase)
    assert len(tips) == 1 and "3 times" in tips[0] and "df -h" in tips[0]
    assert brain.record_use("df -h", phrase) == []


def test_tip_mentions_placeholders(brain):
    for _ in range(2):
        brain.record_use("cp a b", "copy a file")
    tip = brain.record_use("cp a b", "copy a file")[0]
    assert "cp <file> <destination>" in tip and "<...>" in tip


def test_cheer_once_when_user_types_the_command_themselves(brain):
    brain.record_use("df -h", "show me disk usage")
    assert "yourself" in brain.record_use("df -h")[0]
    assert brain.record_use("df -h") == []  # only once


def test_no_cheer_for_commands_never_asked_about(brain):
    assert brain.record_use("df -h") == []


# ---------- trash instead of rm ----------

@pytest.fixture
def trash_brain(brain, monkeypatch):
    import clishe_brain
    monkeypatch.setattr(clishe_brain, "_trash_tool",
                        lambda: (["gio", "trash"], "Open Trash in your file manager"))
    monkeypatch.setattr(clishe_brain, "load_config", lambda: {"trash": "ask"})
    return brain


@pytest.mark.parametrize("command,expected", [
    ("rm notes.txt", "gio trash notes.txt"),
    ("rm -rf build", "gio trash build"),
    ("rm -r 'my notes.txt' *.log", "gio trash 'my notes.txt' *.log"),
    ("rm -- -weird-name", "gio trash -- -weird-name"),
])
def test_trash_rewrites_plain_rm(trash_brain, command, expected):
    assert trash_brain.trash_command(command)["command"] == expected


@pytest.mark.parametrize("command", [
    "rm -rf",                      # no files
    "sudo rm -rf /var/log/x",      # needs root; leave it alone
    "rm a; ls",
    "rm $(cat list.txt)",
    "rm `cat list.txt`",
    "ls | xargs rm",
    "cp a b",
])
def test_trash_leaves_other_commands_alone(trash_brain, command):
    assert trash_brain.trash_command(command) is None


def test_trash_respects_never(trash_brain, monkeypatch):
    import clishe_brain
    monkeypatch.setattr(clishe_brain, "load_config", lambda: {"trash": "never"})
    assert trash_brain.trash_command("rm x") is None


def test_trash_needs_a_trash_tool(brain, monkeypatch):
    import clishe_brain
    monkeypatch.setattr(clishe_brain, "_trash_tool", lambda: None)
    monkeypatch.setattr(clishe_brain, "load_config", lambda: {})
    assert brain.trash_command("rm x") is None


# ---------- the Ctrl+G shell shortcut ----------

def test_line_known_phrase_becomes_command(brain):
    r = brain.resolve_line("show me disk usage", use_ai=False)
    assert r["mode"] == "command" and r["command"] == "df -h" and not r["reasons"]


def test_line_risky_match_carries_a_warning(brain):
    r = brain.resolve_line("remove a directory", use_ai=False)
    assert r["command"] == "rm -r <folder>" and r["reasons"] and "delete a folder" in r["note"]


def test_line_real_command_is_explained(brain):
    r = brain.resolve_line("tar -xzvf a.tgz", use_ai=False)
    assert r["mode"] == "explain" and "-x" in r["explanation"]


def test_line_unknown_or_empty(brain):
    assert brain.resolve_line("book a flight to paris", use_ai=False)["mode"] == "none"
    assert brain.resolve_line("   ", use_ai=False)["mode"] == "none"


# ---------- missing programs, output guides, speed ----------

def test_missing_popular_program_gets_install_hint(brain, monkeypatch):
    import clishe_brain
    monkeypatch.setattr(clishe_brain.shutil, "which", lambda name: None)
    assert "isn't installed" in brain.missing_program("htop")
    assert "isn't installed" in brain.missing_program("sudo nmap -sn 10.0.0.0/24")
    assert "python3" in brain.missing_program("python hello.py")


def test_missing_program_ignores_english_and_installed(brain, monkeypatch):
    import clishe_brain
    monkeypatch.setattr(clishe_brain.shutil, "which", lambda name: None)
    assert brain.missing_program("go back") == ""
    assert brain.missing_program("frobnicate") == ""   # not a known program
    monkeypatch.setattr(clishe_brain.shutil, "which", lambda name: "/usr/bin/" + name)
    assert brain.missing_program("htop") == ""


def test_explain_output_guide_and_fallback(brain):
    assert "available" in brain.explain_output("free -h")["explanation"]
    fallback = brain.explain_output("cat notes.txt")
    assert fallback["status"] == "ok" and "don't have a guide" in fallback["explanation"]
    assert brain.explain_output("")["status"] == "none"


def test_guide_hint_shown_once(brain):
    assert brain.should_hint_guide("df -h") is True
    assert brain.should_hint_guide("df -h") is False
    assert brain.should_hint_guide("cat x") is False


def test_offline_calls_do_not_load_the_ai_providers():
    import subprocess
    code = ("import sys; sys.argv=['x']; import clishe_brain; "
            "print('providers' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parent.parent))
    assert out.stdout.strip() == "False", out.stderr


# ---------- the manual installed on this computer ----------

FIND_MAN = """FIND(1)                     General Commands Manual                    FIND(1)

NAME
       find - search for files in a directory hierarchy

OPTIONS
       -size n[cwbkMG]
              File uses less than, more than or exactly n units of space,
              rounding up.  The following suffixes can be used:

       -type c
              File is of type c:
"""


def test_explain_any_installed_command_from_its_manual(brain, monkeypatch):
    import manual
    monkeypatch.setattr(manual, "read_manual",
                        lambda name: (FIND_MAN, "man find") if name == "fd-find" else ("", ""))
    result = brain.explain("fd-find -size +1M")
    assert result["status"] == "ok"
    assert result["provider"] == "your system's manual"
    assert "search for files" in result["explanation"]
    assert "-size  File uses less than, more than or exactly n units of space," in result["explanation"]


def test_ai_suggestion_is_checked_against_the_manual(brain, monkeypatch):
    import clishe_brain
    import manual
    from providers.base import Resolution

    class Fake:
        name = "fake"

        def resolve_with_explanation(self, phrase):
            return Resolution("sudo find / -size +100M -bigger", "Big files.")

    monkeypatch.setattr(clishe_brain, "build_provider_chain", lambda config: [Fake()])
    monkeypatch.setattr(manual, "read_manual",
                        lambda name: (FIND_MAN, "man find") if name == "find" else ("", ""))
    result = brain.resolve("big files")
    assert result["manual"] == ["find -size: File uses less than, more than or exactly "
                                "n units of space, rounding up."]
    assert result["unverified"] == ["find -bigger"]


# ---------- learning by doing ----------

import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("typed,template,expected", [
    ("ls -la", "ls -la", True),
    ("ls -al", "ls -la", True),
    ("ls -l -a", "ls -la", True),
    ("ls", "ls -la", False),
    ("ls -lah", "ls -la", False),
    ("cp notes.txt backup/", "cp <file> <destination>", True),
    ("cp 'my notes.txt' b", "cp <file> <destination>", True),
    ("cp a", "cp <file> <destination>", False),
    ("tar -czvf site.tar.gz site", "tar -czvf <archive name>.tar.gz <folder>", True),
    ("tar -czvf site.zip site", "tar -czvf <archive name>.tar.gz <folder>", False),
    ("du -sh * | sort -h", "du -sh * | sort -h", True),
    ('echo "unterminated', "echo hi", False),
])
def test_same_command(typed, template, expected):
    from clishe_brain import same_command
    assert same_command(typed, template) is expected


def _ask(brain, phrase, times):
    for _ in range(times):
        brain.record_use(brain.query(phrase), phrase)


def test_your_turn_after_three_asks_until_right_twice(brain, monkeypatch):
    import clishe_brain
    monkeypatch.setattr(clishe_brain, "load_config", lambda: {})
    _ask(brain, "list files", 2)
    assert brain.your_turn("list files") == ""
    _ask(brain, "list files", 1)
    assert brain.your_turn("list files") == "ls -la"

    assert brain.attempt("list files", "ls")["status"] == "close"
    assert brain.attempt("list files", "dir")["status"] == "wrong"
    assert brain.attempt("list files", "ls -al")["status"] == "right"
    assert brain.your_turn("list files") == "ls -la"   # once isn't enough yet
    assert brain.attempt("Please list files?", "ls -la")["status"] == "right"
    assert brain.your_turn("list files") == ""


@_pytest.mark.parametrize("mode,asks,expected", [
    ("always", 1, "ls -la"),
    ("always", 0, ""),
    ("off", 10, ""),
    ("nonsense", 10, ""),
])
def test_learn_mode(brain, monkeypatch, mode, asks, expected):
    import clishe_brain
    monkeypatch.setattr(clishe_brain, "load_config", lambda: {"learn_mode": mode})
    _ask(brain, "list files", asks)
    assert brain.your_turn("list files") == expected


def test_progress_counts_commands_you_typed(brain):
    brain.record_use("sudo df -h")           # typed yourself
    brain.record_use("ls -la")
    brain.record_use("ls")
    brain.record_use("htop")
    _ask(brain, "show me disk usage", 1)     # asked, not typed: doesn't count
    _ask(brain, "count lines in a file", 1)  # wc: asked for, never typed
    progress = brain.progress()
    assert progress["learned"] == ["ls", "df"]
    assert progress["others"] == ["htop"]
    assert progress["total"] > 20
    assert progress["next"][0] == "pwd"


# ---------- tldr-pages ----------

def test_explain_a_command_from_tldr(brain, monkeypatch):
    import tldr
    monkeypatch.setattr(tldr, "_platforms", lambda: ("linux", "common"))
    result = brain.explain("rsync -a src dest")
    assert result["status"] == "ok"
    assert result["provider"].startswith("tldr-pages")
    assert result["explanation"].startswith("Transfer files either to or from a remote host")
    assert "Examples (from tldr-pages):" in result["explanation"]


def test_dictionary_explanations_gain_tldr_examples(brain):
    result = brain.explain("tar -xzvf a.tgz")
    assert result["provider"] == "offline dictionary and tldr-pages"
    assert "Examples (from tldr-pages):" in result["explanation"]


def test_spelling_matches_are_only_for_typos(brain):
    assert brain.suggest("show disk usge") == ("show me disk usage", "df -h")
    assert brain.suggest("count words in a file") != ("count lines in a file", "wc -l <file>")


# ---------- cheat sheet ----------

def test_cheat_sheet(brain):
    for command in ["ls -la", "ls -la", "ls", "df -h"]:
        brain.log(command)
        brain.record_use(command)                       # typed yourself
    brain.record_use("wc -l notes.txt", "count lines in a file")   # asked for
    brain.record_use("df -h", "show me disk usage")     # asked for, but typed too
    sheet = brain.cheat_sheet()
    commands = [command for command, _ in sheet["learned"]]
    assert commands == ["ls -la", "df -h"]               # most-used form, most-used first
    assert all(meaning for _, meaning in sheet["learned"])
    assert sheet["asked"] == [("count lines in a file", "wc -l <file>")]


def test_cheat_sheet_starts_empty(brain):
    assert brain.cheat_sheet() == {"learned": [], "asked": []}


# ---------- the action registry ----------

def test_every_action_the_shell_uses_is_registered():
    """clishe.sh calls the backend as `--action <name>`; a typo there would
    fail at runtime, in one session, with the Python error hidden."""
    import re
    import clishe_brain
    shell = (Path(__file__).resolve().parent.parent / "clishe.sh").read_text()
    for name in set(re.findall(r"--action ([a-z-]+)", shell)):
        assert name in clishe_brain.ACTIONS, f"clishe.sh uses unknown action '{name}'"


def test_every_registered_action_has_a_handler():
    import clishe_brain
    for name, handler in clishe_brain.ACTIONS.items():
        assert callable(handler), name
        assert handler.__name__ == f"_action_{name.replace('-', '_')}"
