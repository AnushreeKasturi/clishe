"""
`clishe doctor`: check everything that commonly goes wrong, and say how to
fix it in plain English. Each check is (status, title, detail, fix):

    ok    - fine
    note  - worth knowing, nothing is broken
    fail  - a real problem; `clishe doctor` exits with 1

Nothing here changes anything; the fixes are suggestions.
"""
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List, NamedTuple

KNOWN_SETTINGS = {"provider_priority", "allow_remote_ai", "trash", "ollama", "local",
                  "anthropic", "learn_mode", "plain"}
RC_FILES = {"bash": "~/.bashrc", "zsh": "~/.zshrc"}


class Check(NamedTuple):
    status: str
    title: str
    detail: str = ""
    fix: str = ""


def python() -> Check:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < (3, 9):
        return Check("fail", f"Python {version} is too old", "Clishe needs Python 3.9 or newer.",
                     "Install a newer python3 with your package manager.")
    return Check("ok", f"Python {version}")


def bash(version: str) -> Check:
    if not version:
        return Check("note", "Couldn't tell the bash version")
    return Check("ok", f"bash {version.split('(')[0]}")


def on_path(found: str) -> Check:
    if found:
        return Check("ok", "clishe is on your PATH", found)
    return Check("note", "clishe isn't on your PATH",
                 "You can only start it by its full path.",
                 'Add this to your shell\'s startup file: export PATH="$HOME/.local/bin:$PATH"')


def shortcut(shell_path: str, home: str) -> Check:
    shell = os.path.basename(shell_path or "")
    if shell not in RC_FILES:
        return Check("note", f"Ctrl+G shortcut: not available for {shell or 'your shell'} yet",
                     "It works in bash and zsh.")
    rc = RC_FILES[shell]
    try:
        text = Path(rc.replace("~", home, 1)).read_text(errors="replace")
    except OSError:
        text = ""
    if "clishe --init" in text:
        return Check("ok", f"Ctrl+G shortcut is set up in {rc}")
    return Check("note", "Ctrl+G shortcut isn't set up",
                 "Type plain English at your normal prompt and press Ctrl+G to turn it into a command.",
                 f'Add this line to {rc}, then open a new terminal: eval "$(clishe --init {shell})"')


def config_file(path: Path) -> List[Check]:
    if not path.exists():
        return [Check("ok", "No config file yet", "Clishe uses its defaults.")]
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        return [Check("fail", "The config file isn't valid JSON", f"{path}: {e}",
                      f"Fix that line, or delete {path} to go back to the defaults.")]
    except OSError as e:
        return [Check("fail", "Can't read the config file", f"{path}: {e}")]
    if not isinstance(data, dict):
        return [Check("fail", "The config file should hold one JSON object", str(path),
                      f"Delete {path} to go back to the defaults.")]
    checks = [Check("ok", "Config file is valid", str(path))]
    unknown = sorted(set(data) - KNOWN_SETTINGS)
    if unknown:
        checks.append(Check("note", f"Unknown setting{'s' * (len(unknown) > 1)} in the config: "
                            + ", ".join(unknown),
                            "Clishe ignores these. A typo?",
                            "Known settings: " + ", ".join(sorted(KNOWN_SETTINGS))))
    return checks


def data_folder(path: Path) -> Check:
    # Clishe creates this folder (and any missing parents) the first time it
    # has something to save, so a folder that isn't there yet is only a
    # problem if we couldn't create it: what matters is whether the nearest
    # folder above it that does exist is writable.
    if path.is_dir():
        if os.access(path, os.W_OK):
            return Check("ok", "Data folder is writable", str(path))
        return Check("fail", "Can't write to the data folder", str(path),
                     "Clishe can't save what you teach it. Check the folder's owner and permissions.")
    ancestor = path.parent
    while not ancestor.is_dir() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    if os.access(ancestor, os.W_OK):
        return Check("note", "Data folder not created yet", str(path),
                     "Clishe will create it the first time it saves something.")
    return Check("fail", "Can't write to the data folder", str(path),
                 "Clishe can't save what you teach it, and can't create the folder "
                 "either. Check the permissions of " + str(ancestor) + ".")


def manual_pages() -> Check:
    if shutil.which("man"):
        return Check("ok", "man pages are available", "explain can read your system's own manual.")
    return Check("note", "No man command", "explain still works from Clishe's own data.",
                 "Install it for more detail, e.g. sudo apt install man-db")


def trash() -> Check:
    from clishe_brain import _trash_tool
    tool = _trash_tool()
    if tool:
        back = ("you can put them back from Finder" if sys.platform == "darwin"
                else "'undo that' can bring them back")
        return Check("ok", f"Trash: {tool[0][0]}", f"Deleted files can go to the Trash, and {back}.")
    return Check("note", "No Trash tool",
                 "rm deletes for good, and 'undo that' can't bring files back.",
                 "Install trash-cli with your package manager (e.g. sudo apt install trash-cli)")


def ai(config: dict) -> List[Check]:
    import setup_check
    from providers import opted_in
    from providers.base import is_local_address
    checks = []
    result = setup_check.check()
    configured = result["configured_model"]
    if result["ollama_running"]:
        if configured and not setup_check._has_model(result["ollama_models"], configured):
            checks.append(Check("note", f"Ollama is running, but the model {configured} isn't downloaded",
                                "Phrases Clishe doesn't know can't be answered by AI until it is.",
                                f"ollama pull {configured}   (or run: clishe setup)"))
        else:
            checks.append(Check("ok", f"Local AI: Ollama with {configured or 'its default model'}"))
    for host in result["other_servers"]:
        checks.append(Check("ok", f"Local AI server at {host}"))
    if not checks:
        checks.append(Check("note", "No local AI running",
                            "Clishe works fine without one; AI only answers what it doesn't know.",
                            "To add one: clishe setup"))
    host = (config.get("ollama") or {}).get("host", "") if isinstance(config.get("ollama"), dict) else ""
    if host and not config.get("allow_remote_ai") and not is_local_address(host):
        checks.append(Check("fail", "The Ollama host isn't on this computer or network",
                            f"{host} is refused, so nothing is sent there.",
                            'Fix the host, or set "allow_remote_ai": true if you mean it.'))
    anthropic = config.get("anthropic") if isinstance(config.get("anthropic"), dict) else {}
    if opted_in(anthropic):
        if not (anthropic.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")):
            checks.append(Check("fail", "Cloud AI is turned on, but there's no API key",
                                "", "Set ANTHROPIC_API_KEY, or turn it off with \"enabled\": false."))
        else:
            checks.append(Check("note", "Cloud AI (Anthropic) is on",
                                "Phrases no local source can answer may be sent over the internet.",
                                'Turn it off with "enabled": false under "anthropic" in the config.'))
    else:
        checks.append(Check("ok", "Local only: nothing you type is sent to the internet"))
    return checks


def tldr_data() -> Check:
    import tldr
    data = tldr._data()
    if data.get("common"):
        pages = sum(len(data.get(platform, {})) for platform in tldr._platforms())
        return Check("ok", f"Command examples: tldr-pages {data.get('version', '')}",
                     f"{pages} pages, offline.")
    return Check("fail", "The bundled command examples are missing", str(tldr.DATA),
                 "Reinstall Clishe: pipx reinstall clishe")


def system() -> Check:
    from config import detect_distro, detect_distro_family
    from knowledge import _installer
    manager = _installer(detect_distro_family())[0]
    distro = detect_distro()
    name = "macOS" if distro == "macos" else distro
    return Check("ok" if manager else "note", f"System: {name}",
                 f"Package manager: {manager}" if manager else
                 "Install hints won't know your package manager.")


def run(bash_version: str = "", clishe_path: str = "", shell: str = "",
        home: str = "") -> List[Check]:
    from config import CONFIG_FILE, load_config
    from clishe_brain import DATA_DIR
    home = home or str(Path.home())
    try:
        config = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        config = config if isinstance(config, dict) else {}
    except (OSError, ValueError):
        config = {}
    checks = [python(), bash(bash_version), on_path(clishe_path), shortcut(shell, home), system()]
    checks += config_file(CONFIG_FILE)
    checks += [data_folder(DATA_DIR), tldr_data(), manual_pages(), trash()]
    checks += ai({**load_config(), **config})
    return checks
