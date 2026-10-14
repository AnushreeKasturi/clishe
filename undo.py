"""
"undo that": reverse the last change a command made, where that can be
done safely.

Before a command runs, `before()` notes what's there (does the target
exist? what were the permissions? what's in the Trash?). After it
succeeds, `after()` turns that into an undo record. `plan()` checks the
record still holds - nothing has been changed since - and returns the
shell commands that reverse it, so people see (and learn) exactly what
undo does. Nothing is ever undone without the user saying yes.

    mv a b         -> mv b a             (if nothing is in a's place now)
    mkdir x        -> rmdir x            (only while it's empty)
    touch f        -> rm f               (only while it's still empty)
    cp a b         -> moves the copy to the Trash, or removes it
                      (only if it hasn't changed since)
    chmod 600 f    -> chmod <old mode> f
    cd somewhere   -> cd back
    trash / gio trash / trash-put -> moved back out of the Trash
    apt install x  -> suggests: sudo apt remove x
    rm f           -> can't be undone; says so
"""
import glob
import os
import shlex
import stat
from pathlib import Path
from typing import List, Optional

MAX_RECORDS = 10

# Commands worth taking a "before" note for (clishe.sh checks this list
# first, so other commands cost nothing).
UNDOABLE = {"mv", "cp", "mkdir", "touch", "chmod", "cd", "rm", "trash", "trash-put",
            "gio", "apt", "apt-get", "dnf", "pacman", "zypper", "brew", "snap", "flatpak"}

_REMOVE_FOR = {"apt": "sudo apt remove {}", "apt-get": "sudo apt-get remove {}",
               "dnf": "sudo dnf remove {}", "pacman": "sudo pacman -R {}",
               "zypper": "sudo zypper remove {}", "brew": "brew uninstall {}",
               "snap": "sudo snap remove {}", "flatpak": "flatpak uninstall {}"}
_INSTALL_WORDS = {"install", "-S", "add", "in"}


def _q(path: str) -> str:
    """A path for a command shown to the user: relative when it's inside the
    current folder (easier to read), absolute otherwise, and quoted."""
    here = os.path.realpath(os.getcwd())
    real = os.path.realpath(path)
    if real.startswith(here + os.sep):
        path = os.path.relpath(real, here)
    if path.startswith("-"):
        path = "./" + path  # so it can't be read as an option
    return shlex.quote(path)


def _words(command: str) -> Optional[List[str]]:
    """Words of a simple command, or None for pipes, chains, redirects and
    substitutions, whose effects can't be worked out reliably."""
    if any(c in command for c in ";&|<>`") or "$(" in command:
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return words or None


def _expand(args: List[str], cwd: str) -> List[str]:
    """Absolute paths for the arguments, with * and ? patterns expanded."""
    paths = []
    for arg in args:
        full = os.path.join(cwd, os.path.expanduser(arg))
        matches = sorted(glob.glob(full)) if any(c in arg for c in "*?[") else [full]
        paths.extend(os.path.normpath(m) for m in matches)
    return paths


def _positional(args: List[str]) -> List[str]:
    out, flags_done = [], False
    for a in args:
        if not flags_done and a == "--":
            flags_done = True
        elif not flags_done and a.startswith("-") and a != "-":
            continue
        else:
            out.append(a)
    return out


def _trash_listing(home: str) -> dict:
    """What's in the Trash now: the freedesktop Trash (gio, trash-cli) keeps
    an .trashinfo file per item; macOS keeps items in ~/.Trash."""
    xdg = Path(os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))) / "Trash"
    listing = {"xdg": sorted(p.name for p in (xdg / "info").glob("*.trashinfo")),
               "mac": []}
    mac = Path(home) / ".Trash"
    try:
        listing["mac"] = sorted(os.listdir(mac))
    except PermissionError:
        listing["mac"] = None  # macOS hides the Trash from terminal programs
    except OSError:
        pass
    return listing


def before(command: str, cwd: str, home: Optional[str] = None) -> Optional[dict]:
    """A note of what the command is about to change, or None if it's not
    something undo knows."""
    words = _words(command)
    if not words:
        return None
    sudo = words[0] == "sudo"
    if sudo:
        words = words[1:]
    if not words:
        return None
    name, args = words[0], words[1:]
    home = home or os.path.expanduser("~")
    note = {"command": command, "kind": name, "cwd": cwd}

    if name in _REMOVE_FOR and args[:1] and args[0] in _INSTALL_WORDS:
        note["packages"] = [a for a in args[1:] if not a.startswith("-")]
        return note if note["packages"] else None
    if sudo:
        return None  # system files: too much at stake to guess
    paths = _positional(args)

    if name in ("mv", "cp"):
        if len(paths) < 2:
            return None
        sources, dest = _expand(paths[:-1], cwd), _expand(paths[-1:], cwd)[0]
        into_dir = os.path.isdir(dest)
        if len(sources) > 1 and not into_dir:
            return None
        finals = [os.path.join(dest, os.path.basename(s)) if into_dir else dest for s in sources]
        note.update(pairs=[[s, f, os.path.lexists(f)] for s, f in zip(sources, finals)])
    elif name == "mkdir":
        created = []
        for target in _expand(paths, cwd):
            chain = []
            while target and not os.path.exists(target):
                chain.append(target)
                parent = os.path.dirname(target)
                if parent == target or "-p" not in args and "--parents" not in args:
                    break
                target = parent
            created.extend(reversed(chain))
        note["paths"] = created
    elif name == "touch":
        note["paths"] = [p for p in _expand(paths, cwd) if not os.path.exists(p)]
    elif name == "chmod":
        if any(a in ("-R", "--recursive") for a in args) or len(paths) < 2:
            return None
        note["modes"] = [[p, stat.S_IMODE(os.stat(p).st_mode)]
                         for p in _expand(paths[1:], cwd) if os.path.exists(p)]
    elif name == "cd":
        pass
    elif name in ("trash", "trash-put") or (name == "gio" and args[:1] == ["trash"]):
        targets = paths[1:] if name == "gio" else paths
        note.update(kind="trash", targets=_expand(targets, cwd), trash=_trash_listing(home),
                    home=home)
    elif name == "rm":
        note["paths"] = _expand(paths, cwd)
    else:
        return None
    return note


def _trashinfo_path(info_file: Path) -> str:
    from urllib.parse import unquote
    try:
        for line in info_file.read_text(errors="replace").splitlines():
            if line.startswith("Path="):
                return unquote(line[5:])
    except OSError:
        pass
    return ""


def after(note: dict, cwd_after: str) -> Optional[dict]:
    """The undo record for a command that just succeeded, or None."""
    kind = note["kind"]
    record = {"command": note["command"], "kind": kind}
    if "packages" in note:
        record.update(kind="install", manager=kind, packages=note["packages"])
    elif kind in ("mv", "cp"):
        pairs = []
        for source, final, existed in note["pairs"]:
            if existed:
                record["replaced"] = True  # what was there before is gone
                continue
            if not os.path.lexists(final):
                continue
            if kind == "mv" and not os.path.lexists(source):
                pairs.append([source, final])
            elif kind == "cp":
                info = os.stat(final)
                pairs.append([final, info.st_mtime, os.path.isdir(final)])
        record["pairs"] = pairs
        if not pairs and not record.get("replaced"):
            return None
    elif kind in ("mkdir", "touch"):
        record["paths"] = [p for p in note["paths"] if os.path.exists(p)]
        if not record["paths"]:
            return None
    elif kind == "chmod":
        record["modes"] = note["modes"]
    elif kind == "cd":
        if os.path.realpath(note["cwd"]) == os.path.realpath(cwd_after):
            return None
        record["from"] = note["cwd"]
    elif kind == "trash":
        record["items"] = _new_trash_items(note)
        if not record["items"]:
            record["kind"] = "trash-unknown"
            record["mac_hidden"] = note["trash"]["mac"] is None
            record["names"] = [os.path.basename(t) for t in note["targets"]]
    elif kind == "rm":
        record["paths"] = note["paths"]
    return record


def _new_trash_items(note: dict) -> List[List[str]]:
    """[trashed file, its .trashinfo (or ""), original path] for each target."""
    home, old = note["home"], note["trash"]
    xdg = Path(os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))) / "Trash"
    targets, items = set(note["targets"]), []
    for info in sorted((xdg / "info").glob("*.trashinfo")):
        if info.name in old["xdg"]:
            continue
        original = _trashinfo_path(info)
        if original in targets:
            items.append([str(xdg / "files" / info.name[:-len(".trashinfo")]), str(info), original])
    mac = Path(home) / ".Trash"
    try:
        new_mac = [n for n in os.listdir(mac) if n not in (old["mac"] or [])]
    except OSError:
        new_mac = []
    for target in note["targets"]:
        base = os.path.basename(target)
        match = next((n for n in new_mac if n == base or n.startswith(os.path.splitext(base)[0])), None)
        if match and not any(i[2] == target for i in items):
            items.append([str(mac / match), "", target])
    return items


# ---------- the stack of undo records ----------

def load(path: Path) -> list:
    import json
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(path: Path, records: list):
    import json
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(records[-MAX_RECORDS:], f)
        tmp.replace(path)
    except OSError:
        pass


# ---------- turning a record into commands ----------

def plan(record: dict) -> dict:
    """{"status": "ok", "explanation", "commands": [...]} to undo `record`,
    or {"status": "impossible", "explanation"} when it can't be done safely."""
    kind = record["kind"]

    def no(text):
        return {"status": "impossible", "explanation": text}

    if kind == "rm":
        return no("rm deletes for good, so that can't be undone. Next time, say yes "
                  "when I offer the Trash, and you'll be able to get files back.")
    if kind == "trash-unknown":
        names = ", ".join(record.get("names", [])) or "the files"
        if record.get("mac_hidden"):
            return no(f"macOS doesn't let terminal programs look inside the Trash, so I can't "
                      f"bring back {names} myself. Open the Trash in the Dock, right-click "
                      f"{names} and choose Put Back: it goes back exactly where it was.")
        return no(f"I couldn't find {names} in the Trash. Open the Trash in your file "
                  "manager and restore it from there.")
    if kind == "install":
        names = " ".join(record["packages"])
        return {"status": "ok", "commands": [_REMOVE_FOR[record["manager"]].format(names)],
                "explanation": f"This removes {names} again. (Anything installed alongside "
                               "it may stay; that's normal and harmless.)"}
    if kind == "cd":
        if not os.path.isdir(record["from"]):
            return no(f"{record['from']} doesn't exist any more.")
        return {"status": "ok", "commands": [f"cd {_q(record['from'])}"],
                "explanation": "This goes back to the folder you were in."}

    commands, problems = [], []
    if kind == "mv":
        for source, final in record["pairs"]:
            if not os.path.lexists(final):
                problems.append(f"{final} isn't there any more")
            elif os.path.lexists(source):
                problems.append(f"something new is at {source}")
            else:
                commands.append(f"mv {_q(final)} {_q(source)}")
        explanation = "This moves it back where it was."
    elif kind == "cp":
        trash = _trash_command()
        for final, mtime, is_dir in record["pairs"]:
            if not os.path.lexists(final):
                continue
            if abs(os.stat(final).st_mtime - mtime) > 1:
                problems.append(f"{final} has changed since it was copied")
            elif trash:
                commands.append(f"{trash} {_q(final)}")
            else:
                commands.append(f"rm {'-r ' if is_dir else ''}{_q(final)}")
        explanation = ("This moves the copy to the Trash." if trash
                       else "This removes the copy. The original isn't touched.")
    elif kind == "mkdir":
        removing = set()
        for path in reversed(record["paths"]):  # deepest first
            if not os.path.isdir(path):
                continue
            # Empty once the folders removed before it are gone.
            leftovers = [e for e in os.listdir(path) if os.path.join(path, e) not in removing]
            if leftovers:
                problems.append(f"{path} isn't empty any more")
                break  # its parents can't be empty either
            commands.append(f"rmdir {_q(path)}")
            removing.add(path)
        explanation = "rmdir removes a folder only while it's empty, so nothing else can be lost."
    elif kind == "touch":
        for path in record["paths"]:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                problems.append(f"{path} has something in it now")
            elif os.path.isfile(path):
                commands.append(f"rm {_q(path)}")
        explanation = "This removes the empty file it created."
    elif kind == "chmod":
        for path, mode in record["modes"]:
            if os.path.exists(path):
                commands.append(f"chmod {mode:o} {_q(path)}")
        explanation = "This puts the permissions back the way they were."
    elif kind == "trash":
        for trashed, info, original in record["items"]:
            if not os.path.lexists(trashed):
                problems.append(f"{os.path.basename(original)} isn't in the Trash any more")
            elif os.path.lexists(original):
                problems.append(f"something new is at {original}")
            else:
                commands.append(f"mv {_q(trashed)} {_q(original)}"
                                + (f" && rm {_q(info)}" if info else ""))
        explanation = "This moves it back out of the Trash, to where it was."
    else:
        return no("I don't know how to undo that.")

    if record.get("replaced"):
        problems.append("it replaced a file that was already there, and that one can't be brought back")
    if problems and not commands:
        return no("I can't undo that safely: " + "; ".join(problems) + ".")
    if problems:
        explanation += " (Not everything: " + "; ".join(problems) + ".)"
    if not commands:
        return no("There's nothing left to undo.")
    return {"status": "ok", "commands": commands, "explanation": explanation}


def _trash_command() -> str:
    import shutil
    import sys
    if sys.platform == "darwin" and shutil.which("trash"):
        return "trash"
    if shutil.which("gio"):
        return "gio trash"
    if shutil.which("trash-put"):
        return "trash-put"
    if shutil.which("trash"):
        return "trash"
    return ""
