"""How well does Clishe turn plain English into the right command, offline?

tests/match_eval.json lists things beginners actually type, each with the
commands that would be a right answer ([] means Clishe should say nothing).
Each phrase goes through the same offline steps as a session: your phrases
and the seed KB (exact), "did you mean...?" (suggest), then tldr-pages.

Every result is one of:
- right:  a right command
- wrong:  a command, but not a right one (or any command when it should
          have said nothing). The number that matters most.
- missed: nothing, when there was a right answer. Annoying, not harmful.

Run `python tests/match_eval.py` for the full report;
tests/test_match_eval.py keeps the numbers from getting worse.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tldr  # noqa: E402
from clishe_brain import ClisheBrain  # noqa: E402

CASES_FILE = Path(__file__).resolve().parent / "match_eval.json"


def load_cases():
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


def fake_linux_machine():
    """Linux pages with every command installed, so the result doesn't
    depend on the machine. Returns a function that undoes it."""
    saved = tldr._platforms, tldr.shutil.which
    tldr._platforms = lambda: ("linux", "common")
    tldr.shutil.which = lambda name: f"/usr/bin/{name}"
    tldr._installed_examples.cache_clear()

    def undo():
        tldr._platforms, tldr.shutil.which = saved
        tldr._installed_examples.cache_clear()
    return undo


def resolve(brain, phrase):
    """(stage, command) the way a session would answer, offline:
    stage is "exact", "suggest", "tldr" or "" (nothing)."""
    command = brain.query(phrase)
    if command:
        return "exact", command
    found = brain.suggest(phrase)
    if found:
        return "suggest", found[1]
    found = brain.suggest_example(phrase)
    if found:
        return "tldr", found[1]
    return "", ""


def evaluate(cases=None):
    """Run every case. Returns (counts, rows): counts of right/wrong/missed
    and (case, stage, command, verdict) for each one."""
    cases = load_cases() if cases is None else cases
    brain = ClisheBrain()
    brain.kb = {}  # only the bundled data, never this machine's own phrases
    undo = fake_linux_machine()
    try:
        rows = []
        for case in cases:
            stage, command = resolve(brain, case["say"])
            if not command:
                verdict = "missed" if case["want"] else "right"
            else:
                verdict = "right" if command in case["want"] else "wrong"
            rows.append((case, stage, command, verdict))
    finally:
        undo()
    return Counter(v for *_, v in rows), rows


def main():
    counts, rows = evaluate()
    total = len(rows)
    for verdict in ("wrong", "missed"):
        picked = [r for r in rows if r[3] == verdict]
        print(f"\n{verdict.upper()} ({len(picked)})")
        for case, stage, command, _ in picked:
            want = " | ".join(case["want"]) or "(nothing)"
            got = f"{command}  [{stage}]" if command else "(nothing)"
            print(f"  {case['say']!r}\n      got:  {got}\n      want: {want}")
    print(f"\n{total} phrases: "
          + ", ".join(f"{counts[v]} {v} ({counts[v] / total:.0%})"
                      for v in ("right", "wrong", "missed")))
    by_stage = Counter(stage or "none" for _, stage, _, _ in rows)
    print("answered by: " + ", ".join(f"{s} {n}" for s, n in by_stage.most_common()))


if __name__ == "__main__":
    main()
