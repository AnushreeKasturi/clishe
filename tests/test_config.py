"""Tests for config.py - the config file, its defaults and the distro
check. Every test points CONFIG_FILE at a temporary folder, so the real
config is never read or written."""
import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path


def test_first_run_writes_private_defaults(cfg_file):
    loaded = config.load_config()
    assert json.loads(cfg_file.read_text()) == config.DEFAULT_CONFIG
    assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600
    assert loaded["provider_priority"] == ["ollama", "local", "anthropic"]
    assert "distro" not in json.loads(cfg_file.read_text())


def test_cloud_ai_is_off_by_default():
    assert config.DEFAULT_CONFIG["anthropic"]["enabled"] is False
    assert config.DEFAULT_CONFIG["allow_remote_ai"] is False
    assert config.DEFAULT_CONFIG["provider_priority"][0] == "ollama"


def test_write_default_never_overwrites(cfg_file):
    cfg_file.write_text('{"trash": "always"}')
    config._write_default_config()
    assert json.loads(cfg_file.read_text()) == {"trash": "always"}


def test_partial_config_keeps_other_defaults(cfg_file):
    cfg_file.write_text('{"trash": "always"}')
    loaded = config.load_config()
    assert loaded["trash"] == "always"
    assert loaded["allow_remote_ai"] is False
    assert loaded["ollama"]["model"] == "llama3.2"


def test_old_priority_gains_local_after_ollama(cfg_file):
    cfg_file.write_text('{"provider_priority": ["ollama", "anthropic"]}')
    assert config.load_config()["provider_priority"] == ["ollama", "local", "anthropic"]
    cfg_file.write_text('{"provider_priority": ["anthropic"]}')
    assert config.load_config()["provider_priority"] == ["local", "anthropic"]


def test_priority_left_alone_when_local_was_set_up(cfg_file):
    cfg_file.write_text('{"provider_priority": ["ollama"], "local": {"host": "", "model": ""}}')
    assert config.load_config()["provider_priority"] == ["ollama"]


@pytest.mark.parametrize("text", ["{not json", "", "[1, 2]", '"hello"', "null"])
def test_broken_config_turns_ai_off_instead_of_crashing(cfg_file, text):
    cfg_file.write_text(text)
    loaded = config.load_config()
    assert loaded["provider_priority"] == []
    assert "distro" in loaded
    assert cfg_file.read_text() == text


def test_loading_does_not_change_the_defaults(cfg_file):
    loaded = config.load_config()
    loaded["ollama"]["model"] = "something-else"
    loaded["provider_priority"].append("extra")
    assert config.DEFAULT_CONFIG["ollama"]["model"] == "llama3.2"
    assert config.DEFAULT_CONFIG["provider_priority"] == ["ollama", "local", "anthropic"]


def test_old_config_moves_to_new_place_and_becomes_private(cfg_file, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    old = home / ".clishe_config.json"
    old.write_text('{"anthropic": {"api_key": "secret"}}')
    old.chmod(0o644)
    monkeypatch.setattr(Path, "home", lambda: home)
    config._migrate_legacy_config()
    assert not old.exists()
    assert json.loads(cfg_file.read_text())["anthropic"]["api_key"] == "secret"
    assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600


def test_old_config_never_replaces_a_new_one(cfg_file, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    old = home / ".clishe_config.json"
    old.write_text('{"trash": "old"}')
    cfg_file.write_text('{"trash": "new"}')
    monkeypatch.setattr(Path, "home", lambda: home)
    config._migrate_legacy_config()
    assert old.exists()
    assert json.loads(cfg_file.read_text()) == {"trash": "new"}


def test_distro_from_os_release(tmp_path, monkeypatch):
    release = tmp_path / "os-release"
    release.write_text('NAME="Pop!_OS"\nID=pop\nID_LIKE="ubuntu debian"\n')
    monkeypatch.setattr(config, "OS_RELEASE_FILE", release)
    assert config.detect_distro() == "pop"
    assert config.detect_distro_family() == ["pop", "ubuntu", "debian"]
    release.write_text('ID="Fedora"\n')
    assert config.detect_distro() == "fedora"
    release.write_text('NAME=Mystery\n')
    assert config.detect_distro() == "unknown"


@pytest.mark.parametrize("platform,name,family", [
    ("darwin", "macos", ["macos"]),
    ("linux", "unknown", []),
])
def test_distro_without_os_release(tmp_path, monkeypatch, platform, name, family):
    monkeypatch.setattr(config, "OS_RELEASE_FILE", tmp_path / "missing")
    monkeypatch.setattr(sys, "platform", platform)
    assert config.detect_distro() == name
    assert config.detect_distro_family() == family
