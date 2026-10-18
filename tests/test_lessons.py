"""Tests for lessons.py - lesson packs for `clishe practice`."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lessons  # noqa: E402

BUNDLED = sorted(p.stem for p in lessons.BUNDLED.glob("*.json"))


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_packs_are_valid(name):
    pack = json.loads((lessons.BUNDLED / f"{name}.json").read_text())
    assert lessons.problems(pack) == []


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_packs_can_be_solved(name, tmp_path):
    """Run every answer, in order, in a real folder: each one must pass its
    own check. Catches a lesson nobody can finish."""
    pack = lessons.read(name)
    sandbox = tmp_path.resolve()
    cwd = sandbox
    for n, ex in enumerate(pack["exercises"], 1):
        # Start bash in the folder itself rather than with `cd` in the script:
        # if that cd failed, the answer ran wherever pytest was started (the
        # checkout) and left files there.
        out = subprocess.run(["bash", "-c", f"{{ {ex['answer']}\n}} >/dev/null 2>&1; "
                              "kill $(jobs -p) 2>/dev/null; pwd"],
                             cwd=cwd, capture_output=True, text=True)
        cwd = Path(out.stdout.strip().splitlines()[-1]).resolve()
        assert cwd.is_dir() and cwd.is_relative_to(sandbox), \
            f"{name} exercise {n}: the answer {ex['answer']!r} left the practice folder ({cwd})"
        assert lessons.passes(ex["check"], ex["answer"], str(cwd), str(sandbox)), \
            f"{name} exercise {n} ({ex['task']}): the answer {ex['answer']!r} doesn't pass its check"


@pytest.mark.parametrize("check,typed,expected", [
    ([{"typed": "^ls"}], "ls -la", True),
    ([{"typed": "^ls"}], "pwd", False),
    ([{"dir": "notes"}], "", True),
    ([{"file": "notes"}], "", False),
    ([{"file": "notes/a.txt"}], "", True),
    ([{"missing": "gone.txt"}], "", True),
    ([{"missing": "notes"}], "", False),
    ([{"contains": ["notes/a.txt", "milk"]}], "", True),
    ([{"contains": ["notes/a.txt", "eggs"]}], "", False),
    ([{"cwd": "notes"}], "", False),
    ([{"cwd": "."}], "", True),
    ([{"dir": "notes"}, {"typed": "^x"}], "y", False),
])
def test_conditions(tmp_path, check, typed, expected):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.txt").write_text("buy milk")
    assert lessons.passes(check, typed, str(tmp_path), str(tmp_path)) is expected


def test_checks_never_look_outside_the_practice_folder(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (tmp_path / "secret.txt").write_text("password")
    assert not lessons.passes([{"file": "../secret.txt"}], "", str(sandbox), str(sandbox))
    assert not lessons.passes([{"contains": ["../secret.txt", "password"]}], "", str(sandbox), str(sandbox))
    assert lessons.passes([{"missing": "/etc/hostname"}], "", str(sandbox), str(sandbox))


@pytest.mark.parametrize("pack,problem", [
    ([], "one JSON object"),
    ({"exercises": []}, 'missing "title"'),
    ({"title": "x", "exercises": [{"task": "t", "hint": "h", "answer": "a"}]}, 'missing "check"'),
    ({"title": "x", "exercises": [{"task": "t", "check": [{"run": "rm -rf /"}], "hint": "h", "answer": "a"}]},
     "unknown check"),
    ({"title": "x", "exercises": [{"task": "t", "check": [{"typed": "("}], "hint": "h", "answer": "a"}]},
     "bad pattern"),
])
def test_problems_are_explained(pack, problem):
    assert any(problem in p for p in lessons.problems(pack))


def test_your_own_lessons_are_found_and_win_on_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    folder = tmp_path / "clishe" / "lessons"
    folder.mkdir(parents=True)
    pack = {"title": "Mine", "exercises": [{"task": "t", "check": [{"typed": "x"}],
                                            "hint": "h", "answer": "x"}]}
    (folder / "mine.json").write_text(json.dumps(pack))
    (folder / "broken.json").write_text("{not json")
    names = [p["name"] for p in lessons.available()]
    assert names[0] == "basics" and "mine" in names and "broken" not in names
    (folder / "basics.json").write_text(json.dumps(pack))
    assert lessons.read("basics")["title"] == "Mine"


def test_needs_reports_missing_programs(monkeypatch):
    pack = {"title": "x", "needs": ["git", "nope-not-here"],
            "exercises": [{"task": "t", "check": [{"typed": "x"}], "hint": "h", "answer": "x"}]}
    assert lessons.problems(pack) == []
    monkeypatch.setattr(lessons.shutil, "which", lambda n: None if n == "nope-not-here" else "/usr/bin/" + n)
    assert lessons.missing(pack) == ["nope-not-here"]
    assert lessons.problems({**pack, "needs": "git"})   # must be a list
