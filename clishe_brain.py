#!/usr/bin/env python3
"""
Clishe Brain - backend for clishe.sh.

Owns the knowledge base (phrases you taught), command history and
next-command prediction, AI-provider resolution, offline explanations,
error hints and the safety check. clishe.sh talks to it through
`--action ...` calls and reads back simple KEY=value lines.
"""
import argparse
import difflib
import json
import os
import re
import shlex
import shutil
import sys
from fractions import Fraction
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Make sure the script's own directory is importable regardless of the
# caller's cwd (clishe.sh may be invoked from anywhere).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from knowledge import (lookup_command, format_explanation, diagnose_error,
                       missing_program_hint, POPULAR_PROGRAMS, output_guide)
from safety import check_command
from manual import check_flags, explain_from_manual



def build_provider_chain(config):
    """The AI providers pull in the network libraries, which cost ~35ms to
    load on every call. Most calls (lookups, safety checks, logging) never
    need them, so they're imported only when the AI is actually asked."""
    from providers import build_provider_chain as _build
    return _build(config)


# ---------- XDG-compliant data file locations ----------
# Data (KB + history) lives under $XDG_DATA_HOME/clishe/, falling back to
# ~/.local/share/clishe/ per the XDG Base Directory spec, instead of
# cluttering the bare home directory with dotfiles.
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DATA_DIR = XDG_DATA_HOME / "clishe"


def _ensure_data_dir():
    """Create the data folder, owner-only, when something needs to go in it.

    Deliberately not done at import: importing this module must not create
    anything in the user's HOME. The test suite imports it (with HOME pointed
    at a temporary folder), and so does anything that just wants to look at a
    function.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # History can contain paths, hostnames or tokens someone typed.
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass

KB_FILE = DATA_DIR / "kb.json"
UNDO_FILE = DATA_DIR / "undo.json"
DATA_FILE = DATA_DIR / "history.json"

# Bundled, read-only seed knowledge base shipped with the repo (never
# written to). Lets a fresh install feel responsive on common phrases
# before the user has taught anything or configured an AI provider.
SEED_KB_FILE = Path(__file__).resolve().parent / "seed_kb.json"


def _migrate_legacy_file(old_name: str, new_path: Path):
    """One-time migration from the old ~/.clishe_* locations to the new
    XDG-compliant paths, so upgrading doesn't silently lose existing data."""
    old_path = Path.home() / old_name
    if old_path.exists() and not new_path.exists():
        _ensure_data_dir()
        try:
            old_path.rename(new_path)
        except OSError:
            pass


_migrate_legacy_file(".clishe_kb.json", KB_FILE)
_migrate_legacy_file(".clishe_data.json", DATA_FILE)

# Minimum number of stored sequences before we bother predicting
MIN_SEQUENCES_FOR_PREDICTION = 3
# How many commands we keep in the "current" rolling buffer before archiving
SEQUENCE_FLUSH_LENGTH = 10
# Oldest sequences are dropped past this, so history.json stays small.
MAX_SEQUENCES = 200
# After asking for the same phrase this many times, Clishe shows the command
# so you can start typing it yourself.
GRADUATION_TIP_AT = (3, 10)
# "Your turn": once you've asked for a phrase this many times (and seen the
# tip with its command), Clishe asks you to type it yourself, until you've
# got it right this many times. "learn_mode" in the config: gentle (these
# numbers), always (from the second time), off.
YOUR_TURN_AFTER = {"gentle": 3, "always": 1}
YOUR_TURN_UNTIL_RIGHT = 2
# The everyday commands the progress report counts toward.
BASICS = ["pwd", "ls", "cd", "mkdir", "touch", "cp", "mv", "rm", "cat", "less",
          "head", "tail", "grep", "find", "df", "du", "free", "ps", "top", "kill",
          "chmod", "tar", "man", "echo", "nano", "sudo", "ssh", "history"]
# How similar a phrase must be (0-1) to offer "did you mean ...?"
FUZZY_CUTOFF = 0.78

# Words people add around a request that don't change what they want.
_LEADING_FILLER = re.compile(
    r"^(?:(?:please|pls|hey|hi|ok|okay|so|um|clishe|can you|could you|would you)[,!]?\s+)+")
_TRAILING_FILLER = re.compile(r"(?:[,]?\s+(?:please|pls|thanks|thank you))+$")


def normalize_phrase(phrase: str) -> str:
    """Canonical form used for KB keys and lookups:
    '  Please, show me disk usage?? ' -> 'show me disk usage'."""
    p = (phrase or "").lower().strip()
    p = p.replace("’", "'").replace("‘", "'")
    p = re.sub(r"\s+", " ", p)
    p = p.strip(" ?!.,")
    p = _LEADING_FILLER.sub("", p)
    p = _TRAILING_FILLER.sub("", p)
    return p.strip(" ?!.,")


# ---------- meaning-based matching ----------
# difflib only sees letters, so "remove a directory" never matches "delete a
# folder". These tables map words onto a shared vocabulary so the
# "did you mean...?" offer can match on meaning. Still offline, still a
# suggestion the user has to accept.

# Words that don't say *what* the user wants done.
_STOPWORDS = set("""
a an the my me i you your is are am do does did be what whats how much many
which can could would will should please show display see view list print
check tell give get let s of to in on for at from with this that these those
it its all any have has there here want need know
""".split())

_SYNONYMS = {
    "directory": "folder", "directories": "folder", "dir": "folder", "dirs": "folder",
    "remove": "delete", "erase": "delete", "del": "delete", "rm": "delete", "wipe": "delete",
    "usage": "use", "using": "use", "used": "use", "uses": "use",
    "space": "disk", "storage": "disk", "drive": "disk",
    "big": "size", "bigger": "size", "biggest": "size", "large": "size",
    "larger": "size", "largest": "size", "huge": "size",
    "ram": "memory",
    "program": "process", "app": "process", "application": "process", "task": "process",
    "running": "run",
    "find": "search", "locate": "search", "look": "search",
    "left": "free", "available": "free", "remaining": "free",
    "make": "create", "new": "create",
    "duplicate": "copy",
    "internet": "network", "wifi": "network",
    "zip": "compress", "unzip": "extract", "unpack": "extract", "decompress": "extract",
    "contents": "content", "inside": "content",
}


def _stem(word: str) -> str:
    """Tiny plural stripper: files -> file, processes -> process."""
    if len(word) > 4 and word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def meaning_tokens(phrase: str) -> frozenset:
    """'Please remove the directories' -> {'delete', 'folder'}"""
    out = set()
    for w in re.findall(r"[a-z0-9]+", normalize_phrase(phrase)):
        if w in _STOPWORDS:
            continue
        w = _SYNONYMS.get(w) or _SYNONYMS.get(_stem(w)) or _stem(w)
        if w not in _STOPWORDS:
            out.add(w)
    return frozenset(out)


# Generic nouns say little on their own: "unzip a file" sharing only "file"
# with "list files" is not a match.
_WEAK_WORDS = {"file": Fraction(3, 10), "folder": Fraction(3, 10)}


def _weight(tokens) -> Fraction:
    """Exact, so "exactly half" is the same on every Python: summing floats
    like 1 + 0.3 + 1 + 0.3 gives 2.5999999999999996 on Python < 3.12."""
    return sum((_WEAK_WORDS.get(t, Fraction(1)) for t in tokens), Fraction(0))


# A candidate must be mostly covered by what the user said (so a match never
# adds an action they didn't ask for: "my files" must not become "delete a
# file"), and must cover more than half of what they said (so it can't
# drop the word that matters: "change my password" is not "what did i
# change", and "delete my photos" is not "delete a file").
MEANING_CANDIDATE_COVERAGE = 0.67
MEANING_QUERY_COVERAGE = 0.5


def _only_typos(said: str, phrase: str) -> bool:
    """A spelling match is only a match if the words that differ are typos
    of each other: "show disk usge" is "show disk usage", but "count words
    in a file" is not "count lines in a file"."""
    wanted, have = meaning_tokens(said), meaning_tokens(phrase)
    return all(difflib.get_close_matches(w, list(have), n=1, cutoff=0.75)
               for w in wanted - have)


class ClisheBrain:
    def __init__(self):
        self.kb = self.load_kb()
        self.data = self.load_data()

    # ---------- persistence helpers ----------

    def _load_json(self, path, default):
        """Load JSON from disk, falling back to `default` on missing/corrupt file."""
        if not path.exists():
            return default
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not read {path.name} ({e}); starting fresh.",
                  file=sys.stderr)
            return default

    def _save_json(self, path, payload):
        """Atomic write with owner-only permissions."""
        _ensure_data_dir()
        tmp_path = path.with_suffix(path.suffix + '.tmp')
        try:
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump(payload, f, indent=2)
            tmp_path.replace(path)
        except OSError as e:
            print(f"Warning: could not save {path.name} ({e})", file=sys.stderr)

    def load_kb(self):
        kb = self._load_json(KB_FILE, {})
        if not isinstance(kb, dict):
            return {}
        # Normalize keys written by older versions ("show disk usage?").
        return {normalize_phrase(k): v for k, v in kb.items() if normalize_phrase(k)}

    def save_kb(self):
        self._save_json(KB_FILE, self.kb)

    def load_seed_kb(self):
        seed = self._load_json(SEED_KB_FILE, {})
        return {normalize_phrase(k): v for k, v in seed.items()} if isinstance(seed, dict) else {}

    def load_data(self):
        data = self._load_json(DATA_FILE, {'sequences': [], 'current': []})
        return data if isinstance(data, dict) else {'sequences': [], 'current': []}

    def save_data(self):
        self._save_json(DATA_FILE, self.data)

    # ---------- KB actions ----------

    def query(self, phrase):
        """Exact lookup: the user's own KB first, then the bundled seed KB.
        Kept as two sources (never merged) so the personal file only ever
        contains what the user taught or approved, and the seed set can be
        improved in an update without migrating anyone's data."""
        key = normalize_phrase(phrase)
        if not key:
            return ''
        if key in self.kb:
            return self.kb[key]
        return self.load_seed_kb().get(key, '')

    def suggest(self, phrase):
        """Closest known phrase for a near-miss ('show disk usage' vs 'show
        me disk usage'). Returns (phrase, command) or None. The caller must
        ask before running it - a near match is a guess, not an answer."""
        key = normalize_phrase(phrase)
        if not key:
            return None
        known = dict(self.load_seed_kb())
        known.update(self.kb)  # the user's own phrases win
        if key in known:
            return None
        by_meaning, perfect = self._suggest_by_meaning(key, known)
        # A partial match gives way to a tldr-pages example that covers
        # everything they said ("count words in a file" is wc -w, not
        # "count files in this folder").
        if by_meaning and not meaning_tokens(key) <= meaning_tokens(by_meaning[0]) \
                and self.suggest_example(key):
            by_meaning = None
        if perfect:
            # Same meaning, different words: better than a spelling match
            # ("find a file" is "search for a file", not "find big files").
            return by_meaning
        match = difflib.get_close_matches(key, list(known), n=1, cutoff=FUZZY_CUTOFF)
        if match and _only_typos(key, match[0]):
            return match[0], known[match[0]]
        return by_meaning

    def suggest_example(self, phrase):
        """When no known phrase is close: an example from tldr-pages whose
        description fits ('count words in a file' -> 'Count words in file',
        wc -w <file>). Returns (description, command) or None. Strict on
        purpose, and the caller must still ask before running it."""
        import tldr
        return tldr.match(phrase)

    def _suggest_by_meaning(self, key, known):
        """Match different wording with the same meaning ('remove a
        directory' -> 'delete a folder'). Returns ((phrase, command), perfect)
        or (None, False); `perfect` means every word lined up both ways."""
        wanted = meaning_tokens(key)
        if not wanted:
            return None, False
        best, best_rank = None, None
        for phrase in known:
            have = meaning_tokens(phrase)
            if not have:
                continue
            overlap = _weight(wanted & have)
            cand_cov = overlap / _weight(have)
            query_cov = overlap / _weight(wanted)
            if cand_cov < MEANING_CANDIDATE_COVERAGE or query_cov <= MEANING_QUERY_COVERAGE:
                continue
            rank = (cand_cov + query_cov,
                    phrase in self.kb,  # the user's own phrases win ties
                    not check_command(known[phrase]),  # then the less risky one
                    difflib.SequenceMatcher(None, key, phrase).ratio())
            if best_rank is None or rank > best_rank:
                best, best_rank = phrase, rank
        if best is None:
            return None, False
        return (best, known[best]), best_rank[0] >= 2.0

    def learn(self, phrase, command):
        """Learn a new phrase-command mapping."""
        key = normalize_phrase(phrase)
        command = (command or "").strip()
        if not key or not command:
            return False
        self.kb[key] = command
        self.save_kb()
        return True

    def forget(self, phrase):
        """Remove a phrase the user taught. Seed phrases can't be removed,
        but teaching the same phrase overrides them."""
        key = normalize_phrase(phrase)
        if key in self.kb:
            del self.kb[key]
            self.save_kb()
            return True
        return False

    def learned(self):
        return sorted(self.kb.items())

    # ---------- history / prediction ----------

    def log(self, command):
        if not command.strip():
            return False
        self.data.setdefault('current', []).append(command)

        if len(self.data['current']) >= SEQUENCE_FLUSH_LENGTH:
            if len(self.data['current']) > 1:
                self.data.setdefault('sequences', []).append(self.data['current'])
            self.data['current'] = []
            # Keep history bounded - old habits matter less than recent ones.
            self.data['sequences'] = self.data['sequences'][-MAX_SEQUENCES:]

        self.save_data()
        return True

    def predict(self, last_command):
        """Predict next command via simple frequency count over past sequences."""
        sequences = self.data.get('sequences', [])
        if len(sequences) < MIN_SEQUENCES_FOR_PREDICTION:
            return ''

        follow_counts = {}
        for seq in sequences:
            for i in range(len(seq) - 1):
                if seq[i] == last_command:
                    nxt = seq[i + 1]
                    follow_counts[nxt] = follow_counts.get(nxt, 0) + 1

        candidates = {k: v for k, v in follow_counts.items() if k != last_command}
        if not candidates:
            return ''
        return max(candidates, key=candidates.get)

    # ---------- helping you outgrow Clishe ----------

    def record_use(self, command, phrase=''):
        """Count how often each phrase is asked for and return any tips to
        show. The goal is for people to learn the commands: after a few
        uses Clishe shows the command to type directly, and it cheers once
        when someone does."""
        tips = []
        uses = self.data.setdefault('phrase_uses', {})
        key = normalize_phrase(phrase)
        if key:
            uses[key] = uses.get(key, 0) + 1
            template = self.query(key)
            if uses[key] in GRADUATION_TIP_AT and template:
                tip = (f'You\'ve asked for "{key}" {uses[key]} times. '
                       f'Next time you can type it yourself: {template}')
                if re.search(r"<[a-z]", template):
                    tip += " (fill in the <...> parts)"
                tips.append(tip)
        else:
            base = _command_name(command)
            if base:
                typed = self.data.setdefault('typed', {})
                typed[base] = typed.get(base, 0) + 1
            cheered = self.data.setdefault('cheered', [])
            command = command.strip()
            if command not in cheered and any(
                    self.query(p) == command for p in uses):
                cheered.append(command)
                tips.append(f"Nice, you typed {command} yourself instead of asking!")
        self.save_data()
        return tips

    def your_turn(self, phrase):
        """Should Clishe ask you to type this phrase's command yourself?
        Returns the command (template) if so, else ''."""
        mode = str(load_config().get("learn_mode", "gentle")).lower()
        if mode not in YOUR_TURN_AFTER:
            return ''
        key = normalize_phrase(phrase)
        template = self.query(key)
        if not template:
            return ''
        uses = self.data.get('phrase_uses', {}).get(key, 0)
        right = self.data.get('typed_right', {}).get(key, 0)
        if uses >= YOUR_TURN_AFTER[mode] and right < YOUR_TURN_UNTIL_RIGHT:
            return template
        return ''

    def attempt(self, phrase, typed):
        """Compare what you typed with the command for a phrase.
        Returns {"status": "right" | "close" | "wrong", "command"}.
        "close" means the right program with different options."""
        key = normalize_phrase(phrase)
        template = self.query(key)
        result = {"command": template}
        if not template:
            return dict(result, status="wrong")
        if same_command(typed, template):
            right = self.data.setdefault('typed_right', {})
            right[key] = right.get(key, 0) + 1
            self.save_data()
            return dict(result, status="right")
        want = _command_name(template)
        close = want and want == _command_name(typed)
        return dict(result, status="close" if close else "wrong")

    def progress(self):
        """What you've learned: commands you typed yourself, out of the basics."""
        typed = self.data.get('typed', {})
        learned = [c for c in BASICS if c in typed]
        others = sorted((c for c in typed if c not in BASICS), key=lambda c: -typed[c])
        asked = {_command_name(self.query(p)) for p in self.data.get('phrase_uses', {})}
        to_try = [c for c in BASICS if c in asked and c not in typed]
        next_up = [c for c in BASICS if c not in typed and c not in to_try]
        return {"learned": learned, "others": others, "total": len(BASICS),
                "to_try": to_try, "next": next_up[:3]}

    def cheat_sheet(self):
        """Your own cheat sheet: the commands you've typed yourself (in the
        form you use most, with what they do), and the phrases you still ask
        for. Returns {"learned": [(command, meaning)], "asked": [(phrase, command)]}."""
        import tldr
        from collections import Counter
        from breakdown import _short
        from knowledge import _COMMAND_DICT
        typed = self.data.get('typed', {})
        history = [c for seq in self.data.get('sequences', []) for c in seq] + self.data.get('current', [])
        forms = Counter(c.strip() for c in history if _command_name(c) in typed)
        learned = []
        for name in sorted(typed, key=lambda n: -typed[n]):
            uses = [(n, c) for c, n in forms.items() if _command_name(c) == name]
            # The form you use most; shorter on a tie.
            command = max(uses, key=lambda u: (u[0], -len(u[1])))[1] if uses else name
            meaning = tldr.summary(name) or (_COMMAND_DICT.get(name) or {}).get("summary", "")
            learned.append((command, _short(meaning)))
        asked = []
        for phrase, count in sorted(self.data.get('phrase_uses', {}).items(), key=lambda p: -p[1]):
            command = self.query(phrase)
            if command and _command_name(command) not in typed:
                asked.append((phrase, command))
        return {"learned": learned, "asked": asked}

    # ---------- the shell shortcut (clishe-bind.bash) ----------

    def resolve_line(self, text, use_ai=True):
        """Turn whatever is on the user's own prompt into something to put
        back there. Never runs anything. Returns a dict with:
          mode: 'command' (replace the line), 'explain' (print an
          explanation, keep the line) or 'none' (print a note)."""
        text = (text or "").strip()
        if not text:
            return {"mode": "none",
                    "note": "Type what you want in plain English, then press the key again."}

        command = self.query(text)
        if command:
            return self._line_result(command, "")

        words = text.split()
        if shutil.which(words[0]) and (
                len(words) == 1 or any(w.startswith(("-", "/", "./", "~")) for w in words[1:])):
            result = self.explain(text)
            if result["status"] == "ok":
                return {"mode": "explain", "explanation": result["explanation"]}

        match = self.suggest(text) or self.suggest_example(text)
        if match:
            return self._line_result(match[1], f'Closest thing I know: "{match[0]}"')

        if use_ai:
            result = self.resolve(text)
            if result["status"] == "ok":
                return self._line_result(result["command"], result["explanation"],
                                         provider=result["provider"])

        return {"mode": "none",
                "note": "I don't know that one yet. Run clishe to teach me, "
                        "or set up an AI provider (see the README)."}

    def _line_result(self, command, note, provider=""):
        return {"mode": "command", "command": command, "note": note,
                "provider": provider, "reasons": check_command(command)}

    def missing_program(self, text):
        """If the user typed a well-known program that isn't installed
        ("htop", "python script.py", "sudo nmap -sn ..."), return a hint on
        how to install it. Plain English ("go back") returns ''."""
        words = (text or "").split()
        if words[:1] == ["sudo"]:
            words = words[1:]
        if not words or words[0] not in POPULAR_PROGRAMS or shutil.which(words[0]):
            return ""
        if len(words) > 1 and not any(w.startswith(("-", "/", "./", "~")) or "." in w
                                      for w in words[1:]):
            return ""
        return missing_program_hint(words[0])

    def explain_output(self, command):
        """Guide to the output of the last command. Falls back to what the
        command itself does. Never sends the output anywhere."""
        if not (command or "").strip():
            return {"status": "none"}
        guide = output_guide(command)
        if guide:
            return {"status": "ok", "explanation": guide[1]}
        info = lookup_command(command)
        if info:
            return {"status": "ok", "explanation":
                    "I don't have a guide to this output yet, but here's what the command does:\n"
                    + format_explanation(info, command)}
        return {"status": "none"}

    def should_hint_guide(self, command):
        """True the first time ever that a command with an output guide
        succeeds, so people learn they can ask 'what does this mean?'."""
        guide = output_guide(command)
        if not guide:
            return False
        hinted = self.data.setdefault('guide_hinted', [])
        if guide[0] in hinted:
            return False
        hinted.append(guide[0])
        self.save_data()
        return True

    # ---------- trash instead of rm ----------

    def trash_command(self, command):
        """If `command` is a plain `rm` and a trash tool is installed, return
        the same files sent to the trash instead (so they can be restored).
        Returns {'command', 'restore', 'mode'} or None."""
        mode = str(load_config().get("trash", "ask")).lower()
        if mode == "never":
            return None
        tool = _trash_tool()
        if not tool:
            return None
        # Only simple, single commands: no pipes, chains, redirects or
        # command substitution that could change what gets deleted.
        if re.search(r"[;&|<>`]|\$\(", command):
            return None
        try:
            # posix=False keeps quotes and globs exactly as typed.
            words = shlex.split(command, posix=False)
        except ValueError:
            return None
        if not words or words[0] != "rm":
            return None
        files, end_of_flags = [], False
        for w in words[1:]:
            if not end_of_flags and w == "--":
                end_of_flags = True
            elif not end_of_flags and w.startswith("-"):
                continue
            else:
                files.append(w)
        if not files:
            return None
        if any(f.startswith("-") for f in files):
            files = ["--"] + files  # so "-name" stays a file, not an option
        return {"command": " ".join(tool[0] + files), "restore": tool[1], "mode": mode}

    # ---------- AI provider actions ----------

    def resolve(self, phrase):
        """Ask configured providers (in priority order) to translate an
        unknown phrase into a shell command. Returns a dict:
          {"status": "ok", "command": ..., "explanation": ..., "provider": ...}
          {"status": "declined", "provider": ...}   - model understood but wouldn't answer
          {"status": "unavailable"}                  - no provider could be reached

        NOTE: this does NOT write to the KB. Caching a suggestion before the
        user approves it would let a rejected or edited command silently
        become auto-executable next time. clishe.sh calls `--action learn`
        only after approval (and after the safety confirmation).
        """
        chain = build_provider_chain(load_config())
        from providers import ProviderError
        if not chain:
            return {"status": "unavailable"}

        for provider in chain:
            try:
                result = provider.resolve_with_explanation(phrase)
            except ProviderError as e:
                print(f"[{provider.name}] {e}", file=sys.stderr)
                continue  # try the next provider in the chain

            if result:
                manual, unverified = self.manual_notes(result.command)
                return {"status": "ok", "command": result.command,
                        "explanation": result.explanation, "provider": provider.name,
                        "manual": manual, "unverified": unverified}
            # This provider understood the request but declined (unclear or
            # unsafe). That's a real answer - don't shop it around.
            return {"status": "declined", "provider": provider.name}

        return {"status": "unavailable"}

    def explain(self, command):
        """Explain a shell command. Checks the offline built-in dictionary
        first (free, instant, no network) - only falls through to AI
        providers if the base command isn't in the dictionary."""
        import tldr
        from knowledge import _base_name
        name = os.path.basename(_base_name(command))
        examples = _examples_text(tldr.examples(name))

        entry = lookup_command(command)
        if entry:
            return {"status": "ok",
                    "explanation": format_explanation(entry, command) + examples,
                    "provider": "offline dictionary" + (" and tldr-pages" if examples else "")}

        # Any other command: tldr-pages' summary and examples, with the flags
        # explained from its manual on this computer. Still offline.
        summary = tldr.summary(name)
        if summary:
            from manual import check_flags
            notes = check_flags(command)
            flags = notes[0]["flags"] if notes else []
            parts = [summary]
            if flags:
                parts.append(f"In '{command.strip()}':\n" + "\n".join(
                    f"  {flag}  {text or '(not found in the manual)'}" for flag, text in flags))
            text = "\n".join(parts) + examples
            if notes:
                text += f"\nFull details: {notes[0]['source']}"
            return {"status": "ok", "explanation": text,
                    "provider": "tldr-pages" + (" and your system's manual" if notes else "")}

        # Any installed command: its own manual, still offline.
        from_manual = explain_from_manual(command)
        if from_manual:
            return {"status": "ok", "explanation": from_manual,
                    "provider": "your system's manual"}

        chain = build_provider_chain(load_config())
        from providers import ProviderError
        for provider in chain:
            try:
                explanation = provider.explain_command(command)
            except ProviderError as e:
                print(f"[{provider.name}] {e}", file=sys.stderr)
                continue

            if explanation:
                return {"status": "ok", "explanation": explanation, "provider": provider.name}

        return {"status": "unavailable"}

    def fix(self, command, error):
        """Why a command failed and how to fix it. Offline rules first (typos,
        missing sudo, scripts that aren't executable...), then the AI.
        Returns {"status": "ok", "explanation", "command", "provider",
        "unverified"} or {"status": "none"}."""
        from fix import offline_fix
        result = offline_fix(command, error)
        if result and result["command"]:
            return dict(result, status="ok", provider="offline", unverified=[])

        from providers import ProviderError
        for provider in build_provider_chain(load_config()):
            try:
                suggestion = provider.fix_command(command, error)
            except ProviderError as e:
                print(f"[{provider.name}] {e}", file=sys.stderr)
                continue
            if suggestion:
                _, unverified = self.manual_notes(suggestion["command"]) \
                    if suggestion["command"] else ([], [])
                return dict(suggestion, status="ok", provider=provider.name,
                            unverified=unverified)
            break
        if result:  # advice, but no single command to run
            return dict(result, status="ok", provider="offline", unverified=[])
        return {"status": "none"}

    def manual_notes(self, command):
        """Check an AI suggestion against the manuals on this computer.
        Returns (lines, unverified): what the manual says about each flag
        used, and the flags the manual doesn't mention (small models
        sometimes invent them)."""
        lines, unverified = [], []
        for note in check_flags(command):
            for flag, help_text in note["flags"]:
                if help_text:
                    lines.append(f"{note['name']} {flag}: {help_text}")
                else:
                    unverified.append(f"{note['name']} {flag}")
        return lines, unverified

    def diagnose(self, error_text):
        """Translate a command's stderr output into a plain-English hint,
        using offline pattern matching only - no AI call, since this needs
        to be instant and available even with no providers configured."""
        hint = diagnose_error(error_text)
        if hint:
            return {"status": "ok", "hint": hint}
        return {"status": "unmatched"}

    def check(self, command):
        """Safety check: reasons a command looks destructive (may be empty)."""
        reasons = check_command(command)
        return {"status": "danger" if reasons else "safe", "reasons": reasons}


# ---------- output helpers for clishe.sh ----------

def _examples_text(examples) -> str:
    """Examples from tldr-pages, as a block to put under an explanation."""
    if not examples:
        return ""
    lines = [f"  {what}\n    {command}" for what, command in examples]
    return "\nExamples (from tldr-pages):\n" + "\n".join(lines)

_PLACEHOLDER = re.compile(r"<[a-z]+(?: [a-z]+)*>")
_WRAPPER_WORDS = {"sudo", "doas", "env", "nice", "nohup", "time", "command"}


def _command_name(command: str) -> str:
    """The program a command line runs: "sudo df -h" -> "df"."""
    try:
        words = shlex.split(command or "")
    except ValueError:
        words = (command or "").split()
    while words and (words[0] in _WRAPPER_WORDS or re.match(r"^\w+=", words[0])):
        words = words[1:]
    return os.path.basename(words[0]) if words else ""


def _shape(words):
    """Command words in a form where "ls -la", "ls -al" and "ls -l -a" match:
    short flags become one sorted set, everything else keeps its order."""
    letters, rest = set(), []
    for w in words:
        if re.match(r"^-[A-Za-z]+$", w):
            letters.update(w[1:])
        else:
            rest.append(w)
    return letters, rest


def same_command(typed: str, template: str) -> bool:
    """True if `typed` is the template's command. Each <placeholder> matches
    whatever value you typed in its place ("cp notes.txt backup/" matches
    "cp <file> <destination>")."""
    holes = []

    def hole(m):
        holes.append(m.group(0))
        return f"\x00{len(holes) - 1}\x00"

    try:
        want = shlex.split(_PLACEHOLDER.sub(hole, template))
        got = shlex.split(typed)
    except ValueError:
        return typed.split() == template.split()
    want_flags, want_rest = _shape(want)
    got_flags, got_rest = _shape(got)
    if want_flags != got_flags or len(want_rest) != len(got_rest):
        return False
    for w, g in zip(want_rest, got_rest):
        pattern = ".+".join(re.escape(part) for part in re.split(r"\x00\d+\x00", w))
        if not re.fullmatch(pattern, g):
            return False
    return True

def _trash_tool():
    """(command words, how to get files back) for the first trash tool found."""
    # On a Mac, always macOS's own trash: Homebrew's gio reports success but
    # doesn't put files in the Mac's Trash.
    if sys.platform == "darwin" and shutil.which("trash"):
        return ["trash"], "Open the Trash in the Dock"
    if shutil.which("gio"):
        return ["gio", "trash"], "Open Trash in your file manager"
    if shutil.which("trash-put"):
        return ["trash-put"], "Run trash-restore"
    if shutil.which("trash"):  # built into macOS 15+, or from Homebrew
        return ["trash"], ("Open the Trash in the Dock" if sys.platform == "darwin"
                           else "Run trash-restore")
    return None


def _one_line(value: str) -> str:
    """Values are sent as single KEY=value lines. Multi-line commands become
    '; '-joined (same meaning to the shell for simple commands), so what the
    user sees is exactly what runs."""
    lines = [ln.strip() for ln in str(value).splitlines() if ln.strip()]
    return "; ".join(lines)


def _encoded(value: str) -> str:
    """For prose (explanations): keep line breaks as a literal \\n that
    clishe.sh turns back into newlines."""
    return str(value).replace("\r", "").replace("\n", "\\n")


# Each action the backend understands: a function that prints the KEY=value
# lines clishe.sh parses. Adding an action means writing the function and
# adding it to ACTIONS - argparse reads the choices from there, so there
# is no second list to keep in step.
def _action_query(brain, args):
    print(brain.query(args.phrase))


def _action_suggest(brain, args):
    match = brain.suggest(args.phrase)
    source = ""
    if not match:
        match = brain.suggest_example(args.phrase)
        source = "tldr-pages"
    if match:
        print("STATUS=ok")
        print(f"PHRASE={_one_line(match[0])}")
        print(f"COMMAND={_one_line(match[1])}")
        if source:
            print(f"PROVIDER={source}")
    else:
        print("STATUS=none")


def _action_learn(brain, args):
    ok = brain.learn(args.phrase, args.command)
    print('learned' if ok else 'error')


def _action_forget(brain, args):
    print('forgotten' if brain.forget(args.phrase) else 'unknown')


def _action_list(brain, args):
    for phrase, command in brain.learned():
        print(f"{phrase}\t{command}")


def _action_log(brain, args):
    ok = brain.log(args.command)
    print('logged' if ok else 'error')
    for tip in brain.record_use(args.command, args.phrase):
        print(f"TIP={_one_line(tip)}")
    if brain.should_hint_guide(args.command):
        print("GUIDE=1")
    prediction = brain.predict(args.command)
    if prediction:
        print(f"PREDICT={_one_line(prediction)}")


def _action_output(brain, args):
    result = brain.explain_output(args.command)
    print(f"STATUS={result['status']}")
    if result['status'] == 'ok':
        print(f"EXPLANATION={_encoded(result['explanation'])}")


def _action_line(brain, args):
    result = brain.resolve_line(args.phrase, use_ai=not args.no_ai)
    print(f"MODE={result['mode']}")
    for key in ('command', 'provider'):
        if result.get(key):
            print(f"{key.upper()}={_one_line(result[key])}")
    for key in ('note', 'explanation'):
        if result.get(key):
            print(f"{key.upper()}={_encoded(result[key])}")
    if result.get('reasons'):
        print(f"REASON={_encoded(chr(10).join(result['reasons']))}")


def _action_missing(brain, args):
    hint = brain.missing_program(args.command)
    print("STATUS=ok" if hint else "STATUS=none")
    if hint:
        print(f"HINT={_one_line(hint)}")


def _action_trash(brain, args):
    result = brain.trash_command(args.command)
    if result:
        print("STATUS=ok")
        print(f"COMMAND={_one_line(result['command'])}")
        print(f"RESTORE={_one_line(result['restore'])}")
        print(f"MODE={result['mode']}")
    else:
        print("STATUS=none")


def _action_turn(brain, args):
    command = brain.your_turn(args.phrase)
    print("STATUS=ask" if command else "STATUS=no")
    if command:
        print(f"COMMAND={_one_line(command)}")


def _action_attempt(brain, args):
    result = brain.attempt(args.phrase, args.command)
    print(f"STATUS={result['status']}")
    print(f"COMMAND={_one_line(result['command'])}")


def _action_progress(brain, args):
    result = brain.progress()
    print(f"LEARNED={' '.join(result['learned'])}")
    print(f"TOTAL={result['total']}")
    print(f"OTHERS={' '.join(result['others'])}")
    print(f"TO_TRY={' '.join(result['to_try'])}")
    print(f"NEXT={' '.join(result['next'])}")


def _action_setup(brain, args):
    import setup_check
    result = setup_check.check()
    for line in setup_check.report(result):
        print(f"LINE={line}")
    print(f"MODEL={result['model']}")
    print(f"RUNNING={int(result['ollama_running'])}")
    print(f"READY={int(result['model_ready'])}")
    print(f"CONFIGURED={result['configured_model']}")


def _action_set_model(brain, args):
    import setup_check
    print('saved' if setup_check.set_ollama_model(args.command) else 'error')


def _action_breakdown(brain, args):
    # With a phrase: only the first time it's used, so known phrases
    # don't redraw the same picture every time.
    key = normalize_phrase(args.phrase)
    if key and brain.data.get('phrase_uses', {}).get(key, 0) > 0:
        print("STATUS=skip")
    else:
        from breakdown import draw
        result = draw(args.command, width=args.width,
                      plain=bool(os.environ.get("CLISHE_PLAIN")))
        print("STATUS=ok" if result else "STATUS=none")
        if result:
            print(f"CMD={_one_line(result['command'])}")
            for tree, label in result['lines']:
                print(f"LINE={tree}\t{_one_line(label)}")


def _action_tour(brain, args):
    from tour import tour
    for stop in tour():
        print(f"STOP={_one_line(stop['title'])}")
        for label, value in stop['facts']:
            print(f"FACT={_one_line(label)}\t{_one_line(value)}")
        import textwrap
        for line in textwrap.wrap(stop['note'], width=max(40, args.width - 2)):
            print(f"NOTE={line}")
        if stop['try']:
            print(f"TRY={_one_line('   '.join(stop['try']))}")


def _action_fix(brain, args):
    result = brain.fix(args.command, args.error)
    print(f"STATUS={result['status']}")
    if result['status'] == 'ok':
        print(f"EXPLANATION={_encoded(result['explanation'])}")
        print(f"PROVIDER={result['provider']}")
        if result['command']:
            print(f"COMMAND={_one_line(result['command'])}")
        if result['unverified']:
            print(f"UNVERIFIED={_one_line(', '.join(result['unverified']))}")


def _action_inspect(brain, args):
    # "Is this safe to run?" for a command, or for a script file.
    import check
    text = check.read_script(os.path.expanduser(args.command.strip())) \
        if args.command.strip() and " " not in args.command.strip() else None
    if text is not None:
        result = check.check_script(text)
        print("MODE=script")
        print(f"LINES={len(result['results'])}")
        for effect in result['effects']:
            print(f"EFFECT={_one_line(effect)}")
        for risky in result['risky'][:20]:
            print(f"RLINE={_one_line(risky['command'])}")
            for warning in risky['warnings']:
                print(f"WARN={_one_line(warning)}")
    else:
        result = check.inspect(args.command)
        print("MODE=command")
        for effect in result['effects']:
            print(f"EFFECT={_one_line(effect)}")
        for warning in result['warnings']:
            print(f"WARN={_one_line(warning)}")
        for step in result['safer']:
            print(f"SAFER={_one_line(step)}")


def _action_undo_before(brain, args):
    import undo
    note = undo.before(args.command, args.cwd or os.getcwd())
    if note:
        print(json.dumps(note))


def _action_undo_record(brain, args):
    import undo
    try:
        note = json.loads(args.state)
    except ValueError:
        note = None
    record = undo.after(note, args.cwd or os.getcwd()) if isinstance(note, dict) else None
    if record:
        undo.save(UNDO_FILE, undo.load(UNDO_FILE) + [record])


def _action_undo_plan(brain, args):
    import undo
    records = undo.load(UNDO_FILE)
    if not records:
        print("STATUS=none")
    else:
        result = undo.plan(records[-1])
        print(f"STATUS={result['status']}")
        print(f"ORIGINAL={_one_line(records[-1]['command'])}")
        print(f"EXPLANATION={_one_line(result['explanation'])}")
        for command in result.get('commands', []):
            print(f"COMMAND={_one_line(command)}")


def _action_undo_done(brain, args):
    import undo
    undo.save(UNDO_FILE, undo.load(UNDO_FILE)[:-1])


def _action_lessons(brain, args):
    import lessons
    for pack in lessons.available():
        needs = f" (needs {', '.join(pack['missing'])})" if pack['missing'] else ""
        print(f"PACK={pack['name']}\t{pack['count']}\t{_one_line(pack['title'])}"
              f"\t{_one_line(pack['description'])}{needs}")


def _action_lesson(brain, args):
    import lessons
    pack = lessons.read(args.phrase)
    absent = lessons.missing(pack) if pack else []
    print("STATUS=" + ("none" if not pack else "missing" if absent else "ok"))
    for name in absent:
        from knowledge import missing_program_hint
        print(f"MISSING={_one_line(missing_program_hint(name))}")
    if pack and not absent:
        print(f"TITLE={_one_line(pack['title'])}")
        print(f"DONE={_one_line(pack.get('done', ''))}")
        for ex in pack['exercises']:
            print(f"TASK={_one_line(ex['task'])}")
            print(f"HINT={_one_line(ex['hint'])}")
            print(f"ANSWER={_one_line(ex['answer'])}")


def _action_lesson_check(brain, args):
    import lessons
    pack = lessons.read(args.phrase)
    ok = bool(pack) and 0 <= args.step < len(pack['exercises']) and lessons.passes(
        pack['exercises'][args.step]['check'], args.command, args.cwd or os.getcwd(), args.state)
    print("yes" if ok else "no")


def _action_app(brain, args):
    # "how do I install spotify?"
    import apps
    from config import detect_distro_family
    name = apps.wanted(args.phrase)
    app = apps.find(name) if name else None
    family = detect_distro_family()
    result = apps.plan(app, family) if app else (apps.tool_plan(name, family) if name else None)
    if not result:
        print("STATUS=none")
    elif result.get("installed"):
        print("STATUS=installed")
        print(f"APP={_one_line(result['app'])}")
    else:
        print("STATUS=ok")
        print(f"APP={_one_line(result['app'])}")
        print(f"HOW={_one_line(result['how'])}")
        if result['command']:
            print(f"COMMAND={_one_line(result['command'])}")
        for step in result['setup']:
            print(f"SETUP={_one_line(step)}")
        for other in result['others']:
            print(f"OTHER={_one_line(other)}")


def _action_doctor(brain, args):
    import doctor
    for check in doctor.run(os.environ.get("CLISHE_BASH", ""), os.environ.get("CLISHE_ON_PATH", ""),
                            os.environ.get("SHELL", "")):
        print("CHECK=" + "\t".join(_one_line(part) for part in check))


def _action_sheet(brain, args):
    sheet = brain.cheat_sheet()
    for command, meaning in sheet['learned']:
        print(f"LEARNED={_one_line(command)}\t{_one_line(meaning)}")
    for phrase, command in sheet['asked']:
        print(f"ASKED={_one_line(phrase)}\t{_one_line(command)}")


def _action_setting(brain, args):
    value = load_config().get(args.phrase, "")
    print(str(value).lower() if isinstance(value, bool) else value)


def _action_predict(brain, args):
    print(brain.predict(args.command))


def _action_resolve(brain, args):
    # Line-based KEY=value output so clishe.sh can parse it with plain
    # bash, no JSON tool required.
    result = brain.resolve(args.phrase)
    print(f"STATUS={result['status']}")
    if result['status'] == 'ok':
        print(f"COMMAND={_one_line(result['command'])}")
        print(f"EXPLANATION={_encoded(result['explanation'])}")
        print(f"PROVIDER={result['provider']}")
        if result.get('manual'):
            print(f"MANUAL={_encoded(chr(10).join(result['manual']))}")
        if result.get('unverified'):
            print(f"UNVERIFIED={_one_line(', '.join(result['unverified']))}")
    elif result['status'] == 'declined':
        print(f"PROVIDER={result['provider']}")


def _action_explain(brain, args):
    result = brain.explain(args.command)
    print(f"STATUS={result['status']}")
    if result['status'] == 'ok':
        print(f"EXPLANATION={_encoded(result['explanation'])}")
        print(f"PROVIDER={result['provider']}")


def _action_diagnose(brain, args):
    result = brain.diagnose(args.error)
    print(f"STATUS={result['status']}")
    if result['status'] == 'ok':
        print(f"HINT={_one_line(result['hint'])}")


def _action_check(brain, args):
    result = brain.check(args.command)
    print(f"STATUS={result['status']}")
    if result['reasons']:
        print(f"REASON={_encoded(chr(10).join(result['reasons']))}")


ACTIONS = {
    'query': _action_query,
    'suggest': _action_suggest,
    'learn': _action_learn,
    'forget': _action_forget,
    'list': _action_list,
    'log': _action_log,
    'output': _action_output,
    'line': _action_line,
    'missing': _action_missing,
    'trash': _action_trash,
    'turn': _action_turn,
    'attempt': _action_attempt,
    'progress': _action_progress,
    'setup': _action_setup,
    'set-model': _action_set_model,
    'breakdown': _action_breakdown,
    'tour': _action_tour,
    'fix': _action_fix,
    'inspect': _action_inspect,
    'undo-before': _action_undo_before,
    'undo-record': _action_undo_record,
    'undo-plan': _action_undo_plan,
    'undo-done': _action_undo_done,
    'lessons': _action_lessons,
    'lesson': _action_lesson,
    'lesson-check': _action_lesson_check,
    'app': _action_app,
    'doctor': _action_doctor,
    'sheet': _action_sheet,
    'setting': _action_setting,
    'predict': _action_predict,
    'resolve': _action_resolve,
    'explain': _action_explain,
    'diagnose': _action_diagnose,
    'check': _action_check,
}


def main():
    parser = argparse.ArgumentParser(description='Clishe Brain - Command Backend')
    parser.add_argument('--action', required=True,
                        choices=sorted(ACTIONS),
                        help='Action to perform')
    parser.add_argument('--phrase', default='', help='Natural language phrase')
    parser.add_argument('--command', default='', help='Bash command')
    parser.add_argument('--error', default='', help='Captured stderr text to diagnose')
    parser.add_argument('--no-ai', action='store_true', help='line: offline only')
    parser.add_argument('--width', type=int, default=80, help='breakdown: terminal width')
    parser.add_argument('--cwd', default='', help='undo: the folder the command runs in')
    parser.add_argument('--state', default='', help='undo: the note from undo-before; '
                                                    'lesson-check: the practice folder')
    parser.add_argument('--step', type=int, default=0, help='lesson-check: exercise number (0-based)')

    args = parser.parse_args()
    brain = ClisheBrain()
    ACTIONS[args.action](brain, args)


if __name__ == '__main__':
    main()
