"""Checks on the bundled data files and project metadata, so a bad edit to a
JSON file or a forgotten version bump fails CI instead of a user's session."""
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clishe_brain import normalize_phrase  # noqa: E402

SEED = json.loads((ROOT / "seed_kb.json").read_text())

# Same rule as RE_PLACEHOLDER in clishe.sh.
PLACEHOLDER = re.compile(r"<([a-z]+( [a-z]+)*)>")

# Commands that hang waiting for input, or fail, when run with no arguments.
NEEDS_ARGUMENT = {"cat", "less", "head", "tail", "wc", "cp", "mv", "rm", "mkdir",
                  "touch", "chmod", "chown", "kill", "pkill", "wget", "diff", "grep"}


@pytest.mark.parametrize("phrase,command", SEED.items())
def test_seed_commands_are_complete(phrase, command):
    """A seed entry must be runnable as-is or use <placeholders>, never a
    bare 'cat' that hangs the session waiting on stdin."""
    words = command.split()
    assert not (len(words) == 1 and words[0] in NEEDS_ARGUMENT), (
        f"{phrase!r} -> {command!r} needs an argument; use a <placeholder>")
    # Anything left that looks like <...> is a placeholder clishe.sh won't
    # recognise (capitals, digits, punctuation), so it would run literally.
    leftover = re.search(r"<[^ ]", PLACEHOLDER.sub("", command))
    assert not leftover, (
        f"{command!r} has a malformed placeholder (use lowercase words, e.g. <file name>)")


@pytest.mark.parametrize("phrase", SEED)
def test_seed_phrases_are_normalized(phrase):
    assert normalize_phrase(phrase) == phrase


def test_error_patterns_are_well_formed():
    patterns = json.loads((ROOT / "error_patterns.json").read_text())
    for entry in patterns:
        assert entry["match"] and entry["hint"]


def test_command_dictionary_is_well_formed():
    dictionary = json.loads((ROOT / "command_dictionary.json").read_text())
    for name, entry in dictionary.items():
        assert entry.get("summary"), name
        assert isinstance(entry.get("flags", {}), dict), name


def test_version_matches_between_script_and_pyproject():
    script = (ROOT / "clishe.sh").read_text()
    pyproject = (ROOT / "pyproject.toml").read_text()
    script_version = re.search(r'^CLISHE_VERSION="([^"]+)"', script, re.M).group(1)
    project_version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert script_version == project_version


def _shell_help_block(name):
    """The text of a `cat <<'EOF'` help function in clishe.sh, e.g. usage."""
    script = (ROOT / "clishe.sh").read_text()
    block = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", script, re.S | re.M)
    assert block, f"no {name}() in clishe.sh"
    return block.group(1)


# A session keyword: lowercase words, optionally ending in <placeholder>
# or [optional]. Anything else in the help text is prose, not a command.
SESSION_KEYWORD = re.compile(r"^[a-z][a-z0-9 ]*(?:<[^>]+>|\[[a-z]+\])?$")


def test_every_file_clishe_needs_is_packaged():
    """Anything the installed package must carry has to match a package-data
    glob and be installed by the PKGBUILD, or it silently doesn't ship
    (CLAUDE.md, Layout). Docs and build files stay out of the package."""
    # Everything a running Clishe reads has to ship: data (*.json), the
    # bundled tldr-pages database, and the shell scripts and man page.
    shippable = (".json", ".gz", ".sh", ".1")
    # install.sh is the from-git installer: it clones the repo, so it is run
    # from a checkout and is not part of the installed package.
    known_exceptions = {"install.sh"}
    pyproject = (ROOT / "pyproject.toml").read_text()
    globs = re.search(r"^clishe = \[(.*?)\]", pyproject, re.S | re.M).group(1)
    patterns = [p.strip().strip('"') for p in globs.split(",")]

    for path in sorted(ROOT.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if not path.name.endswith(shippable) or path.name in known_exceptions:
            continue
        assert any(fnmatch.fnmatch(path.name, p) for p in patterns), (
            f"{path.name} is not in package-data ({patterns}); add it there and "
            f"to packaging/aur/PKGBUILD, or it won't ship")


def test_the_aur_package_installs_what_pyproject_ships():
    """The PKGBUILD keeps its own copy of the file list; it must not fall
    behind the pip package."""
    pkbuild = (ROOT / "packaging" / "aur" / "PKGBUILD").read_text()
    # clishe-bind.* covers both shell bindings.
    for needed in ("clishe.sh", "clishe-bind.*", "clishe.1",
                   "./*.json", "./*.json.gz", "lessons/*.json", "providers/*.py"):
        assert needed in pkbuild, f"the PKGBUILD does not install {needed}"
    assert "/usr/share/man/man1/clishe.1" in pkbuild, "the man page is not installed"


def test_every_one_shot_command_in_usage_is_in_the_readme():
    """`clishe --help` and the README list the same commands. A new one-shot
    command added to usage() but not the README is the usual drift."""
    readme = (ROOT / "README.md").read_text()
    commands = [m.group(1) for m in
                (re.match(r"^  clishe (\S+)", line)
                 for line in _shell_help_block("usage").splitlines()) if m]
    assert commands, "no one-shot commands found in usage()"
    missing = [c for c in commands if c.strip('"<>') not in readme]
    assert not missing, f"README does not document: {missing}"


def test_every_session_command_in_help_is_in_the_readme():
    """Same for the session commands: session_help() and the README's
    session commands table must not drift apart."""
    readme = (ROOT / "README.md").read_text()
    keywords = []
    for line in _shell_help_block("session_help").splitlines():
        # The description starts at two or more spaces, so keywords and
        # descriptions are always separable (keep session_help padded).
        match = re.match(r"^  (\S.*?)(?:  +|$)", line)
        if match and SESSION_KEYWORD.match(match.group(1)):
            keywords.append(match.group(1))
    assert keywords, "no session commands found in session_help()"
    missing = [k for k in keywords if f"`{k}`" not in readme]
    assert not missing, f"README does not document: {missing}"


def test_specific_error_patterns_come_before_generic_ones():
    # First match wins, so "permission denied (publickey)" must be checked
    # before plain "permission denied".
    matches = [e["match"] for e in json.loads((ROOT / "error_patterns.json").read_text())]
    assert matches.index("permission denied (publickey)") < matches.index("permission denied")


def test_output_guides_are_well_formed():
    for entry in json.loads((ROOT / "output_guides.json").read_text()):
        assert entry["command"] and entry["guide"]


def test_old_configs_get_the_local_provider(tmp_path, monkeypatch):
    import json as _json
    import config as cfg
    path = tmp_path / "config.json"
    path.write_text(_json.dumps({"provider_priority": ["ollama", "anthropic"]}))
    monkeypatch.setattr(cfg, "CONFIG_FILE", path)
    loaded = cfg.load_config()
    assert loaded["provider_priority"] == ["ollama", "local", "anthropic"]
    assert loaded["anthropic"]["enabled"] is False


def test_default_config_is_local_only():
    import config as cfg
    assert cfg.DEFAULT_CONFIG["anthropic"]["enabled"] is False
    assert cfg.DEFAULT_CONFIG["allow_remote_ai"] is False


def test_importing_config_writes_nothing(tmp_path):
    """Importing config.py must not create a folder or a config file. It used
    to mkdir on import, which meant every test run - and any `python -c
    "import config"` - left a ~/.config/clishe behind in the real HOME."""
    import subprocess
    import sys as _sys
    script = ("import sys; sys.path.insert(0, %r); import config; "
              "print(config.CONFIG_FILE.exists())" % str(ROOT))
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path))
    result = subprocess.run([_sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "importing config created a config file"
    assert not (tmp_path / "clishe").exists(), "importing config created a folder"


def test_loading_a_missing_config_writes_the_defaults(tmp_path):
    """The first-run file is still created when Clishe actually runs - just
    not when it is imported."""
    import subprocess
    import sys as _sys
    script = ("import sys; sys.path.insert(0, %r); import config; "
              "config.load_config(); print(config.CONFIG_FILE.exists())" % str(ROOT))
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path))
    result = subprocess.run([_sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"
    written = json.loads((tmp_path / "clishe" / "config.json").read_text())
    assert written == __import__("config").DEFAULT_CONFIG


def _run_import(module, tmp_path):
    """Import a Clishe module in a subprocess with HOME pointed at tmp_path."""
    import subprocess
    import sys as _sys
    script = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import {module}"
    env = dict(os.environ, HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / ".config"),
               XDG_DATA_HOME=str(tmp_path / ".local" / "share"))
    result = subprocess.run([_sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["config", "clishe_brain", "knowledge",
                                    "safety", "undo", "check", "lessons",
                                    "apps", "manual", "breakdown", "fix",
                                    "tour", "doctor", "setup_check", "tldr"])
def test_importing_clishe_writes_nothing_to_home(module, tmp_path):
    """Importing any of Clishe's modules must leave HOME exactly as it was.

    They used to mkdir on import, which meant every test run - and anything
    else that just imported a function - littered the user's home with a
    config folder and a data folder.
    """
    _run_import(module, tmp_path)
    assert list(tmp_path.iterdir()) == [], (
        f"importing {module} created {sorted(p.name for p in tmp_path.iterdir())}")


def test_the_data_folder_is_created_when_something_is_saved(tmp_path):
    """...but the first save still makes it, or nothing would ever persist."""
    import subprocess
    import sys as _sys
    script = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
              "import clishe_brain as b; "
              "b.ClisheBrain().save_data(); print(b.DATA_DIR.is_dir())")
    env = dict(os.environ, HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / ".config"),
               XDG_DATA_HOME=str(tmp_path / ".local" / "share"))
    result = subprocess.run([_sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"
    assert (tmp_path / ".local" / "share" / "clishe" / "history.json").exists()
