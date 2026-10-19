# Changelog

## Unreleased

### Added
- **More plain-English error hints** for messages beginners get stuck on:
  `argument list too long`, `segmentation fault`, git's `non-fast-forward`
  and `refusing to merge unrelated histories`, and npm's `EACCES` permission
  error (which advises against `sudo` and points to a user-owned npm folder).

### Changed
- "Did you mean...?" is stricter: a known phrase is only offered when it
  covers more than half of what you typed, so it no longer drops the word
  that matters ("delete my photos" isn't offered "delete a file", "change
  my password" isn't offered `git diff`). On 267 test phrasings this cuts
  wrong suggestions from 38 to 23. "how much disk space is left" is now a
  known phrase.

## 0.9.0 (2026-10-19)

### Added
- **A man page**: `man clishe` now works, with the commands, the session
  words, the config file and where your data lives. It ships with the pip
  package and the Arch package.
- **`CLISHE_DEBUG=1`** shows Python error messages that Clishe normally
  hides, for tracking down a bug: `CLISHE_DEBUG=1 clishe`.
- **Two new lessons:** `clishe practice git` (13 exercises: init, config,
  status, add, commit, log, diff, all inside the throwaway folder) and
  `clishe practice processes` (ps, pipes with grep/sort/head, background
  jobs with & and jobs, kill, uptime). With several lessons, `practice`
  asks which one; type its number or its name. Lessons can list programs
  they need (`"needs": ["git"]`), and Clishe explains how to install a
  missing one instead of starting.
- **Two more lessons:** `clishe practice permissions` (9 exercises: read
  permissions with ls -l, make a script runnable with chmod +x and run it,
  make a file private with chmod 600) and `clishe practice archives` (9:
  pack, list and unpack with tar, then the same with zip and unzip).
- **`clishe sheet`**: your own cheat sheet. The commands you type yourself,
  in the form you use most, with what each does, and the things you still
  ask for with the command to type instead. Plain text, so
  `clishe sheet > cheatsheet.txt` saves it for printing.
- **`clishe doctor`** (or `doctor` in a session): checks Python, bash,
  whether `clishe` is on your PATH, the Ctrl+G shortcut for your shell,
  the config file (invalid JSON, misspelled settings), the data folder,
  `man`, the Trash, the bundled examples, your local AI (running? model
  downloaded? host on this computer?) and whether cloud AI is on. Each
  finding says how to fix it; it exits with 1 when something is broken.
  The bug report form now asks for its output.
- **Thousands of commands, offline, from tldr-pages** (CC BY 4.0, see
  NOTICE.md). `explain` now gives a plain-English summary and real
  examples for thousands of commands, with the flags you used explained
  from your own manual; commands in Clishe's dictionary gain examples too.
  The labels under commands use tldr's short summaries.
- **More requests answered offline.** When no known phrase fits, Clishe
  looks for a tldr-pages example whose description matches ("count words
  in a file" → `wc -w <file>`) and asks "Did you mean…?". Only everyday
  commands that are installed are offered, the request's action must match
  the example's, and every word you said must be covered.

### Changed
- **Importing Clishe no longer writes to your home folder.** Reading a
  Clishe function used to create `~/.config/clishe` and
  `~/.local/share/clishe` as a side effect, just by being imported. Both
  folders are now created the first time Clishe actually has something to
  save, so running the test suite - or anything else that imports a
  function - no longer leaves folders behind in your home directory.
- The optional Anthropic provider's default model is now `claude-haiku-5-5`.
  It is still off unless you turn it on, and a model already set in your
  config is left alone.
- PyPI now lists macOS and the tested Python versions (3.9, 3.11, 3.12).
- **Tab completion** in bash and zsh, turned on by the same
  `eval "$(clishe --init bash)"` line as Ctrl+G: `clishe <Tab>` lists what
  Clishe can do, `clishe practice <Tab>` the lessons, `clishe explain <Tab>`
  your commands, `clishe check <Tab>` your files.
- Adding a backend action is now a single step: each action is a
  `_action_<name>` function registered in `ACTIONS` in `clishe_brain.py`, and
  the `--action` choices are read from there. The old hand-kept list of action
  names (which had to be updated in two places) is gone. What each action
  prints is unchanged.

- A CI test that checks the practice folder is tidied up no longer depends
  on how fast the machine is. It waited a fixed 5 seconds for the cleanup
  before giving up, so on a loaded runner it could fail with the folder
  still there - it failed on the Python 3.9 job while passing on 3.11, 3.12
  and macOS. It now waits for the folder to actually go, and says on stderr
  how long things took if it ever fails again.
### Fixed
- On Windows (outside WSL), `clishe` now says it needs WSL and how to
  install it, instead of starting and then quietly doing nothing because
  its Python backend can't run there. This covers both the pipx install
  and running `clishe.sh` from Git Bash.
- The safety check now sees a dangerous command wherever it sits on the
  line: in a subshell `(rm -rf x)`, a group `{ rm -rf x; }`, after `!`,
  inside `if ... then`, `for ... do` and `while ... do`, and inside
  `$(...)`, `` `...` `` and `<(...)`. It also sees through `timeout 5s`
  and `busybox`. Text that is only printed (`echo '$(rm -rf /)'`) is
  still not flagged.
- `2>/dev/null` no longer confuses the safety check:
  `mv important.txt /dev/null 2>/dev/null` is now flagged, and
  `mv notes.txt ~ 2>/dev/null` no longer is.
- Install one-liners that run a download without a pipe now get the same
  warning as `curl ... | sh`: `bash -c "$(curl -fsSL ...)"` (the Homebrew
  installer), `sh <(curl ...)`, `source <(curl ...)` and
  `eval "$(curl ...)"`, with wget too. `clishe check` shows the safer way
  for them (download, read, check). Showing or saving a download
  (`echo "$(curl ...)"`, `x=$(curl ...)`) is still not flagged.
- More destructive commands now ask for a typed YES, with the reason:
  `rsync --delete` (and `--delete-before`/`-after`/`-during`/`--del`),
  which deletes files from the destination; `kill -9 -1` and
  `pkill -u $USER`, which stop every program you're running at once;
  `systemctl poweroff`/`reboot`/`halt`/`suspend`; `cp /dev/null file`,
  which empties the file; and two more ways to run a download unread,
  `bash < <(curl ...)` and an unquoted `bash -c $(curl ...)`. Copying with
  rsync, `kill 1234`, `systemctl status` and `cp file /dev/null` are still
  not flagged.
- `clishe doctor` no longer reports "Can't write to the data folder" on a
  fresh install, where the folder has simply not been created yet. It says
  so as a note instead, and still fails if the folder exists but can't be
  written to, or couldn't be created at all.
- Closing the terminal in the instant `practice` was starting could leave
  its throwaway folder behind. The tidy-up is now in place before the
  folder is made.
- A config file that holds valid JSON of the wrong kind (a list, a word,
  `null`) no longer stops Clishe with a Python error; AI is switched off and
  everything offline keeps working, as with any other broken config.
- A config moved from the old `~/.clishe_config.json` is now made readable
  only by you, since it may hold an API key.
- "Did you mean…?" no longer offers a phrase that only looks alike:
  "count words in a file" was offered "count lines in a file". Spelling
  matches now only count when the differing words are typos of each other
  ("show disk usge" still finds "show me disk usage").
- Practice no longer leaves its throwaway folder behind when it's stopped
  early. Ctrl-C at the practice prompt now ends practice like "quit"
  (progress saved, folder removed), and closing the terminal or a shutdown
  removes the folder too. Folders that still couldn't be removed (a crash,
  `kill -9`) are swept up the next time practice starts: only Clishe's own
  practice folders, owned by you and untouched for a day.

## 0.8.0 (2026-10-08)

### Added
- **Plain mode** for screen readers and simple terminals: `clishe --plain`,
  `CLISHE_PLAIN=1`, or `"plain": true` in the config. Words instead of
  symbols ("Tip:", "Warning:", "OK:" for 💡 ⚠ ✓), a one-line welcome, and
  each command explained as a "part: meaning" list in reading order instead
  of the drawn tree. The Ctrl+G shortcut follows `CLISHE_PLAIN` too.
- **"How do I install Spotify?"** (also "install vs code", "get vlc",
  "download zoom"): for about 25 popular desktop apps, Clishe shows the
  right way to install them here. It prefers the distro's own package
  (apt, dnf or pacman) when the app is in its official repositories,
  otherwise Flathub, adding the one-time Flatpak and Flathub setup for your
  distro if it's missing, and a Homebrew cask on a Mac. Well-known
  command-line tools (`install htop`) get the package manager's command, or
  "already installed". It asks before running anything. The list is
  `apps.json`, easy to extend.
- **Lesson packs.** Practice exercises now live in JSON lesson files
  (`lessons/basics.json` is the built-in one), so teachers, workshops and
  contributors can write lessons without touching code. Your own lessons go
  in `~/.local/share/clishe/lessons/`. `clishe practice <lesson>` runs one,
  `clishe practice --list` shows them, and with several lessons `practice`
  asks which. Each lesson keeps its own progress. Checks are data (a folder
  exists, a file contains some text, what you typed matches...), never
  code, and never look outside the practice folder. A test replays every
  bundled lesson's answers to make sure each one can be finished.

## 0.7.0 (2026-10-08)

### Added
- **`undo that`** (also "undo", "take that back"): reverses the last change,
  showing the commands first and asking before running them. Undoes `mv`
  (moves it back), `mkdir` (rmdir while empty, `-p` parents too), `touch`
  (removes the file while it's still empty), `cp` (sends the copy to the
  Trash if it hasn't changed), `chmod` (old permissions), `cd` (back), and
  moving files to the Trash (restored from the freedesktop Trash; on macOS,
  which hides the Trash from terminal programs, it explains Finder's Put
  Back). Package installs get the matching remove command. It refuses
  rather than guess when anything has changed since, and says plainly that
  a plain `rm` can't be undone. Up to the last 10 changes are remembered.
- **`clishe check`**: "is this safe to run?" for a command or a script file,
  without running it. It explains each part, says what it would change
  (files created, replaced or deleted, software installed, sudo, services,
  which websites it contacts) and shows any risky lines. For downloaded
  scripts piped into a shell it gives a safer way: download, read, check.
  Exits with 1 when there are warnings. In a session: `is this safe:
  <command>` or `check <command>` (phrases like "check my ip address" still
  work as before).
- **macOS support.** Clishe now runs with the bash 3.2 that macOS ships:
  `mapfile`, `read -i` and a bash-version-dependent substitution were
  replaced. Install hints use Homebrew, the AI is told about macOS's BSD
  tools, deleted files can go to the Trash (macOS's `trash` command), and
  `clishe tour` describes your Mac. CI now runs every test on macOS too.

### Changed
- Commands like `mv notes.txt drafts` and `touch new.txt` are now run as
  commands. Before, `mv`/`cp`/`rm` with three or more words, and `touch`
  with a file that didn't exist yet, were read as English.
- On macOS, deleting with the Trash uses macOS's own `trash` command even
  when Homebrew's `gio` is installed: gio reports success there but the
  files don't show up in the Mac's Trash.
- Editing a suggested command on bash 3.2 shows the command and lets you
  type a new one (Enter keeps it); bash 4+ still puts it on the line.

## 0.6.0 (2026-10-07)

### Added
- **Ctrl+G in zsh.** Add `eval "$(clishe --init zsh)"` to `~/.zshrc` and the
  shortcut works the same as in bash: plain English becomes the command on
  your line, the cursor lands on the first `<placeholder>`, real commands
  get explained, and risky ones get a warning. `clishe --init` with no
  shell name picks the one you're using.
- **`fix that`** (also "what went wrong", "why did that fail"): after a
  command fails, Clishe explains why and offers a fixed command, run
  through the usual safety check. Offline fixes for common mistakes: a
  misspelled command (`gti` → `git`, `sl` → `ls`), a misspelled file or
  folder, a missing `sudo`, a script that isn't executable, `cp` on a
  folder without `-r`, `cat` on a folder, an out-of-date apt package list.
  Anything else goes to your local AI, and its fix is checked against the
  man page. For `rm`, `mv` and other destructive commands it never puts a
  guessed file name in the fix. After a failed command, a hint mentions
  `fix that`.
- **`clishe tour`** (or `tour` in a session): a walk through your own
  computer in plain English, one stop at a time. Your Linux and what it's
  based on, processor and memory, free disk space, desktop and shell, what
  the main folders are for, how software is installed, and whether you can
  use sudo. Each stop has commands to try. Offline: it reads /etc, /proc
  and the environment.
- **Every part labelled.** AI suggestions, and known phrases the first
  time you use them, are drawn with each part of the command labelled
  underneath (`find` → search for files, `-size +100M` → bigger than 100M).
  Options written together get a line each (`-xzvf` → `-x`, `-z`, `-v`,
  `-f`). Labels come from the offline dictionary and your man pages.
  Commands with pipes or redirects, or too wide for the terminal, are
  shown the usual way.

### Changed
- "Clishe:" is now bright blue. The dark blue was hard to read on dark
  terminal themes, such as Ubuntu's.

## 0.5.1 (2026-10-05)

### Added
- **Install with pipx:** `pipx install git+https://github.com/Sym-jay/clishe`
  (or `uv tool install`), no curl-into-bash needed. CI now installs the
  package and runs it on every change.
- A PyPI publishing workflow that runs on each GitHub release, so
  `pipx install clishe` works once the project is set up on PyPI.
- An Arch User Repository package (`packaging/aur/`), ready to submit.
- First release on PyPI: `pipx install clishe`.

## 0.5.0 (2026-10-05)

### Added
- **`clishe setup`.** Checks your memory and suggests a local model that
  fits, finds Ollama and other local model servers, and can download the
  model (`ollama pull`) and save it in the config. It also says plainly
  whether anything could be sent to the internet.
- **Any local model server.** Besides Ollama, Clishe now works with
  llama.cpp's `llama-server`, LM Studio, Jan, LocalAI, vLLM and anything
  else with an OpenAI-style API. It finds a running server on the usual
  ports and uses its first model, so there's usually nothing to configure.
- Linux derivatives get the right package manager: the AI is told the
  distro your system is based on (Mint and Pop!_OS get `apt`).
- Every model, local or cloud, now gets the same safety instructions
  (decline unclear or destructive requests, use `<placeholders>`). Before,
  Ollama got a shorter prompt without them.
- **Explain any installed command, offline.** When a command isn't in the
  offline dictionary, `explain` reads your system's own manual (`man`, or
  `--help` when there's no man page) and shows its one-line summary and
  the description of each flag you used. AI is asked only when there's no
  manual. Flags missing from the dictionary are filled in from the manual
  too.
- **AI suggestions are checked against the manual.** Each suggestion shows
  what your manual says about its flags, and warns about any flag the
  manual doesn't mention, which is how small local models usually go wrong.
- **Your turn.** After you've asked for a phrase three times (and seen the
  tip with its command), Clishe asks you to type it yourself and checks
  your answer: `ls -al` counts for `ls -la`, and `cp notes.txt backup/`
  counts for `cp <file> <destination>`. A wrong answer shows the command
  and runs it as usual. After two right answers it stops asking. New
  `"learn_mode"` config option: `gentle` (default), `always`, `off`.
- **`practice`**: 14 hands-on exercises in a throwaway folder, from `pwd`
  to `rm -r`, each checked after every command you type, with hints and
  answers. It picks up where you left off.
- **`progress`**: which everyday commands you've typed yourself, which
  ones you still ask for, and what to learn next.
- `clishe practice` and `clishe progress` work from your normal shell too.
- 16 bundled git phrases for beginners ("what did i change", "undo my
  last commit", "which branch am i on"...), chosen so none of them throws
  away work. Thanks @nawaaaaaAaar (#13).

### Changed
- **Local only by default.** The Anthropic provider is now opt-in:
  set `"enabled": true` under `"anthropic"` to use it. An
  `ANTHROPIC_API_KEY` in your environment no longer turns it on by itself.
  Existing configs with a key typed into the config file keep working.
- Model servers outside your computer and local network are refused unless
  you set `"allow_remote_ai": true`, so a typo in a host can't send your
  phrases to the internet.

## 0.4.0 (2026-10-05)

### Added
- **"What does this mean?"** After `ls -l`, `df`, `du`, `free`, `ps`,
  `uptime`, `hostname -I`, `ip`, `ss`, `lsblk`, `wc`, `git status` or
  `git log`, ask and Clishe explains the output's columns in plain English.
  Offline; the output itself is never sent anywhere. A one-time hint shows
  the first time each of these runs.
- **Install hints for your distro.** "command not found", or typing a
  well-known program that isn't installed (`htop`, `nmap`, `tree`...), now
  says the install command for your package manager (apt, dnf, pacman,
  zypper, apk), including packages with different names (`dig` is
  `dnsutils` on Ubuntu, `bind-utils` on Fedora). `python` points to
  `python3`.
- More errors explained: pip's externally-managed-environment, apt without
  sudo, "Unable to locate package", interrupted dpkg, not in sudoers,
  "not a git repository", SSH key rejected, no internet / DNS failures.
- A friendly first run: five things to try, instead of a blank prompt.
- "go back" goes to the previous folder (`cd -`).
- **Ctrl+G in your normal shell.** Add `eval "$(clishe --init bash)"` to
  `~/.bashrc`, type plain English at any prompt and press Ctrl+G: the line
  becomes the command, with the cursor on the first `<placeholder>`. On a
  real command it explains the flags instead. It never runs anything.
- **Trash instead of rm.** When you delete with `rm` and `gio` or
  `trash-cli` is installed, Clishe offers to move the files to the Trash so
  you can get them back. New `"trash"` config option: `ask` (default),
  `always`, `never`.
- **Learning tips.** After asking for the same phrase 3 (and 10) times,
  Clishe shows the command to type yourself, and cheers once when you do.
- "Did you mean...?" now matches on meaning, not just spelling: "remove a
  directory" finds "delete a folder", "how much disk is left" finds "how much
  space do i have". It uses a small synonym table, stays offline and still
  asks before running. A match never adds an action you didn't ask for, and
  on a tie the less risky command wins.
- 30 more bundled phrases (disk partitions, CPU info, open ports, zip/unzip,
  file details, services, logs and more).

### Fixed
- A taught or AI-suggested command is now saved only after it runs
  successfully. Before, a wrong command (say, a program that isn't
  installed) was saved first and then came back every time.
- Clishe's own internal functions (`say`, `warn`, `brain`...) were treated
  as commands, so typing "say hi" ran Clishe's code instead of being read
  as English.
- On machines with Go installed, "go back" ran the `go` program. `go` now
  counts as a command only before a real Go subcommand (`go build`,
  `go test`, `go mod tidy`...).
- About twice as fast: the AI provider code (and its network libraries) is
  loaded only when an AI is actually asked, and logging and next-command
  prediction are one call instead of two.
- The safety check now also catches `rm *` (and `rm ./*`, `rm dir/*`),
  emptying a file with `> file` or `truncate -s 0`, commands hidden in
  `bash -c '...'`, `su -c '...'` and `eval`, scripts piped into `python3`,
  `perl`, `ruby` or `node`, and `cp`/`tee` onto a disk device.
  `rm *.log`, `echo hi > out.txt` and `>> file` are still not flagged.
- `teach` now runs the safety check before saving, as the README says, so a
  risky command needs a typed YES to be saved.
- README: "shows its work" now describes what actually asks before running.
- The safety check now also catches moving your home folder or a system
  folder (`mv ~ /tmp/x`), a command hidden in a variable set on the same line
  (`x=rm; $x -rf /`), and code passed straight to an interpreter that deletes
  files or runs a risky shell command (`python3 -c "shutil.rmtree(...)"`,
  `perl -e 'unlink ...'`, `node -e "fs.rmSync(...)"`).
- "what's my ip" now answers offline with your local address
  (`hostname -I`). "what's my public ip" still asks the internet.
- Removed the bundled "check disk speed" phrase, which ran `sudo hdparm` on
  a disk: not something to hand a beginner without context.

## 0.3.0

### Fixed
- Piping input into Clishe (or pressing Ctrl-D) no longer spins forever at
  end of input; the session now says goodbye and exits.
- Ctrl-C stops the running command (for example `ping` or `top`) instead of
  killing Clishe.
- Seed phrases that ran incomplete commands are fixed. "show file contents"
  used to run a bare `cat`, which hung waiting for input; `kill -9`,
  `find . -name`, `tar -czvf`, `wget` and others failed with usage errors.
- Commands are printed with `printf %s` instead of `echo -e`, so a command
  containing `\n` or other escapes is shown exactly as it will run.
- A command is saved to your knowledge base only after it passes the safety
  check, so cancelling a destructive-command warning no longer leaves the
  command saved.
- The destructive-command check caught `rm -rf` but not `rm -fr`,
  `rm -r -f`, `rm --recursive`, `chmod -R 755 /`, `>/dev/sda` without a space,
  and similar variants.

### Added
- `safety.py`: a parser-based destructive-command check that explains *why*
  a command is risky. Also covers disk partitioning, `shred`,
  `find -delete`, `curl ... | sh`, fork bombs with any name,
  `git reset --hard`, `git clean -f`, force-push, shutdown/reboot and
  `crontab -r`.
- `<placeholder>` templates: commands like `cp <file> <destination>` prompt
  for each value and quote it safely. AI providers are asked to use them
  for missing values, and you can teach your own.
- "Did you mean ...?" offline fuzzy matching against known phrases, and
  forgiving matching that ignores case, punctuation and filler words.
- AI suggestions show the model's one-line explanation.
- `explain` breaks down the exact flags used (`tar -xzvf` → `-x`, `-z`,
  `-v`, `-f`), including old-style `tar xzvf` and unknown flags.
- Session commands: `help`, `learned`, `teach`, `forget <phrase>`.
- Arrow-key line editing and input history that persists across sessions.
- `clishe --version` and `clishe --list`; `NO_COLOR` support.
- When no AI provider is reachable, the underlying error is shown.
- More seed phrases (folder sizes, rename, compare files, and more).
- `LICENSE` file (the README already said MIT).

### Changed
- Data files (`kb.json`, `history.json`, input history) are written with
  owner-only permissions, and history is capped so it stays small.
- Provider JSON parsing is shared and tolerates chatter around the JSON,
  which small local models often add.
- Version numbers are unified (the banner said 1.3, `pyproject.toml` said
  0.2.0); a test keeps them in sync. Minimum Python is 3.9 everywhere.
- Shell tests now source `clishe.sh` and test the real functions instead of
  copies. CI runs shellcheck.
