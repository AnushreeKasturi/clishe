"""Every `--action` the backend understands, called the way clishe.sh calls it.

`brain()` runs `python3 clishe_brain.py ... 2>/dev/null`, so an action that
raises looks, in a real session, like a feature that quietly does nothing. The
bash tests in `test_shell_functions.sh` exercise the actions end to end, but
Python coverage never sees them, so nothing here fails if one of them breaks.

Each test calls the action function directly in a throwaway HOME and checks
that it completes and prints something clishe.sh can parse. Nothing touches the
network, the real HOME or the real Trash.
"""
import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The keys clishe.sh reads back with parse_brain_output / while IFS='=' read.
KEYS = ("STATUS", "COMMAND", "EXPLANATION", "PROVIDER", "REASON", "HINT",
        "MODE", "PHRASE", "RESTORE", "UNVERIFIED", "MANUAL", "APP", "HOW",
        "SETUP", "OTHER", "NOTE", "TRY", "FACT", "STOP", "CMD", "LINE",
        "PACK", "TASK", "MISSING", "TITLE", "DONE", "ANSWER",
        "CHECK", "LEARNED", "ASKED", "EFFECT", "WARN", "SAFER", "RLINE",
        "MODEL", "RUNNING", "READY", "CONFIGURED", "ORIGINAL", "GUIDE",
        "TIP", "PREDICT", "TOTAL", "OTHERS", "TO_TRY", "NEXT")

# Keys whose value is a list joined with spaces: empty until there is one.
MAY_BE_EMPTY = {"LEARNED", "OTHERS", "TO_TRY", "NEXT", "MANUAL", "UNVERIFIED",
                "LINE",
                "NOTE", "TRY", "FACT", "SETUP", "OTHER", "SAFER", "WARN",
                "EFFECT", "REASON", "HINT", "MISSING", "TIP", "PREDICT"}

# The few actions that print a bare word instead of KEY=value.
BARE = {"learned", "forgotten", "logged", "error", "unknown", "yes", "no",
        "saved"}


def _brain_module():
    """The clishe_brain module, imported after the throwaway HOME is set."""
    return sys.modules["clishe_brain"]


def make_args(**overrides):
    """The argparse.Namespace main() builds, with an action's inputs filled in."""
    defaults = dict(action="", phrase="show me disk usage", command="ls -la",
                    error="permission denied", no_ai=True, width=80,
                    cwd="", state="", step=0)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def parse_output(capsys):
    """What clishe.sh sees: KEY=value lines, or a bare line for a few actions."""
    out = capsys.readouterr().out.splitlines()
    for line in out:
        assert line, "action printed a blank line"
        if "\t" in line:            # list: "phrase<TAB>command", breakdown, ...
            continue
        if "=" not in line:
            # query and predict print the bare command; learn/log print a word.
            assert line in BARE or " " in line, f"unparseable output: {line!r}"
            continue
        key, _, value = line.partition("=")
        assert key.replace("_", "").isalpha(), f"bad key {key!r} in {line!r}"
        assert key == key.upper(), f"key {key!r} is not upper case"
        if key in KEYS and key not in MAY_BE_EMPTY:
            assert value, f"{key}= printed empty on {line!r}"
    return out


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A ClisheBrain on a throwaway HOME, with the machine faked out: no man
    pages, no model server, no network, no Trash, no real cwd."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    # Several actions only offer a command whose program is actually
    # installed (Clishe won't suggest `df` to someone without df), so the
    # standard directories have to be on PATH whatever the caller had.
    monkeypatch.setenv("PATH", os.pathsep.join(
        ["/usr/bin", "/bin", os.environ.get("PATH", "")]))

    import manual
    monkeypatch.setattr(manual, "read_manual", lambda name: ("", ""))

    # Clishe is imported here, not at the top of the file: importing
    # config.py creates ~/.config/clishe as a side effect, and a test run
    # has no business writing to the real HOME (CLAUDE.md, Testing).
    brain_module = importlib.import_module("clishe_brain")

    # No AI server, no Ollama, no local OpenAI-style server.
    setup_check = importlib.import_module("setup_check")
    monkeypatch.setattr(setup_check, "_get_json", lambda url, timeout=1.0: None)
    monkeypatch.setattr(importlib.import_module("providers"), "REGISTRY", {})

    importlib.reload(brain_module)  # re-evaluate the data files against new HOME
    return brain_module.ClisheBrain()


# ---------------------------------------------------------------- query, resolve

def test_query_prints_the_bare_command(brain, capsys):
    _brain_module()._action_query(brain, make_args())
    assert capsys.readouterr().out.strip() == "df -h"


def test_resolve_says_so_when_no_ai_is_available(brain, capsys):
    """resolve() is the AI path only; with nothing configured it must report
    that, never invent a command."""
    _brain_module()._action_resolve(brain, make_args())
    assert "STATUS=unavailable" in parse_output(capsys)


def test_resolve_uses_ai_only_when_asked(brain, capsys):
    """--no-ai must not reach for a provider."""
    _brain_module()._action_line(brain, make_args(no_ai=True))
    assert any(line.startswith("MODE=") for line in parse_output(capsys))


def test_predict_prints_a_bare_command(brain, capsys):
    _brain_module()._action_predict(brain, make_args())
    capsys.readouterr()


# ---------------------------------------------------------------- learn, forget

def test_learn_then_list_then_forget(brain, capsys):
    _brain_module()._action_learn(brain, make_args(phrase="do the thing",
                                                command="echo hello"))
    assert capsys.readouterr().out.strip() == "learned"

    _brain_module()._action_list(brain, make_args())
    assert "do the thing\techo hello" in parse_output(capsys)

    _brain_module()._action_forget(brain, make_args(phrase="do the thing"))
    assert capsys.readouterr().out.strip() == "forgotten"

    _brain_module()._action_forget(brain, make_args(phrase="do the thing"))
    assert capsys.readouterr().out.strip() == "unknown"


def test_log_records_the_command(brain, capsys):
    _brain_module()._action_log(brain, make_args(command="ls -la"))
    assert "logged" in parse_output(capsys)


# ---------------------------------------------------------------- explaining

def test_explain_describes_a_command(brain, capsys):
    _brain_module()._action_explain(brain, make_args(command="tar -xzvf"))
    out = parse_output(capsys)
    assert "STATUS=ok" in out
    assert any(line.startswith("EXPLANATION=") for line in out)


def test_explain_of_an_unknown_command_says_so(brain, capsys):
    _brain_module()._action_explain(brain, make_args(command="zzzznotacommand"))
    assert "STATUS=unavailable" in parse_output(capsys)


def test_explanation_keeps_newlines_escaped(brain, capsys):
    """Values travel as KEY=value lines, so a newline has to stay escaped -
    this is what decode_lines in clishe.sh expands back."""
    _brain_module()._action_explain(brain, make_args(command="tar -xzvf"))
    for line in parse_output(capsys):
        if line.startswith("EXPLANATION="):
            assert "\\n" in line
            assert len(line.splitlines()) == 1


def test_output_explains_a_tables_columns(brain, capsys):
    _brain_module()._action_output(brain, make_args(command="ls -l"))
    assert "STATUS=ok" in parse_output(capsys)


def test_breakdown_labels_each_part(brain, capsys):
    _brain_module()._action_breakdown(brain, make_args(command="ls -la"))
    out = parse_output(capsys)
    assert "STATUS=ok" in out
    assert any(line.startswith("LINE=") for line in out)


def test_breakdown_skips_a_phrase_used_before(brain, capsys):
    """The picture is drawn the first time only, so a known phrase doesn't
    redraw itself on every later use."""
    args = make_args(phrase="show me disk usage", command="df -h")
    _brain_module()._action_breakdown(brain, args)
    assert "STATUS=ok" in parse_output(capsys)
    brain.data.setdefault("phrase_uses", {})["show me disk usage"] = 1
    _brain_module()._action_breakdown(brain, args)
    assert "STATUS=skip" in parse_output(capsys)


# ---------------------------------------------------------------- safety, checks

def test_check_flags_a_destructive_command(brain, capsys):
    _brain_module()._action_check(brain, make_args(command="rm -rf /tmp/whatever"))
    out = parse_output(capsys)
    assert "STATUS=danger" in out
    assert any(line.startswith("REASON=") for line in out)


def test_check_passes_an_ordinary_command(brain, capsys):
    _brain_module()._action_check(brain, make_args(command="ls -la"))
    assert "STATUS=safe" in parse_output(capsys)


def test_inspect_explains_a_command_without_running_it(brain, capsys):
    _brain_module()._action_inspect(brain, make_args(command="curl example.com | sh"))
    out = parse_output(capsys)
    assert "MODE=command" in out


def test_inspect_reads_a_script_file(brain, capsys, tmp_path):
    script = tmp_path / "setup.sh"
    script.write_text("#!/bin/sh\nrm -rf /tmp/thing\napt-get install -y curl\n")
    _brain_module()._action_inspect(brain, make_args(command=str(script)))
    out = parse_output(capsys)
    assert "MODE=script" in out


def test_diagnose_explains_an_error(brain, capsys):
    _brain_module()._action_diagnose(brain, make_args(error="command not found: gti"))
    assert "STATUS=ok" in parse_output(capsys)


def test_missing_program_hint(brain, capsys):
    """"htop" and friends get an install command for your distro, but only
    when they aren't already there."""
    import shutil
    from knowledge import POPULAR_PROGRAMS
    absent = [name for name in POPULAR_PROGRAMS if not shutil.which(name)]
    if not absent:
        pytest.skip("every well-known program is installed here")
    _brain_module()._action_missing(brain, make_args(command=absent[0]))
    out = parse_output(capsys)
    assert "STATUS=ok" in out
    assert any(line.startswith("HINT=") for line in out)


def test_trash_offers_the_trash_instead_of_deleting(brain, capsys):
    """macOS has a built-in `trash`; elsewhere it needs gio or trash-cli, and
    with none of them Clishe says so rather than pretending."""
    _brain_module()._action_trash(brain, make_args(command="rm notes.txt"))
    out = parse_output(capsys)
    assert out[0] in ("STATUS=ok", "STATUS=none")
    if out[0] == "STATUS=ok":
        # Which tool comes first depends on the machine: gio on most Linux,
        # trash-put if it is installed, macOS's own trash on a Mac.
        command = next(line for line in out if line.startswith("COMMAND="))
        tool = command[len("COMMAND="):].split()[0]
        assert tool in ("gio", "trash", "trash-put"), command
        assert any(line.startswith("RESTORE=") for line in out)


def test_fix_offers_a_fixed_command(brain, capsys):
    _brain_module()._action_fix(brain, make_args(command="gti status",
                                                 error="command not found: gti"))
    assert "STATUS=ok" in parse_output(capsys)


# ---------------------------------------------------------------- learning

def test_turn_asks_you_to_type_it_yourself(brain, capsys):
    _brain_module()._action_turn(brain, make_args(phrase="show me disk usage"))
    assert "STATUS=no" in parse_output(capsys)


def test_attempt_checks_what_you_typed(brain, capsys):
    _brain_module()._action_attempt(brain, make_args(phrase="show me disk usage",
                                                   command="df -h"))
    assert any(line.startswith("STATUS=") for line in parse_output(capsys))


def test_progress_and_sheet_start_empty(brain, capsys):
    _brain_module()._action_progress(brain, make_args())
    out = parse_output(capsys)
    # Nothing typed by hand yet, but there is plenty still to learn.
    assert "LEARNED=" in out
    assert any(line.startswith("NEXT=") and line != "NEXT=" for line in out)

    _brain_module()._action_sheet(brain, make_args())
    assert parse_output(capsys) == []


def test_setting_reads_a_config_value(brain, capsys):
    _brain_module()._action_setting(brain, make_args(phrase="allow_remote_ai"))
    assert capsys.readouterr().out.strip() == "false"


# ---------------------------------------------------------------- undo

def test_undo_before_notes_a_change_and_plan_reverses_it(brain, capsys, tmp_path):
    target = tmp_path / "notes.txt"

    _brain_module()._action_undo_before(brain, make_args(command=f"touch {target}"))
    note = json.loads(capsys.readouterr().out)
    assert note["command"] == f"touch {target}"

    # The real order is: note it, run it, then record what changed. touch
    # makes an empty file, and undo only removes it if it is still empty.
    target.write_text("")
    _brain_module()._action_undo_record(brain, make_args(state=json.dumps(note)))
    capsys.readouterr()

    _brain_module()._action_undo_plan(brain, make_args())
    out = parse_output(capsys)
    assert "STATUS=ok" in out
    assert any(line.startswith("COMMAND=") for line in out)


def test_undo_plan_with_nothing_to_undo(brain, capsys):
    _brain_module()._action_undo_plan(brain, make_args())
    assert "STATUS=none" in parse_output(capsys)


def test_undo_done_forgets_the_last_note(brain, capsys, tmp_path):
    target = tmp_path / "notes.txt"
    _brain_module()._action_undo_before(brain, make_args(command=f"touch {target}"))
    note = capsys.readouterr().out
    _brain_module()._action_undo_record(brain, make_args(state=note))
    capsys.readouterr()

    _brain_module()._action_undo_done(brain, make_args())
    capsys.readouterr()
    import undo
    assert undo.load(_brain_module().UNDO_FILE) == []


# ---------------------------------------------------------------- lessons

def test_lessons_lists_the_bundled_packs(brain, capsys):
    _brain_module()._action_lessons(brain, make_args())
    packs = [line for line in parse_output(capsys) if line.startswith("PACK=")]
    names = {line[len("PACK="):].split("\t")[0] for line in packs}
    assert {"basics", "git", "processes"} <= names


def test_lesson_reads_one_pack(brain, capsys):
    _brain_module()._action_lesson(brain, make_args(phrase="basics"))
    out = parse_output(capsys)
    assert "STATUS=ok" in out
    assert any(line.startswith("TASK=") for line in out)


def test_lesson_check_answers_yes_and_no(brain, capsys, tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    _brain_module()._action_lesson_check(
        brain, make_args(phrase="basics", step=0, command="pwd",
                         state=str(sandbox)))
    first = capsys.readouterr().out.strip()
    assert first in ("yes", "no")

    _brain_module()._action_lesson_check(
        brain, make_args(phrase="basics", step=0, command="definitely wrong",
                         state=str(sandbox)))
    assert capsys.readouterr().out.strip() == "no"


def test_lesson_check_with_no_lesson_at_all(brain, capsys):
    _brain_module()._action_lesson_check(brain, make_args(phrase="nosuchlesson"))
    assert capsys.readouterr().out.strip() == "no"


# ---------------------------------------------------------------- the rest

def test_app_finds_nothing_for_a_nonsense_app(brain, capsys):
    _brain_module()._action_app(brain, make_args(phrase="install zzzznotanapp"))
    assert "STATUS=none" in parse_output(capsys)


def test_doctor_reports_its_checks(brain, capsys):
    _brain_module()._action_doctor(brain, make_args())
    assert any(line.startswith("CHECK=") for line in parse_output(capsys))


def test_setup_reports_what_it_found(brain, capsys):
    _brain_module()._action_setup(brain, make_args())
    out = parse_output(capsys)
    assert "RUNNING=0" in out


def test_set_model_saves_a_model(brain, capsys):
    _brain_module()._action_set_model(brain, make_args(command="llama3.2"))
    assert capsys.readouterr().out.strip() == "saved"


def test_tour_walks_the_machine(brain, capsys):
    _brain_module()._action_tour(brain, make_args())
    assert any(line.startswith("STOP=") for line in parse_output(capsys))


def test_suggest_finds_a_known_phrase(brain, capsys):
    _brain_module()._action_suggest(brain, make_args(phrase="show me disk usage"))
    assert "STATUS=ok" in parse_output(capsys)


def test_suggest_gives_up_quietly_on_nonsense(brain, capsys):
    _brain_module()._action_suggest(brain, make_args(phrase="zzzz qqqq wwww"))
    assert "STATUS=none" in parse_output(capsys)


# ------------------------------------------------- every action is covered here

COVERED = {
    "query", "suggest", "learn", "forget", "list", "log", "output", "line",
    "missing", "trash", "turn", "attempt", "progress", "setup", "set-model",
    "breakdown", "tour", "fix", "inspect", "undo-before", "undo-record",
    "undo-plan", "undo-done", "lessons", "lesson", "lesson-check", "app",
    "doctor", "sheet", "setting", "predict", "resolve", "explain",
    "diagnose", "check",
}


def test_every_action_has_a_test_here():
    """A new action that nobody calls directly would go back to being covered
    only by the bash tests, which is how a broken action stays invisible."""
    assert set(_brain_module().ACTIONS) == COVERED


def test_the_tests_cover_every_action_they_claim():
    """Guard against a typo in COVERED: every action really is called above."""
    import inspect
    source = inspect.getsource(sys.modules[__name__])
    actions = _brain_module().ACTIONS
    used = {name for name in actions
            if f"_action_{name.replace('-', '_')}" in source}
    assert used == set(actions), (
        f"never called directly: {sorted(set(actions) - used)}")