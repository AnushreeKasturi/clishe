"""Fuzz tests for safety.py: wrap every command from test_safety.py in the
ways real shell lines wrap commands (sudo, subshells, if/then, bash -c,
2>/dev/null...) and check the verdict doesn't change.

- A dangerous command stays flagged, with the same reasons, however it's wrapped.
- A safe command stays unflagged.

The random choices use fixed seeds, so a failure is the same on every run
and every machine. The assertion message prints the exact command.

Known limit: shlex can't read quotes nested inside "$(...)", so
echo "$(echo "2>/dev/sda")" is flagged although it only prints. That errs
on the safe side, so it isn't tested here."""
import random
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from safety import check_command  # noqa: E402
from test_safety import DANGEROUS, SAFE  # noqa: E402

# Words that run the rest of the line as the real command. They only apply
# to the first command, so they're used on single commands only.
PREFIXES = [
    "sudo ", "sudo -u root ", "sudo -E ", "sudo -- ", "doas ", "env ",
    "env -i ", "FOO=1 ", "nohup ", "nice ", "nice -n 5 ", "timeout 5 ",
    "timeout 5s ", "timeout -s KILL 5 ", "time ", "command ", "exec ",
    "builtin ", "stdbuf -oL ", "ionice -c 3 ", "! ", "/usr/bin/env ",
    "sudo env ", "busybox ",
]

# Ways a whole line can be put inside another one and still run.
WRAPS = [
    lambda c: f"true && {c}",
    lambda c: f"false || {c}",
    lambda c: f"cd /tmp; {c}",
    lambda c: f"echo start\n{c}",
    lambda c: f"{c} & wait",
    # "((" would be arithmetic, not a subshell.
    lambda c: f"( {c})" if c.startswith("(") else f"({c})",
    lambda c: f"( {c} )",
    lambda c: f"{{ {c}; }}",
    lambda c: f"if true; then {c}; fi",
    lambda c: f"for f in a; do {c}; done",
    lambda c: f"while true; do {c}; break; done",
    lambda c: f"bash -c {shlex.quote(c)}",
    lambda c: f"sh -c {shlex.quote(c)}",
    lambda c: f"sudo bash -c {shlex.quote(c)}",
    lambda c: f"eval {shlex.quote(c)}",
    # Spaces after "$(" keep "$((" (arithmetic) out. A bare $(cmd) would
    # run cmd's output as a command, so it's behind ":" (which ignores it).
    lambda c: f": $( {c} )",
    lambda c: f"x=$( {c} )",
    lambda c: f"echo \"$( {c} )\"",
    lambda c: f"{c} 2>/dev/null",
    lambda c: f"{c} 2>&1",
    lambda c: f"{c} | tee log.txt",
]

# Safe text that must stay safe: a dangerous-looking command that is only
# printed, never run.
QUOTED_ONLY = [
    "echo 'rm -rf /'",
    "echo '$(rm -rf /)'",
    "echo '`rm -rf ~`'",
    "printf '%s\\n' '(rm -rf /)'",
    "grep -r 'sudo rm -rf' notes/",
]

CASES_PER_COMMAND = 12


def _is_single_command(command: str) -> bool:
    """A plain command a prefix can go in front of (`sudo (rm x)` and
    `env ! rm x` aren't valid shell)."""
    return not (command.lstrip().startswith(("(", "{", "!"))
                or any(sep in command for sep in (";", "&&", "||", "|", "\n", "&")))


def _variants(command: str, seed: int):
    """Fixed-seed random wrappings of `command`, one to two layers deep."""
    rng = random.Random(seed)
    single = _is_single_command(command)
    for _ in range(CASES_PER_COMMAND):
        line = command
        if single and rng.random() < 0.5:
            line = rng.choice(PREFIXES) + line
        for _layer in range(rng.randint(1, 2)):
            line = rng.choice(WRAPS)(line)
        yield line


@pytest.mark.parametrize("command,key", DANGEROUS)
def test_wrapping_a_dangerous_command_keeps_it_flagged(command, key):
    expected = set(check_command(command))
    for i, line in enumerate(_variants(command, seed=hash_seed(command))):
        got = set(check_command(line))
        missing = expected - got
        assert not missing, f"variant {i}: {line!r} lost {sorted(missing)}"


@pytest.mark.parametrize("command", SAFE + QUOTED_ONLY)
def test_wrapping_a_safe_command_keeps_it_safe(command):
    for i, line in enumerate(_variants(command, seed=hash_seed(command))):
        assert check_command(line) == [], f"variant {i}: {line!r} was flagged"


@pytest.mark.parametrize("prefix", PREFIXES)
def test_every_prefix_is_seen_through(prefix):
    assert check_command(prefix + "rm -rf build")


@pytest.mark.parametrize("wrap", range(len(WRAPS)))
def test_every_wrap_is_seen_through(wrap):
    assert check_command(WRAPS[wrap]("rm -rf build"))


def hash_seed(command: str) -> int:
    """A seed from the command text that, unlike hash(), is the same in
    every Python process."""
    return sum((i + 1) * ord(ch) for i, ch in enumerate(command))
