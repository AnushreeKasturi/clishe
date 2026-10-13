"""
The guided breakdown: a command drawn with each part labelled underneath,

    find  .  -type f  -size +100M
    │     │  │        └─ bigger than 100M
    │     │  └─ only files, not folders
    │     └─ start in this folder
    └─ search for files in a directory hierarchy

so people see the shape of a command, not just a one-line answer. Labels
come from the offline dictionary and the man pages on this computer. When a
command doesn't fit this shape (pipes, redirects, very long lines), there is
no breakdown and Clishe shows the command the usual way.
"""
import os
import re
import shlex
from typing import List, Optional, Tuple

from knowledge import _COMMAND_DICT

MAX_PARTS = 7
MAX_LABEL = 56
GAP = "  "

_JOINERS = re.compile(r"\|\||&&|[|;&<>]|\$\(|`")
_PLACEHOLDER = re.compile(r"^<([a-z]+(?: [a-z]+)*)>$")
_ANY_PLACEHOLDER = re.compile(r"<[a-z]+(?: [a-z]+)*>")
_NUMBER = re.compile(r"^[+-]?\d")

# What common values mean, for the options beginners meet first.
_FIND_TYPES = {"f": "only files, not folders", "d": "only folders", "l": "only links"}


def _short(text: str) -> str:
    """A label-sized version of a sentence from a dictionary or man page."""
    text = (text or "").strip()
    # "ls - list directory contents" (GNU) or "ls – list..." (BSD)
    m = re.match(r"^[\w.+, -]{1,120}? [-–] (.+)$", text)
    if m:
        text = m.group(1)
    # Examples and cross-references belong in the man page, not a label.
    text = re.split(r",? (?:e\.g\.|i\.e\.|as described|see )", text, maxsplit=1)[0]
    text = re.sub(r"\s*\([^)]*\)", "", text)  # drop asides: "(bundles)"
    text = re.split(r"(?<=[a-z])\. |;", text, maxsplit=1)[0].strip().rstrip(".:,")
    if text[:1].isupper() and not text[1:2].isupper():
        text = text[0].lower() + text[1:]
    # Too long: end at a comma if that still leaves a full phrase
    # ("..., recursively" -> "..."), else cut with an ellipsis.
    if len(text) > MAX_LABEL and "," in text[:MAX_LABEL] and text.rindex(",", 0, MAX_LABEL) >= 30:
        text = text[:text.rindex(",", 0, MAX_LABEL)]
    if len(text) > MAX_LABEL:
        text = text[:MAX_LABEL - 1].rsplit(" ", 1)[0] + "…"
    return text


def _manual(name: str) -> str:
    from manual import read_manual
    return read_manual(name)[0]


def _letters(name: str, flag: str) -> List[Tuple[str, str]]:
    """-xzvf -> [("x", "extract an archive"), ("z", ...), ...], or [] if any
    letter has no label."""
    letters = [(c, _flag_label(name, f"-{c}")) for c in flag[1:]]
    return letters if all(label for _, label in letters) else []


def _flag_label(name: str, flag: str) -> str:
    entry = _COMMAND_DICT.get(name) or {}
    known = (entry.get("flags") or {}).get(flag)
    if known:
        return _short(known)
    text = _manual(name)
    if text:
        from manual import flag_help
        return _short(flag_help(text, flag))
    return ""


def _command_label(name: str) -> str:
    """What the command is, in a few words: tldr-pages' one-line summary
    (written to be short), then the NAME line of the local manual, then
    Clishe's own dictionary (full sentences, written for explain)."""
    import tldr
    if tldr.summary(name):
        return _short(tldr.summary(name))
    text = _manual(name)
    if text:
        from manual import summary
        found = summary(text)
        if found:
            return _short(found)
    entry = _COMMAND_DICT.get(name) or {}
    return _short(entry.get("summary", ""))


def _value_label(name: str, flag: str, value: str) -> str:
    """Labels for an option together with its value (find -size +100M)."""
    plain = value.strip("'\"")
    if name == "find":
        if flag == "-type" and plain in _FIND_TYPES:
            return _FIND_TYPES[plain]
        if flag in ("-name", "-iname"):
            return f"named {plain}" + (" (any case)" if flag == "-iname" else "")
        if flag == "-size" and plain[:1] in "+-":
            return ("bigger than " if plain[0] == "+" else "smaller than ") + plain[1:]
        if flag in ("-mtime", "-mmin") and plain[:1] == "-":
            unit = "days" if flag == "-mtime" else "minutes"
            return f"changed in the last {plain[1:]} {unit}"
    if flag in ("-n", "--lines") and plain.isdigit():
        return f"{plain} lines"
    return _flag_label(name, flag)


def _positional_label(token: str) -> str:
    plain = token.strip("'\"")
    m = _PLACEHOLDER.match(plain)
    if m:
        return f"the {m.group(1)} you choose"
    named = {".": "this folder", "./": "this folder", "..": "the folder above",
             "~": "your home folder", "~/": "your home folder", "/": "the whole system",
             "*": "everything in this folder", "-": "standard input"}
    if plain in named:
        return named[plain]
    return ""


def _word_label(name: str, token: str) -> str:
    """A plain word after the command: a subcommand the dictionary knows
    ("apt install", "git status"), else a path or value."""
    entry = _COMMAND_DICT.get(name) or {}
    known = (entry.get("flags") or {}).get(token)
    if known:
        return _short(known)
    return _positional_label(token) or _path_label(token)


def _path_label(plain: str) -> str:
    plain = plain.strip("'\"")
    if "*" in plain or "?" in plain:
        return f"everything matching {plain}"
    if os.path.isdir(os.path.expanduser(plain)):
        return "a folder"
    if os.path.isfile(os.path.expanduser(plain)):
        return "a file"
    return ""


def split_parts(command: str) -> Optional[List[Tuple[str, str]]]:
    """[(text, label)] for each part of a simple command, or None if the
    command has pipes, redirects or other things this layout can't show.
    A label is a string, or a list of strings for options written together."""
    if not command or _JOINERS.search(_ANY_PLACEHOLDER.sub("x", command)) or "\n" in command:
        return None
    # Keep "<archive name>" in one piece while splitting into words.
    holes = _ANY_PLACEHOLDER.findall(command)
    masked = _ANY_PLACEHOLDER.sub(lambda m: f"\x00{holes.index(m.group(0))}\x00", command)
    try:
        words = shlex.split(masked, posix=False)
    except ValueError:
        return None
    words = [re.sub(r"\x00(\d+)\x00", lambda m: holes[int(m.group(1))], w) for w in words]
    if not words:
        return None

    parts = []
    if words[0] == "sudo" and len(words) > 1:
        parts.append(("sudo", "as the administrator (asks for your password)"))
        words = words[1:]
    name = os.path.basename(words[0])
    parts.append((words[0], _command_label(name)))

    i = 1
    while i < len(words):
        tok = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else None
        if tok.startswith("-") and len(tok) > 1 and tok not in ("--",):
            word_option = (tok.startswith("--") or len(tok) == 2
                           or bool(_flag_label(name, tok)))
            takes_value = nxt is not None and (
                not nxt.startswith("-") or _NUMBER.match(nxt)) and (
                (word_option and not tok.startswith("--") and len(tok) > 2)
                or (tok in ("-n", "--lines") and nxt.isdigit()))
            if takes_value:
                parts.append((f"{tok} {nxt}", _value_label(name, tok, nxt)))
                i += 2
                continue
            if word_option:
                parts.append((tok, _flag_label(name, tok)))
            else:
                # Short options written together (-xzvf): one line per letter.
                letters = _letters(name, tok)
                parts.append((tok, [f"-{c}  {label}" for c, label in letters] or ""))
        else:
            parts.append((tok, _word_label(name, tok)))
        i += 1
    return parts


def draw(command: str, width: int = 80, plain: bool = False) -> Optional[dict]:
    """{"command": the spaced command, "lines": [(tree, label)]}, or None
    when the breakdown wouldn't help or wouldn't fit. With plain=True the
    lines are a simple "part: meaning" list in reading order (no tree), for
    screen readers."""
    parts = split_parts(command)
    if not parts or len(parts) > MAX_PARTS:
        return None
    labelled = [i for i, (_, label) in enumerate(parts) if label]
    if len(labelled) < 2 or not parts[0][1]:
        return None

    if plain:
        lines = []
        for i in labelled:
            text, label = parts[i]
            for sub in (label if isinstance(label, list) else [f"{text}  {label}"]):
                part, _, meaning = sub.partition("  ")
                lines.append(("", f"{part}: {meaning}"))
        return {"command": GAP.join(text for text, _ in parts), "lines": lines}

    positions, pos = [], 0
    for text, _ in parts:
        positions.append(pos)
        pos += len(text) + len(GAP)
    spaced = GAP.join(text for text, _ in parts)

    lines = []
    for i in reversed(labelled):
        tree = ""
        for j in labelled:
            if j >= i:
                break
            tree += " " * (positions[j] - len(tree)) + "│"
        tree += " " * (positions[i] - len(tree))
        labels = parts[i][1] if isinstance(parts[i][1], list) else [parts[i][1]]
        for n, label in enumerate(labels):
            branch = "└─ " if n == len(labels) - 1 else "├─ "
            lines.append((tree + branch, label))
    widest = max([len(spaced)] + [len(tree) + len(label) for tree, label in lines])
    if widest > width:
        return None
    return {"command": spaced, "lines": lines}
