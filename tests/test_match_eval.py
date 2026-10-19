"""Keeps Clishe's plain-English matching from getting worse.

The numbers come from tests/match_eval.json (see tests/match_eval.py).
A change to seed_kb.json, the synonyms or the matching must not lose right
answers or add wrong ones. When a change makes things better, raise
MIN_RIGHT / lower MAX_WRONG to the new numbers so they stay that way.
Run `python tests/match_eval.py` to see every wrong and missed phrase.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from match_eval import evaluate, load_cases  # noqa: E402

MIN_RIGHT = 150
MAX_WRONG = 38


def test_cases_are_well_formed():
    cases = load_cases()
    says = [c["say"] for c in cases]
    assert len(says) == len(set(says)), "a phrase is listed twice"
    for case in cases:
        assert case["say"].strip() and case["say"] == case["say"].lower(), case
        assert isinstance(case["want"], list), case
        assert all(isinstance(w, str) and w.strip() for w in case["want"]), case


def test_matching_does_not_get_worse():
    counts, rows = evaluate()
    wrong = [f"{case['say']!r} -> {command!r}" for case, _, command, verdict in rows
             if verdict == "wrong"]
    assert counts["wrong"] <= MAX_WRONG, (
        f"{counts['wrong']} wrong answers (was at most {MAX_WRONG}):\n  " + "\n  ".join(wrong))
    assert counts["right"] >= MIN_RIGHT, (
        f"{counts['right']} right answers (was at least {MIN_RIGHT}). "
        "Run `python tests/match_eval.py` to see which phrases changed.")
