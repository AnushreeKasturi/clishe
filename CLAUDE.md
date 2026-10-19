# CLAUDE.md

Guidance for Claude (and anyone else) working on Clishe.

## What Clishe is

A command-line helper for people learning Linux: type plain English, see the
real command (each part labelled), run it if you want, and gradually learn to
type it yourself. Published on PyPI as `clishe` (`pipx install clishe`).

**Principles. Keep to these in every change:**
- **Offline first.** Built-in phrases, the dictionary, man pages and the
  bundled tldr-pages data answer before any AI does. The AI is the last step.
- **Local first.** AI runs on the user's machine (Ollama, or any OpenAI-style
  local server). The cloud provider (Anthropic) is opt-in (`"enabled": true`)
  and must never become a default. Non-local hosts are refused unless
  `"allow_remote_ai": true`.
- **Teach, don't hide.** Show the command before running it, explain it, and
  nudge people to type it themselves (your turn, practice, progress, sheet).
- **Safe by default.** Destructive commands need a typed YES with a
  plain-English reason (`safety.py`). Never guess a different file name for
  `rm`/`mv`. Prefer saying nothing over a wrong suggestion.
- **Plain English for users.** Messages are written for beginners: say what
  happened and what to do next. No jargon, no apologies. Not "Error: ENOENT,
  operation failed" or "Sorry, something went wrong!", but "There's no file
  called notes.txt here. Type `ls` to see what's in this folder."
- **Python standard library only**, plus bash. No runtime dependencies.

**Never:**
- add a runtime dependency, or make the Anthropic provider (or any cloud AI) a default;
- edit `tldr.json.gz` by hand (rebuild it with `scripts/build_tldr.py`);
- loosen "did you mean" or tldr matching without first adding the bad cases to the "no match" tests;
- run Clishe or tests against the real `HOME` or the real Trash (see Testing).

## Quick start

```bash
pip install -e ".[dev]"                          # pytest, coverage, ruff
HOME=$(mktemp -d) NO_COLOR=1 ./clishe.sh            # try it with a throwaway home
python -m pytest tests/ -q && ruff check . && /bin/bash tests/test_shell_functions.sh
```

Linux and macOS only. On Windows, work inside WSL: native Windows has no
`grp`/`pwd` modules, POSIX permissions or `man`, so the shell tests can't run
and some Python tests fail for reasons that have nothing to do with your change.

## Layout

| Path | What it is |
|---|---|
| `clishe.sh` | The interactive front end (bash, large: search it before adding a helper): session loop, routing, prompts, display |
| `clishe_brain.py` | Python backend called by `clishe.sh` as `--action <name>`; prints `KEY=value` lines |
| `launch.py` | The `clishe` console script when installed with pipx; runs `clishe.sh` with bash |
| `clishe-bind.bash`, `clishe-bind.zsh` | The Ctrl+G shortcut for the user's normal shell |
| `safety.py` | Parser-based check for destructive commands |
| `knowledge.py` | Offline dictionary, error hints, output guides, install hints |
| `manual.py` | Reads the local `man` page (or `--help`) |
| `tldr.py`, `tldr.json.gz` | tldr-pages summaries, examples and strict phrase matching (CC BY 4.0, see NOTICE.md) |
| `breakdown.py` | Draws a command with each part labelled (or a list in plain mode) |
| `check.py` | `clishe check`: what a command or script would do, without running it |
| `fix.py` | `fix that`: offline fixes for common mistakes |
| `undo.py` | `undo that`: notes taken before a change and how to reverse it |
| `lessons.py`, `lessons/*.json` | Practice lessons with declarative (data-only) checks |
| `apps.py`, `apps.json` | "How do I install Spotify?" |
| `tour.py`, `doctor.py`, `setup_check.py` | `clishe tour`, `clishe doctor`, `clishe setup` |
| `config.py`, `providers/` | Config, distro detection, AI providers (ollama, local, anthropic) |
| `*.json` | Offline data: `seed_kb.json` (phrases), `command_dictionary.json`, `error_patterns.json`, `output_guides.json` |
| `scripts/build_tldr.py` | Rebuilds `tldr.json.gz` from a pinned tldr-pages release. Never edit the .gz by hand |
| `clishe.1` | The man page (`man clishe`) |
| `packaging/aur/` | Arch package (not yet submitted to the AUR) |

When you add, rename or remove a file here, update the README's project
layout too: the two lists are kept by hand.

The installed package keeps this flat layout: `pyproject.toml` maps the repo
root to the `clishe` package, and lists non-Python files in `package-data`
as globs (`*.json`, `*.json.gz`, `lessons/*.json`); `packaging/aur/PKGBUILD`
uses the same globs. **A new file outside those globs (a new extension, a new
folder, another shell script) must be added to `package-data` and to the
PKGBUILD**, or it won't ship. A new Python subfolder also needs an entry in
`packages` and `package-dir`.

## How the pieces talk

`clishe.sh` calls `brain --action <name> ...` (a function that runs
`python3 clishe_brain.py ... 2>/dev/null`) and parses `KEY=value` lines with
`parse_brain_output` or a `while IFS='=' read` loop. To add a feature:
1. Logic in a Python module.
2. A new action in `clishe_brain.py`: a `_action_<name>(brain, args)`
   function that prints `KEY=value` (use `_one_line()` / `_encoded()` for
   values), plus an entry for it in `ACTIONS`. The `--action` choices come
   from that dict, so there is no second list to update.
3. A bash function in `clishe.sh` that renders it.
4. Hook it in, and don't skip the text (the step most often missed):
   - [ ] the one-shot `case "$1"` block and/or the session `case "$user_input"` block
   - [ ] `usage` and `session_help`
   - [ ] README (features, session commands table, one-shot list)
   - [ ] tests for the Python logic and the bash rendering

`tests/test_data_files.py` checks that `usage` and `session_help` still match
the README, and that every file the package needs is in `package-data` and the
PKGBUILD.
`tests/test_clishe_brain.py` checks that every `--action` clishe.sh uses is
registered.

## Debugging

`brain()` in `clishe.sh` runs Python with `2>/dev/null`, so a Python
traceback shows up in bash only as empty output (a feature that "does
nothing"). Run the backend directly to see the error and exactly what it
prints (`KEY=value` lines for most actions; `query` prints the bare command):

```bash
HOME=$(mktemp -d) python3 clishe_brain.py --action explain --command 'ls -la'
HOME=$(mktemp -d) python3 clishe_brain.py --action query --phrase 'show hidden files'
```

Or set `CLISHE_DEBUG=1` to let those errors through in a real session:
`CLISHE_DEBUG=1 HOME=$(mktemp -d) ./clishe.sh ...`. For the bash side,
`HOME=$(mktemp -d) bash -x ./clishe.sh ...` traces each line.

## Config and AI providers

- Config lives in `$XDG_CONFIG_HOME/clishe/config.json` (default
  `~/.config/clishe/config.json`); defaults are `DEFAULT_CONFIG` in
  `config.py`. Neither that folder nor `~/.local/share/clishe` is created on
  import: both are made when something is first saved, so importing a
  Clishe module never writes to `$HOME`
  (`tests/test_data_files.py::test_importing_clishe_writes_nothing_to_home`
  holds that down).
- Keys that matter: `provider_priority` (order AI providers are tried),
  `allow_remote_ai` (off: non-local hosts are refused), and per-provider
  blocks (`model`, `host`, and for cloud providers `enabled`).
- A new provider subclasses `Provider` in `providers/base.py`
  (`is_available`, `resolve_command`, `explain_command`; raise
  `ProviderError` for expected failures so the chain falls through) and is
  registered in `REGISTRY` in `providers/__init__.py`, and nowhere else. A
  cloud provider must be off unless `"enabled": true` (`opted_in`).
- Tests use fake servers; never call a real AI API in a test.

## Testing

```bash
python -m pytest tests/ -q                 # Python (stdlib + pytest)
ruff check .                                # lint (unused imports, undefined names)
coverage run -m pytest tests/ -q && coverage report   # fails below 75% (fail_under)
/bin/bash tests/test_shell_functions.sh    # bash, incl. end-to-end sessions
zsh tests/test_zsh_bind.zsh                # the zsh Ctrl+G widget
```

- CI (`.github/workflows/tests.yml`) runs everything on **Linux (Python
  3.9/3.11/3.12) and macOS**, plus `ruff check`, `coverage report`,
  `shellcheck -S warning` on both systems, `zsh -n`, and an
  install-and-run check of the package (including that the data files and
  the man page are actually installed).
- Ruff is deliberately narrow (`E4,E7,E9,F`, `E402` ignored): it catches
  breakage, not style. Don't widen it without reformatting the codebase -
  the long lines, `typing.List` for Python 3.9 and the `sys.path` line
  before the sibling imports are all intentional.
- **Shellcheck:** run `shellcheck -S warning clishe.sh` if you have it; if
  not, CI will, so watch for SC2034 (variable looks
  unused; e.g. set for `eval` or another function) and SC2178/SC2128 (it
  doesn't track `local` per function, so reusing a name as array in one
  function and string in another fails). Fix by renaming or a targeted
  `# shellcheck disable=` with a reason.
- Tests must not depend on the machine: stub man pages
  (`monkeypatch manual.read_manual`), fake the platform/installed programs
  (`tldr._platforms`, `shutil.which`), fake AI servers, and guard tool-specific
  shell tests (`command -v apt`, `command -v go`).
- Every bundled lesson is replayed by `tests/test_lessons.py` to prove it can
  be finished. Add a lesson and that test covers it.
- When trying features by hand, use a throwaway home:
  `HOME=$(mktemp -d) NO_COLOR=1 ./clishe.sh ...`, never the real one. Don't
  let tests touch the real Trash (fake `gio` and `trash` in `PATH`).

## Gotchas learned the hard way

- **bash 3.2 (macOS):** no `mapfile`, no `read -i`, and `${var//pat/"$rep"}`
  keeps the quotes (bash 5.2 treats `&` as the match instead): use
  `replace_all` and `edit_command`. Test with `/bin/bash` on a Mac.
- **BSD vs GNU tools:** `chmod 644 -- file` fails on macOS (no `--` after the
  mode). Prefer `./-name` over `--` in generated commands.
- **zsh:** `$'\n'` isn't expanded inside `${…//…}`; use a `nl=$'\n'` variable.
- **macOS Trash:** terminal programs can't read `~/.Trash` (no Full Disk
  Access), and Homebrew's `gio trash` doesn't reach the Mac's Trash. On macOS,
  use the built-in `trash` command and explain Finder's "Put Back".
- **Practice** runs learner commands with `eval` in a `mktemp` folder; reads
  go through a subshell with the default Ctrl-C so Ctrl-C means "quit". Its
  cleanup traps (EXIT/HUP/TERM) must be restored afterwards.
- **Matching:** "did you mean" and tldr matching are deliberately strict
  (same action word, every word covered, everyday installed commands only).
  When loosening anything, add the bad cases to the "no match" tests first.
- **Plain mode:** never print symbols directly; use `$ICON_TIP`,
  `$ICON_WARN`, `$ICON_OK`, `$ICON_NOTE`, `$ICON_FAIL`, `$ICON_BULLET`,
  `$ICON_CHEER` (set in `set_symbols`).
- Seed phrases with values use lowercase `<placeholders>`; a bare `cat` would
  hang waiting for input (`tests/test_data_files.py` checks this).

## Workflow

- One focused PR per change, with tests. Merge only when CI is green on
  Linux and macOS. Update `CHANGELOG.md` under `## Unreleased`, the README
  (features, session commands table, one-shot list, project layout) and
  CONTRIBUTING when contributors are affected.
- Commit messages: a short summary line, then what and why.
- **Releases:** follow `RELEASING.md` step by step. The version is in two
  places (`pyproject.toml` and `CLISHE_VERSION` in `clishe.sh`) and they
  must match.
- Issue labels, and which file and test each kind of contribution touches,
  are in CONTRIBUTING ("Good places to start").
