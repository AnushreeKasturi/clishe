"""
Safety check for commands before Clishe runs them.

Every command Clishe is about to run (from your KB, an AI suggestion, or
something you typed) goes through `check_command`. If it looks destructive,
the shell asks you to type YES, and shows you *why* in plain English, so
the warning teaches something instead of just blocking.

This is a best-effort guard, not a sandbox. It catches common ways to lose
data or break a system; it can't catch everything. Read what you run.
"""
import os
import re
import shlex
from typing import List, Optional

# Tokens that separate one command from the next on a single line.
_SEPARATORS = {";", "&&", "||", "|", "&", "|&", "\n"}

# Wrappers that run the *next* word as the real command.
_WRAPPERS = {"sudo", "doas", "env", "nice", "nohup", "time", "command",
             "exec", "builtin", "xargs", "ionice", "stdbuf", "timeout"}

_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}

# Interpreters that run whatever script arrives on stdin.
_INTERPRETERS = _SHELLS | {"python", "python3", "perl", "ruby", "node"}

# Programs that download a file, and the ways a shell can run their output
# without a pipe: bash -c "$(curl ...)", eval "$(curl ...)", sh <(curl ...).
_DOWNLOADERS = {"curl", "wget"}
_COMMAND_SUB = re.compile(r"^\$\((.*)\)$|^`(.*)`$", re.S)
_PROCESS_SUB = re.compile(r"^<\((.*)\)$", re.S)

# rsync options that delete files from the destination (and --del).
_RSYNC_DELETES = {"--delete", "--delete-before", "--delete-during", "--delete-delay",
                  "--delete-after", "--delete-excluded", "--delete-missing-args"}

# rm targets that match everything in a folder (rm *.log is deliberate, so
# it isn't flagged).
_EVERYTHING_GLOBS = {"*", ".*", "./*", "*.*"}

# Interpreters that run code given right on the command line, and the flag
# that introduces it: python3 -c '...', perl -e '...', node -e '...'.
_INLINE_CODE_FLAGS = {
    "python": ("-c",), "python3": ("-c",), "python2": ("-c",),
    "perl": ("-e", "-E"), "ruby": ("-e",), "node": ("-e", "--eval"),
    "php": ("-r",),
}

# Calls in that inline code that delete files.
_CODE_DELETES = re.compile(
    r"\bos\.(remove|unlink|rmdir|removedirs)\b|\brmtree\b|\.unlink\s*\("
    r"|\bunlink\b|\bremove_tree\b|\bFileUtils\.rm|\bFile\.delete\b"
    r"|\b(rmSync|rmdirSync|unlinkSync)\b|\bfs\.(rm|rmdir|unlink)\s*\(")

# A quoted string inside inline code, which might be a shell command
# (os.system("rm -rf ~")).
_CODE_STRING = re.compile(r"'([^']*)'|\"([^\"]*)\"")

# How deep to follow "bash -c '...'" / eval inside each other.
_MAX_NESTING = 3

_DISK_TOOLS = {"fdisk", "sfdisk", "gdisk", "sgdisk", "parted", "wipefs",
               "mkswap", "cfdisk"}

_POWER_TOOLS = {"shutdown", "reboot", "poweroff", "halt"}

# systemctl poweroff, systemctl isolate reboot.target and the like.
_SYSTEMCTL_POWER = {"poweroff", "reboot", "halt", "kexec", "soft-reboot", "suspend",
                    "hibernate", "hybrid-sleep", "suspend-then-hibernate"}
_POWER_TARGETS = {"poweroff.target", "reboot.target", "halt.target", "kexec.target",
                  "soft-reboot.target", "suspend.target", "hibernate.target"}

# pkill/killall options that take a value, and the ones that pick a user
# (pkill -u bob with no program name stops everything bob runs).
_KILL_VALUE_OPTS = {
    "pkill": {"-u", "-U", "-g", "-G", "-P", "-s", "-t", "-F", "--euid", "--uid",
              "--signal", "--pgroup", "--group", "--parent", "--session",
              "--terminal", "--pidfile", "--ns", "--nslist"},
    "killall": {"-u", "-s", "-o", "-y", "-n", "-Z", "--user", "--signal",
                "--older-than", "--younger-than", "--ns", "--context"},
}
_KILL_USER_OPTS = {"-u", "-U", "--euid", "--uid", "--user"}

_DISK_DEVICE = re.compile(r"^/dev/(sd[a-z]|nvme\d|hd[a-z]|vd[a-z]|mmcblk\d|xvd[a-z]|disk\d)")

# name(){ name|name& };name  -- works for any function name, not just ":".
_FORK_BOMB = re.compile(r"(\S+)\s*\(\)\s*\{[^}]*\1\s*\|\s*\1")

# Unquoted system-wide targets that are almost never what a beginner means.
_ROOT_TARGETS = {"/", "/*", "~", "~/", "$HOME", "/home", "/etc", "/usr",
                 "/bin", "/boot", "/var", "/lib"}

REASONS = {
    "rm_recursive": "deletes a folder and everything inside it, permanently (there's no trash bin)",
    "rm_root": "deletes files in a system-wide or home location",
    "mkfs": "formats a disk or partition, erasing everything on it",
    "disk_tool": "changes disk partitions, which can make data unreadable",
    "dd": "writes raw data to a file or device and can overwrite a whole disk",
    "disk_write": "writes directly to a disk device, destroying what's on it",
    "shred": "overwrites files so they can never be recovered",
    "chmod_recursive": "changes permissions on a folder and everything inside it",
    "chown_recursive": "changes the owner of a folder and everything inside it",
    "perm_root": "changes permissions or ownership on a system location",
    "find_delete": "deletes every file that matches the search",
    "pipe_to_shell": "runs a script it downloads or generates without letting you read it first",
    "fork_bomb": "is a 'fork bomb' that freezes the system by spawning processes forever",
    "git_reset_hard": "throws away your uncommitted changes in this git repo",
    "git_clean": "deletes untracked files from this git repo",
    "git_force_push": "overwrites history on the remote git repo",
    "power": "shuts down, restarts or puts the computer to sleep",
    "crontab_remove": "deletes all of your scheduled (cron) jobs",
    "dev_null_move": "moves files into /dev/null, which deletes them",
    "rm_all": "deletes every file in the folder",
    "rsync_delete": "deletes files in the destination folder that aren't in the source, so a wrong path can empty it",
    "kill_all": "stops every program you're running at once (every program on the computer, with sudo), losing unsaved work",
    "truncate": "empties the file, erasing everything that was in it",
    "mv_root": "moves a system-wide or home folder, which can break your system or make your files seem to vanish",
    "script_delete": "runs a small program that deletes files or folders",
}


def _tokenize(command: str) -> List[str]:
    """Split a command line into words and operators, respecting quotes.
    Falls back to a plain split on unbalanced quotes rather than failing."""
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return re.findall(r"[;&|<>]+|[^\s;&|<>]+", command)


def _segments(tokens: List[str]):
    """Yield (words, redirects, piped_into) for each simple command.
    `redirects` is a list of (operator, target) for output redirections,
    plus ("<", "<(...)") when stdin comes from a process substitution.
    `piped_into` is True when the previous separator was a pipe."""
    words, redirects = [], []
    piped = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _SEPARATORS:
            if words or redirects:
                yield words, redirects, piped
            words, redirects = [], []
            piped = tok in ("|", "|&")
        elif tok and set(tok) <= set("<>&") and ">" in tok:
            # Output redirection: remember where it points.
            if i + 1 < len(tokens):
                redirects.append((tok, tokens[i + 1]))
                i += 1
        elif tok == "<" and tokens[i + 1:i + 2] and tokens[i + 1].startswith("("):
            # <(curl x) is process substitution: one word, not a redirection.
            word, i = _process_sub(tokens, i)
            words.append(word)
        elif tok == "<" and tokens[i + 1:i + 2] == ["<"] and tokens[i + 2:i + 3]                 and tokens[i + 2].startswith("("):
            # bash < <(curl x): stdin comes from a process substitution.
            word, i = _process_sub(tokens, i + 1)
            redirects.append(("<", word))
        elif tok and set(tok) <= set("<"):
            i += 1  # input redirection: skip its target
        else:
            words.append(tok)
        i += 1
    if words or redirects:
        yield words, redirects, piped


def _process_sub(tokens: List[str], i: int):
    """Join the tokens of <(...) starting at tokens[i] == "<" into one word.
    Returns the word and the index of its last token."""
    j = i + 1
    while j < len(tokens) - 1 and not tokens[j].endswith(")"):
        j += 1
    return "<" + " ".join(tokens[i + 1:j + 1]), j


def _strip_wrappers(words: List[str]) -> List[str]:
    """Drop `sudo`, `env FOO=bar`, `timeout 5` and the like so we look at the
    command that actually runs."""
    words = list(words)
    while words:
        first = os.path.basename(words[0])
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
        elif first in _WRAPPERS:
            words.pop(0)
            # Skip the wrapper's own options (sudo -u root, timeout 5, nice -n 10).
            while words and (words[0].startswith("-") or words[0].isdigit()):
                opt = words.pop(0)
                if opt in ("-u", "-g", "-n", "-c", "-s") and words:
                    words.pop(0)
        else:
            break
    return words


def _short_flags(args: List[str]) -> str:
    """All single-letter flags, e.g. ['-rf', '-v'] -> 'rfv'."""
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def _truncates_to_zero(args: List[str]) -> bool:
    """truncate -s 0 / -s0 / --size=0 / --size 0"""
    for i, a in enumerate(args):
        if a in ("-s0", "--size=0"):
            return True
        if a in ("-s", "--size") and args[i + 1:i + 2] == ["0"]:
            return True
    return False


def _check_segment(words: List[str], redirects, piped: bool, depth: int,
                   variables=None) -> List[str]:
    found = []
    for _op, target in redirects:
        if _DISK_DEVICE.match(target):
            found.append("disk_write")

    words = _expand_command_name(_strip_wrappers(words), variables or {})
    # "> notes.txt" or ": > notes.txt" with nothing else empties the file.
    # ("echo hi > out.txt" is normal use and isn't flagged.)
    if (not words or words == [":"]) and any(
            op in (">", ">|", "&>") and not _DISK_DEVICE.match(t) for op, t in redirects):
        found.append("truncate")
    if not words:
        return found
    name = os.path.basename(words[0])
    args = words[1:]
    flags = _short_flags(args)
    long_flags = {a.split("=")[0] for a in args if a.startswith("--")}
    positional = [a for a in args if not a.startswith("-")]

    stdin_download = any(op == "<" and _is_download(t, _PROCESS_SUB) for op, t in redirects)
    if (piped or stdin_download) and name in _INTERPRETERS and (
            not [p for p in positional if p != "-"] or (name in _SHELLS and "s" in flags)):
        found.append("pipe_to_shell")

    # Commands hidden in a string: bash -c '...', su -c '...', eval ...
    inner = None
    if name in _SHELLS | {"su"} and "c" in flags and positional:
        inner = _rejoin_substitution(args, args.index(positional[0]))
    elif name == "eval" and args:
        inner = " ".join(args)
    # A download run as it arrives, without a pipe.
    if (inner and _is_download(inner, _COMMAND_SUB)) or (
            not inner and name in _SHELLS | {"source", "."} and positional
            and _is_download(positional[0], _PROCESS_SUB)):
        found.append("pipe_to_shell")
    if inner and depth < _MAX_NESTING:
        found.extend(_check_keys(inner, depth + 1))

    if name == "rm":
        if "r" in flags or "R" in flags or "--recursive" in long_flags:
            found.append("rm_recursive")
        if any(p.rstrip("/") in {t.rstrip("/") for t in _ROOT_TARGETS} for p in positional):
            found.append("rm_root")
        if "--no-preserve-root" in long_flags:
            found.append("rm_root")
        if any(p in _EVERYTHING_GLOBS or p.endswith("/*") for p in positional):
            found.append("rm_all")
    elif name.startswith("mkfs"):
        found.append("mkfs")
    elif name in _DISK_TOOLS:
        found.append("disk_tool")
    elif name == "dd" and any(a.startswith("of=") for a in args):
        target = next(a[3:] for a in args if a.startswith("of="))
        found.append("disk_write" if _DISK_DEVICE.match(target) else "dd")
    elif name == "cp" and len(positional) >= 2 and _DISK_DEVICE.match(positional[-1]):
        found.append("disk_write")
    elif name == "cp" and len(positional) == 2 and positional[0] == "/dev/null"             and positional[1] != "/dev/null" and not positional[1].endswith("/"):
        found.append("truncate")
    elif name == "rsync" and any(a == "--del" or a.split("=")[0] in _RSYNC_DELETES
                                 for a in args):
        found.append("rsync_delete")
    elif name == "tee" and any(_DISK_DEVICE.match(p) for p in positional):
        found.append("disk_write")
    elif name == "truncate" and _truncates_to_zero(args):
        found.append("truncate")
    elif name == "shred":
        found.append("shred")
    elif name in ("chmod", "chown", "chgrp"):
        if "R" in flags or "--recursive" in long_flags:
            found.append("chmod_recursive" if name == "chmod" else "chown_recursive")
        elif any(p in _ROOT_TARGETS for p in positional):
            found.append("perm_root")
    elif name == "find":
        if "-delete" in args or ("-exec" in args and any(
                os.path.basename(a) == "rm" for a in args)):
            found.append("find_delete")
    elif name == "git" and args:
        sub = args[0]
        if sub == "reset" and "--hard" in args:
            found.append("git_reset_hard")
        elif sub == "clean" and ("f" in flags or "--force" in long_flags):
            found.append("git_clean")
        elif sub == "push" and ("f" in flags or "--force" in long_flags
                                or "--force-with-lease" in long_flags):
            found.append("git_force_push")
    elif name in _POWER_TOOLS or (name == "init" and positional[:1] in (["0"], ["6"])):
        found.append("power")
    elif name == "systemctl" and positional and (
            positional[0] in _SYSTEMCTL_POWER
            or (positional[0] in ("start", "isolate") and positional[1:2]
                and positional[1] in _POWER_TARGETS)):
        found.append("power")
    elif (name == "kill" and _kills_everything(args)) or (
            name in ("pkill", "killall") and _kills_all_of_a_user(name, args)):
        found.append("kill_all")
    elif name == "crontab" and "r" in flags:
        found.append("crontab_remove")
    elif name == "mv" and positional:
        if positional[-1] == "/dev/null":
            found.append("dev_null_move")
        elif any(p.rstrip("/") in {t.rstrip("/") for t in _ROOT_TARGETS}
                 for p in positional[:-1]):
            found.append("mv_root")
    elif name in _INLINE_CODE_FLAGS:
        code = _inline_code(args, _INLINE_CODE_FLAGS[name])
        if code is not None:
            if _CODE_DELETES.search(code):
                found.append("script_delete")
            if depth < _MAX_NESTING:
                for m in _CODE_STRING.finditer(code):
                    found.extend(_check_keys(m.group(1) or m.group(2) or "", depth + 1))
    return found


def _is_download(text: str, pattern) -> bool:
    """True when `text` is nothing but $(...), `...` or <(...) (as `pattern`
    says) around curl or wget. "echo $(curl x)" isn't: that only shows it."""
    m = pattern.match(text.strip())
    if not m:
        return False
    inner = next(g for g in m.groups() if g is not None)
    first = next(_segments(_tokenize(inner)), None)
    words = _strip_wrappers(first[0]) if first else []
    return bool(words) and os.path.basename(words[0]) in _DOWNLOADERS


def _rejoin_substitution(args: List[str], start: int) -> str:
    """An unquoted $(curl -s x) arrives as several words; join them back so
    bash -c $(curl -s x) is read like bash -c "$(curl -s x)"."""
    word = args[start]
    if word.startswith("$(") and not word.endswith(")"):
        end = ")"
    elif word.startswith("`") and (len(word) == 1 or not word.endswith("`")):
        end = "`"
    else:
        return word
    for j in range(start + 1, len(args)):
        if args[j].endswith(end):
            return " ".join(args[start:j + 1])
    return word


def _kills_everything(args: List[str]) -> bool:
    """kill -9 -1: -1 as the process ID means every process you can reach.
    A leading -9, -KILL or -s KILL is the signal ("kill -1" alone isn't)."""
    i = 0
    if args[:1] and args[0] in ("-s", "-n", "--signal"):
        i = 2
    elif args[:1] and args[0].startswith("-") and args[0] != "--":
        i = 1
    if args[i:i + 1] == ["--"]:
        i += 1
    return "-1" in args[i:]


def _kills_all_of_a_user(name: str, args: List[str]) -> bool:
    """pkill -u bob / killall -u bob with no program name stops everything
    that user runs (with your own name, it logs you out)."""
    user, names, i = False, [], 0
    while i < len(args):
        a = args[i]
        opt = a.split("=")[0]
        if opt in _KILL_USER_OPTS or (a[:2] in ("-u", "-U") and len(a) > 2):
            user = True
        if a in _KILL_VALUE_OPTS[name]:
            i += 1  # skip its value
        elif not a.startswith("-"):
            names.append(a)
        i += 1
    return user and not names


def _inline_code(args: List[str], code_flags) -> Optional[str]:
    """The code after -c / -e (also joined forms like -c'...'), or None."""
    for i, a in enumerate(args):
        if a in code_flags:
            return args[i + 1] if i + 1 < len(args) else None
        for f in code_flags:
            if len(f) == 2 and a.startswith(f) and len(a) > 2:
                return a[2:]
    return None


_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
_VAR_REF = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")


def _expand_command_name(words: List[str], variables) -> List[str]:
    """`x=rm; $x -rf /` hides the command in a variable. If the first word is
    a variable set earlier on the same line, put its value back."""
    if not words:
        return words
    m = _VAR_REF.match(words[0])
    if m:
        value = variables.get(m.group(1) or m.group(2))
        if value:
            try:
                return shlex.split(value) + words[1:]
            except ValueError:
                return value.split() + words[1:]
    return words


def _check_keys(command: str, depth: int = 0) -> List[str]:
    keys: List[str] = []
    if ":(){" in command.replace(" ", "") or _FORK_BOMB.search(command):
        keys.append("fork_bomb")
    variables = {}
    for words, redirects, piped in _segments(_tokenize(command)):
        assignments = [_ASSIGNMENT.match(w) for w in words]
        if words and all(assignments) and not redirects:
            # "x=rm" on its own just sets a variable for later commands.
            variables.update((m.group(1), m.group(2)) for m in assignments)
            continue
        keys.extend(_check_segment(words, redirects, piped, depth, variables))
    return keys


def check_command(command: str) -> List[str]:
    """Return a list of plain-English reasons this command looks dangerous.
    An empty list means nothing risky was recognised."""
    if not command or not command.strip():
        return []
    # De-duplicate, keeping order.
    seen, reasons = set(), []
    for k in _check_keys(command):
        if k not in seen:
            seen.add(k)
            reasons.append(REASONS[k])
    return reasons
