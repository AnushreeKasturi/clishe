"""
`clishe check`: "is this safe to run?" for a command or a script someone
found online. It never runs anything. It says what the command would do:
what it changes, whether it uses the internet or admin rights, whether it
installs software, and any risky patterns the safety check knows - with a
safer way to do it when there is one.

    clishe check 'curl -fsSL https://get.example.com | sudo bash'
    clishe check install.sh
"""
import os
import re
from typing import List, Optional
from urllib.parse import urlparse

from safety import _segments, _strip_wrappers, _tokenize, check_command

MAX_SCRIPT_BYTES = 200_000
MAX_LINES_SHOWN = 40

_URL = re.compile(r"https?://[^\s'\"|;&)]+")
_NETWORK = {"curl", "wget", "ssh", "scp", "rsync", "ftp", "sftp", "nc", "telnet"}
_PACKAGE_INSTALL = {
    "apt": {"install", "upgrade", "full-upgrade", "dist-upgrade"},
    "apt-get": {"install", "upgrade", "dist-upgrade"},
    "dnf": {"install", "upgrade"}, "yum": {"install", "update"},
    "pacman": {"-S", "-Syu", "-U"}, "zypper": {"install", "in", "update"},
    "apk": {"add", "upgrade"}, "brew": {"install", "upgrade"},
    "snap": {"install"}, "flatpak": {"install"},
    "pip": {"install"}, "pip3": {"install"}, "pipx": {"install"},
    "npm": {"install", "i"}, "cargo": {"install"}, "gem": {"install"},
}
_REMOVE = {"rm", "rmdir", "shred", "unlink"}
_WRITE = {"cp", "mv", "mkdir", "touch", "ln", "tee", "install", "rsync", "dd",
          "chmod", "chown", "chgrp", "unzip", "truncate", "sed"}
_EXTRACT = {"tar": "x", "unzip": ""}
_SERVICES = {"systemctl", "service", "crontab", "useradd", "usermod", "userdel",
             "passwd", "mount", "umount", "ufw", "iptables", "reboot", "shutdown"}


def _hosts(text: str) -> List[str]:
    hosts = []
    for url in _URL.findall(text):
        host = urlparse(url).hostname
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _targets(args: List[str]) -> List[str]:
    return [a for a in args if not a.startswith("-")]


def _facts(command: str) -> dict:
    """What a command line touches, as data (see describe() for the words)."""
    facts = {"sudo": False, "network": False, "hosts": _hosts(command), "installs": [],
             "removed": [], "changed": [], "services": []}
    for words, redirects, piped in _segments(_tokenize(command)):
        if words and words[0] in ("sudo", "doas"):
            facts["sudo"] = True
        for op, target in redirects:
            # ">&2", "2>&1" and /dev/null only move output around; "< <(...)" is input.
            if op == "<" or target == "/dev/null" or target.isdigit() or target.startswith("&") or op.endswith("&"):
                continue
            facts["changed"].append(f"{target} ({'adds to it' if op == '>>' else 'replaces it'})")
        words = _strip_wrappers(words)
        if not words:
            continue
        name, args = os.path.basename(words[0]), words[1:]
        targets = _targets(args)
        if name in _NETWORK or (name == "git" and args[:1] in (["clone"], ["pull"], ["push"])):
            facts["network"] = True
        if name in _PACKAGE_INSTALL and any(a in _PACKAGE_INSTALL[name] for a in args[:2]):
            pkgs = [a for a in args[1:] if not a.startswith("-")]
            facts["installs"].append(f"{name}: {' '.join(pkgs) or 'updates'}")
        elif name in _REMOVE:
            facts["removed"].extend(targets or ["(nothing named)"])
        elif name in _WRITE and not (name == "sed" and "-i" not in args):
            if name in ("cp", "mv", "ln", "install", "rsync"):
                targets = targets[-1:]       # the destination
            elif name in ("sed", "chmod", "chown", "chgrp"):
                targets = targets[1:]        # skip the expression, mode or owner
            facts["changed"].extend(targets)
        elif name == "tar" and "x" in "".join(a.lstrip("-") for a in args[:1]):
            facts["changed"].append("files unpacked from the archive")
        elif name in _SERVICES:
            facts["services"].append(" ".join([name] + args[:2]))
    return facts


def _merge(all_facts: List[dict]) -> dict:
    merged = {"sudo": False, "network": False, "hosts": [], "installs": [],
              "removed": [], "changed": [], "services": []}
    for facts in all_facts:
        for key, value in facts.items():
            if isinstance(value, bool):
                merged[key] = merged[key] or value
            else:
                merged[key].extend(v for v in value if v not in merged[key])
    return merged


def describe(facts: dict) -> List[str]:
    """The facts in plain English, most important first."""
    effects = []
    if facts["sudo"]:
        effects.append("Runs as the administrator (sudo), so it can change anything on "
                       "this computer.")
    if facts["network"] or facts["hosts"]:
        where = f": {', '.join(facts['hosts'])}" if facts["hosts"] else ""
        effects.append(f"Uses the internet{where}.")
    if facts["installs"]:
        effects.append("Installs or updates software (downloaded from the internet): "
                       + "; ".join(facts["installs"]) + ".")
    if facts["removed"]:
        effects.append("Deletes: " + ", ".join(facts["removed"]) + ".")
    if facts["changed"]:
        effects.append("Creates or changes: " + ", ".join(dict.fromkeys(facts["changed"])) + ".")
    if facts["services"]:
        effects.append("Changes how the system runs: " + ", ".join(facts["services"]) + ".")
    return effects or ["Only reads or shows things. It doesn't change any files."]


def inspect(command: str) -> dict:
    """What one command line would do. Returns
    {"command", "warnings": [...], "effects": [...], "safer": [steps], "facts"}."""
    warnings = check_command(command)
    facts = _facts(command)
    safer = []
    if any("runs a script it downloads" in w for w in warnings) and facts["hosts"]:
        url = _URL.search(command).group(0)
        name = os.path.basename(urlparse(url).path) or "script.sh"
        safer = [f"curl -fsSL {url} -o {name}", f"less {name}", f"clishe check {name}"]
    return {"command": command, "warnings": warnings, "effects": describe(facts),
            "safer": safer, "facts": facts}


def script_lines(text: str) -> List[str]:
    """The commands in a script: comments and blank lines dropped,
    backslash-continued lines joined."""
    lines, current = [], ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if current:
            line = current + " " + line.lstrip()
            current = ""
        if line.endswith("\\"):
            current = line[:-1].rstrip()
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    if current.strip():
        lines.append(current.strip())
    return lines


def read_script(path: str) -> Optional[str]:
    """The text of a script file, or None if it isn't a readable text file."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_SCRIPT_BYTES:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def check_script(text: str) -> dict:
    """Every command in a script, plus one summary for the whole script."""
    results = [inspect(line) for line in script_lines(text)]
    return {"results": results, "risky": [r for r in results if r["warnings"]],
            "effects": describe(_merge([r["facts"] for r in results]))}
