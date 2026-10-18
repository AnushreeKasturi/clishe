"""Fail the run if the tests leave anything behind in the checkout."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _changes():
    """`git status` lines for the checkout, or None when git can't tell."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return set(out.stdout.splitlines()) if out.returncode == 0 else None


def pytest_sessionstart(session):
    session.config._clishe_tree = _changes()


def pytest_sessionfinish(session, exitstatus):
    before = session.config._clishe_tree
    after = _changes()
    if before is None or after is None:
        return
    left = sorted(after - before)
    if left:
        print("\nThe tests changed the checkout (use tmp_path instead):\n  " + "\n  ".join(left))
        session.exitstatus = 1
