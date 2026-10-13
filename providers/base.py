"""
Provider - the common interface every AI backend (local or cloud) must implement.

Keeping this interface tiny on purpose: two operations, both optional-returning.
Anything provider-specific (auth, prompt format, HTTP client) lives inside the
provider subclass, never leaks into clishe_brain.py.
"""
import ipaddress
import json
import re
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class ProviderError(Exception):
    """Raised for expected failures (timeout, bad auth, empty response).
    Callers catch this and fall through to the next provider."""
    pass


@dataclass
class Resolution:
    """A suggested command plus the model's one-line reason for it."""
    command: str
    explanation: str = ""


def parse_json_reply(text: str) -> dict:
    """Parse a model's JSON reply, tolerating markdown fences or chatter
    around the object (small local models add both). Raises ProviderError
    if there's no JSON object in it at all."""
    cleaned = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError(
                f"No JSON object in model reply: {cleaned[:80]!r}") from None
        try:
            data = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as e:
            raise ProviderError(f"Could not parse model reply as JSON: {e}") from e
    if not isinstance(data, dict):
        raise ProviderError("Model reply was JSON but not an object")
    return data


# The same instructions for every model, local or cloud, so a small local
# model gets the same safety rules as a big one.
RESOLVE_PROMPT = (
    "You translate a beginner's plain-English request into a single Linux "
    "shell command. Reply with ONLY a JSON object, no markdown fences, no "
    "extra text, in this exact shape: "
    '{"command": "<the shell command>", "explanation": "<one short sentence>"}. '
    "If the request is unclear, unsafe (e.g. would delete/overwrite data, "
    "modify permissions recursively, or affect the whole system), or isn't "
    "really a shell task, reply with "
    '{"command": null, "explanation": "<why, in one short sentence>"}. '
    "If the command needs a value the user did not give (like a file or folder "
    "name), write it as a short lowercase placeholder in angle brackets, e.g. "
    '"cat <file>" or "cp <file> <destination>". '
    "Prefer simple, common commands a beginner can learn and reuse."
)

EXPLAIN_PROMPT = (
    "You explain Linux shell commands to a beginner in one or two short, "
    "plain-English sentences. Reply with ONLY a JSON object, no markdown "
    'fences: {"explanation": "<text>"}. Be concrete about what the command '
    "does and flag anything destructive or irreversible."
)

FIX_PROMPT = (
    "A beginner ran a Linux shell command and it failed. In one or two short, "
    "plain-English sentences, explain what went wrong, and give a corrected "
    "command if there is one. Reply with ONLY a JSON object, no markdown fences: "
    '{"explanation": "<text>", "command": "<the corrected command, or null>"}. '
    "Never suggest a command that deletes or overwrites data. Only add sudo when "
    "the error is about permissions. If you're not sure of a fix, use null."
)

# Package manager for each distro family, for the prompt.
_PACKAGE_MANAGERS = {
    "debian": "apt", "ubuntu": "apt", "fedora": "dnf", "rhel": "dnf",
    "centos": "dnf", "arch": "pacman", "opensuse": "zypper", "suse": "zypper",
    "alpine": "apk",
}


def distro_note(distro: str, family=None) -> str:
    """Extra prompt text so package-manager answers fit the user's distro.
    `family` is ID plus ID_LIKE from /etc/os-release, so a derivative like
    Linux Mint (ID_LIKE="ubuntu debian") is told to use apt."""
    if not distro or distro == "unknown":
        return ""
    if distro == "macos":
        return (" The user is on macOS: its tools are the BSD versions, so some options "
                "differ from GNU/Linux. Use Homebrew (brew install) for installs, never sudo with brew.")
    note = f" The user's system is running the '{distro}' Linux distribution"
    based_on = [d for d in (family or []) if d != distro]
    if based_on:
        note += f" (based on {', '.join(based_on)})"
    manager = next((_PACKAGE_MANAGERS[d] for d in [distro, *(family or [])]
                    if d in _PACKAGE_MANAGERS), None)
    if manager:
        return note + f". Its package manager is {manager}; use it for installs."
    return (note + " - use its native package manager and conventions (e.g. apt for "
            "debian/ubuntu, dnf for fedora, pacman for arch) when relevant.")


def is_local_address(url: str) -> bool:
    """True if `url` points at this computer or the local network (a home
    server, say). Clishe's promise is that your phrases never leave your
    own machines unless you opt in to a cloud provider."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    return bool(addresses) and all(
        a.is_loopback or a.is_private or a.is_link_local for a in addresses)


def resolution_from_reply(data: dict) -> Optional[Resolution]:
    """Turn {"command": ..., "explanation": ...} into a Resolution, or None
    if the model declined (null/empty command)."""
    command = data.get("command")
    if not command or not isinstance(command, str) or not command.strip():
        return None
    explanation = data.get("explanation")
    if not isinstance(explanation, str):
        explanation = ""
    return Resolution(command.strip(), explanation.strip())


class Provider(ABC):
    #: short machine name, e.g. "ollama", "anthropic" - used in config & logs
    name = "base"
    #: False for providers that send your phrases over the internet. Those
    #: are only used when the user turns them on ("enabled": true).
    local = True

    def __init__(self, config: dict):
        self.config = config or {}

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap, local check - do we even have what's needed to try this
        provider (an API key present, a local server reachable)? Should NOT
        make a real generation request."""
        raise NotImplementedError

    @abstractmethod
    def resolve_command(self, phrase: str) -> Optional[str]:
        """Translate a natural-language phrase into a single shell command.
        Return None (not raise) if the model declines/is unsure - that's a
        normal outcome, not an error. Raise ProviderError for actual failures
        (network, auth, malformed response) so the caller can try the next
        provider in the chain."""
        raise NotImplementedError

    def resolve_with_explanation(self, phrase: str) -> Optional[Resolution]:
        """Like resolve_command, but also returns the model's short reason so
        the user learns *why* this command does what they asked. Providers
        that can't give a reason don't need to override this."""
        command = self.resolve_command(phrase)
        return Resolution(command) if command else None

    def fix_command(self, command: str, error: str) -> Optional[dict]:
        """Explain why a command failed and suggest a corrected one:
        {"explanation", "command"} (command may be ""), or None if unsure.
        Works for any provider that has an _ask(system, user) -> dict
        helper; others don't support it."""
        ask = getattr(self, "_ask", None)
        if ask is None:
            return None
        system = FIX_PROMPT + distro_note(getattr(self, "distro", ""), getattr(self, "family", []))
        data = ask(system, f"Command: {command}\nError:\n{(error or '')[-1500:]}")
        explanation = data.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            return None
        command = data.get("command")
        return {"explanation": explanation.strip(),
                "command": command.strip() if isinstance(command, str) else ""}

    @abstractmethod
    def explain_command(self, command: str) -> Optional[str]:
        """Return a short, beginner-friendly explanation of what a shell
        command does. Return None if unsure; raise ProviderError on failure."""
        raise NotImplementedError
