# Contributing to Clishe

Thanks for considering a contribution! This covers the most common ways to help.

## Good places to start

Much of what Clishe knows lives in plain JSON files, so you can make a real
difference without touching the code. Issues labelled
[`good first issue`](https://github.com/Sym-jay/clishe/labels/good%20first%20issue)
and [`data only (no code)`](https://github.com/Sym-jay/clishe/labels/data%20only%20%28no%20code%29)
are the easiest way in.

| You want to... | Edit | Checked by |
|---|---|---|
| Add a phrase ("show me disk usage" → `df -h`) | `seed_kb.json` | `tests/test_data_files.py`, `tests/test_match_eval.py` |
| Explain a command and its flags (`explain tar -xzvf`) | `command_dictionary.json` | `tests/test_data_files.py`, `tests/test_knowledge.py` |
| Explain an error message beginners hit | `error_patterns.json` | `tests/test_knowledge.py` |
| Explain a command's output ("what does this mean?") | `output_guides.json` | `tests/test_knowledge.py` |
| Teach "how do I install <app>?" a new app | `apps.json` (Flathub ID, Homebrew cask, and apt/dnf/pacman only if the app is in that distro's official repositories) | `tests/test_apps.py` |
| Add a practice exercise, or a whole lesson | `lessons/*.json` (see "Writing a lesson" below) | `tests/test_lessons.py` |
| Teach `fix that` a new mistake | a rule function in `fix.py` (add it to `RULES`) | `tests/test_fix.py` |
| Teach `undo that` a new command | `before()`, `after()` and `plan()` in `undo.py` | `tests/test_undo.py` |
| Teach `clishe check` a new effect | `_facts()` and `describe()` in `check.py` | `tests/test_check.py` |
| Catch a new dangerous command | `safety.py` (see below) | `tests/test_safety.py` |

Try your change in a real session too (`./clishe.sh` from the repo folder).
Nothing to set up: Clishe uses only the Python standard library.

## Adding a new AI provider

Clishe's provider system is designed so a new backend (OpenAI, Gemini, a
different local model server, etc.) can be added without touching
`clishe_brain.py` or `clishe.sh` at all.

1. Create a new file in `providers/`, e.g. `providers/openai_provider.py`.
2. Implement the `Provider` interface from `providers/base.py`:
```python
   from .base import (Provider, ProviderError, Resolution, distro_note,
                      parse_json_reply, resolution_from_reply)

   class OpenAIProvider(Provider):
       name = "openai"

       def is_available(self) -> bool:
           # Cheap, local check only - no network call here.
           ...

       def resolve_command(self, phrase: str) -> str | None:
           # Return a shell command, or None if unclear/unsafe.
           # Raise ProviderError for real failures (network, auth, etc).
           ...

       # Optional but recommended: also return the model's one-line reason,
       # which Clishe shows under the suggestion. The default implementation
       # calls resolve_command() and leaves the explanation empty.
       def resolve_with_explanation(self, phrase: str) -> Resolution | None:
           ...

       def explain_command(self, command: str) -> str | None:
           ...
```
   `parse_json_reply()` tolerates code fences and chatter around the JSON,
   `resolution_from_reply()` turns `{"command": ..., "explanation": ...}`
   into a `Resolution`, and `distro_note()` gives the prompt text that makes
   package-manager answers fit the user's distro. Ask the model to write
   missing values as `<placeholders>` (see the existing prompts) so Clishe
   can prompt for them.
3. Register it in `providers/__init__.py`:
```python
   from .openai_provider import OpenAIProvider

   REGISTRY = {
       "ollama": OllamaProvider,
       "local": LocalProvider,
       "anthropic": AnthropicProvider,
       "openai": OpenAIProvider,
   }
```
4. Add tests in `tests/test_providers.py` mocking the network call, covering
   at least one success case and one failure case (see the existing
   Anthropic/Ollama tests for the pattern).
   A provider that sends anything over the internet must set `local = False`,
   which keeps it off until the user sets `"enabled": true` in its config.
   Clishe is local-first: please don't add cloud providers to the defaults.
5. Mention the new provider and its config keys in the README's "Enabling
   AI features" section.

## Adding to the offline knowledge/command dictionary

`command_dictionary.json` and `error_patterns.json` (used by `explain` and
`diagnose`) can grow without any code changes — just add entries following
the existing format. Short flags are listed one per key (`"-x"`, `"-z"`) so
combined flags like `-xzvf` can be explained letter by letter; subcommands
(`"status"` for git) work the same way.

## Adding seed phrases

`seed_kb.json` maps a lowercase phrase to a command. If the command needs a
value from the user, write it as a placeholder of lowercase words in angle
brackets, e.g. `"copy a file": "cp <file> <destination>"`. Never add a bare
command that needs arguments (`"cat"`), since it would hang or fail when run.
`tests/test_data_files.py` checks this.

## Updating the tldr-pages data

`tldr.json.gz` is generated, so don't edit it by hand. To move to a newer
tldr-pages release, change `VERSION` in `scripts/build_tldr.py`, run
`python3 scripts/build_tldr.py`, run the tests, and update the version in
NOTICE.md. Improvements to the examples themselves belong upstream in
[tldr-pages](https://github.com/tldr-pages/tldr).

## Writing a lesson

A lesson is a JSON file in `lessons/` (bundled with Clishe) or in
`~/.local/share/clishe/lessons/` (your own, or a workshop's). The file name
is the lesson's name: `lessons/permissions.json` runs with
`clishe practice permissions`.

```json
{
  "title": "File permissions",
  "description": "Who can read, change and run a file.",
  "done": "You just used ls -l and chmod.",
  "exercises": [
    {"task": "Make a file called script.sh.",
     "check": [{"file": "script.sh"}],
     "hint": "touch <file> creates an empty file.",
     "answer": "touch script.sh"},
    {"task": "Let yourself run script.sh.",
     "check": [{"typed": "^chmod\\b.*\\+x"}],
     "hint": "chmod +x <file> marks a file as runnable.",
     "answer": "chmod +x script.sh"}
  ]
}
```

Each exercise runs in a fresh throwaway folder, and its `check` is a list of
conditions that must all be true after the learner's command. Checks are data,
never code, so a lesson can't run anything by being checked:

| Condition | True when |
|---|---|
| `{"typed": "^ls"}` | what they typed matches the pattern (a regular expression) |
| `{"dir": "notes"}` | that folder exists |
| `{"file": "notes/todo.txt"}` | that file exists |
| `{"missing": "old.txt"}` | nothing is there any more |
| `{"contains": ["notes/todo.txt", "milk"]}` | the file contains the text |
| `{"cwd": "notes"}` | they are in that folder (`"."` is the practice folder itself) |

Paths are relative to the practice folder, and checks never look outside it.
If a lesson needs a program that might not be installed, list it in
`"needs": ["git"]`: Clishe then explains how to install it instead of
starting the lesson.
`answer` is what `answer` and `skip` show; it's also run to set the folder up
when someone picks up a lesson halfway, so each answer should leave things the
way the next exercise expects. `tests/test_lessons.py` runs every bundled
lesson's answers in order and fails if any exercise can't be finished.

## Improving the safety check

`safety.py` decides when Clishe asks for a typed `YES`. To cover a new
dangerous pattern, add a reason to `REASONS`, detect it in
`_check_segment()`, and add cases to both the `DANGEROUS` and `SAFE` lists
in `tests/test_safety.py`. False positives matter too: a prompt that fires
on everyday commands teaches people to type `YES` without reading.

## Running tests locally

```bash
pip install -e ".[dev]"          # pytest, coverage, ruff - none of these ship
python -m pytest tests/ -v
ruff check .                     # unused imports, undefined names
bash tests/test_shell_functions.sh
shellcheck -S warning clishe.sh install.sh   # if you have shellcheck
```

`tests/test_shell_functions.sh` sources `clishe.sh` (which stops after its
function definitions when sourced) and tests the real bash functions, plus
a few end-to-end sessions with piped input.

## Pull requests

- Keep PRs focused — one change per PR is easier to review than several
  bundled together.
- Make sure `python -m pytest tests/ -v` and `ruff check .` pass before
  opening the PR. CI runs the same on Linux and macOS.
- Describe *why* the change is needed, not just what it does.

## Reporting bugs or safety issues

For a general bug, open a GitHub issue with steps to reproduce.

For a safety bypass (a command running without the expected confirmation
prompt, or a destructive pattern not being caught), see `SECURITY.md`.
