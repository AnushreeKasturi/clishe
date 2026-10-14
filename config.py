"""
Config loading for clishe's AI providers.

Reads the XDG-compliant config file (~/.config/clishe/config.json by
default, or $XDG_CONFIG_HOME/clishe/config.json if set). If it doesn't
exist, writes sensible defaults so first-run users see exactly what to
fill in instead of hitting a wall of "provider not configured" errors
with no next step.

Also detects the running Linux distro from /etc/os-release so AI providers
can give distro-correct package-manager commands (apt vs dnf vs pacman)
instead of defaulting to one distro for everyone.
"""
import copy
import json
import os
import sys
from pathlib import Path

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR = XDG_CONFIG_HOME / "clishe"
# The directory is created when the config is first written, not on import:
# importing this module must not write anything to the user's HOME (the test
# suite imports it, and a `python -c "import config"` shouldn't litter either).
CONFIG_FILE = CONFIG_DIR / "config.json"

OS_RELEASE_FILE = Path('/etc/os-release')

# Local first: Ollama, then any OpenAI-style local server (llama.cpp, LM
# Studio, Jan...). The cloud provider is listed but off until "enabled": true.
DEFAULT_CONFIG = {
    "provider_priority": ["ollama", "local", "anthropic"],
    "allow_remote_ai": False,
    "trash": "ask",
    "ollama": {
        "host": "http://localhost:11434",
        "model": "llama3.2"
    },
    "local": {
        "host": "",
        "model": ""
    },
    "anthropic": {
        "enabled": False,
        "api_key": "",
        "model": "claude-haiku-5-5"
    }
}


def _migrate_legacy_config():
    """One-time migration from the old ~/.clishe_config.json location to the
    new XDG-compliant path, so upgrading doesn't silently lose an existing
    config (and any API key already saved in it). This only ever touches
    the config file - KB and history data migration lives in clishe_brain.py,
    which owns those files."""
    old_path = Path.home() / ".clishe_config.json"
    if old_path.exists() and not CONFIG_FILE.exists():
        try:
            old_path.rename(CONFIG_FILE)
            # It may hold an API key, and the old file was often world-readable.
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass


_migrate_legacy_config()


def detect_distro() -> str:
    """Read the ID field from /etc/os-release (e.g. 'ubuntu', 'fedora',
    'arch', 'debian'). Returns 'unknown' if the file is missing or
    unparseable (e.g. non-Linux systems), so callers never need to
    special-case a missing value."""
    if not OS_RELEASE_FILE.exists():
        return "macos" if sys.platform == "darwin" else "unknown"
    try:
        with open(OS_RELEASE_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('ID='):
                    value = line.split('=', 1)[1].strip()
                    return value.strip('"').lower()
    except OSError:
        pass
    return "unknown"


def detect_distro_family() -> list:
    """ID plus ID_LIKE from /etc/os-release, e.g. ['pop', 'ubuntu', 'debian'],
    so derivatives map onto the package manager of the distro they're
    based on. Empty if unknown."""
    ids = []
    try:
        with open(OS_RELEASE_FILE, 'r') as f:
            for line in f:
                key, _, value = line.strip().partition('=')
                if key in ('ID', 'ID_LIKE'):
                    ids.extend(value.strip('"').lower().split())
    except OSError:
        pass
    if not ids and sys.platform == "darwin":
        ids = ["macos"]
    return ids


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        _write_default_config()
        config = copy.deepcopy(DEFAULT_CONFIG)
    else:
        try:
            with open(CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
            if not isinstance(user_config, dict):
                raise json.JSONDecodeError("config is not a JSON object", "", 0)
            # Merge shallowly over defaults so a partial user config still works.
            config = copy.deepcopy(DEFAULT_CONFIG)
            config.update(user_config)
            # Configs from before the "local" provider existed don't list it.
            priority = config.get("provider_priority")
            if (isinstance(priority, list) and "local" not in priority
                    and "local" not in user_config):
                at = priority.index("ollama") + 1 if "ollama" in priority else 0
                config["provider_priority"] = priority[:at] + ["local"] + priority[at:]
        except (json.JSONDecodeError, OSError):
            # Corrupted config shouldn't take down the whole tool - fall back to
            # KB-only behavior (empty priority list means no providers get built).
            config = {"provider_priority": []}

    # Always computed live, never persisted to disk - the distro can't
    # change without a fresh install anyway, and this keeps it accurate
    # without a stale cached value surviving an OS upgrade.
    config["distro"] = detect_distro()
    config["distro_family"] = detect_distro_family()
    return config


def _write_default_config():
    """Create the config file with owner-only read/write permissions (0600).

    This file may hold a plaintext Anthropic API key (if the user opts in to
    the cloud provider), so it
    should never be created with default (often world-readable) permissions
    on shared or multi-user systems. os.O_EXCL also means this safely does
    nothing if another process created the file between our exists() check
    and this call, instead of clobbering it.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    except OSError:
        pass
