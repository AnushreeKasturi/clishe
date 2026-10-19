#!/bin/bash
# Clishe - Natural Language Command Line Interface

CLISHE_VERSION="0.8.0"

# Colors (off when output isn't a terminal, or when NO_COLOR is set -
# see https://no-color.org).
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    GREEN='\033[0;32m'
    BLUE='\033[0;94m'   # bright blue: dark blue is hard to read on dark themes
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    DIM='\033[2m'
    NC='\033[0m' # No Color
else
    GREEN='' BLUE='' YELLOW='' RED='' DIM='' NC=''
fi

# Plain mode (--plain, CLISHE_PLAIN=1, or "plain": true in the config):
# words instead of symbols and pictures, for screen readers and simple
# terminals.
PLAIN="${CLISHE_PLAIN:-}"
if [ "${1:-}" = "--plain" ]; then
    PLAIN=1
    shift
fi
set_symbols() {
    if [ -n "$PLAIN" ]; then
        ICON_TIP="Tip:" ICON_WARN="Warning:" ICON_OK="OK:" ICON_CHEER="" ICON_BULLET="-"
        ICON_NOTE="Note:" ICON_FAIL="Problem:"
        export CLISHE_PLAIN=1   # so the brain draws lists, not trees
    else
        ICON_TIP="💡" ICON_WARN="⚠" ICON_OK="✓" ICON_CHEER="🎉 " ICON_BULLET="•"
        ICON_NOTE="!" ICON_FAIL="✗"
    fi
}
set_symbols

# Resolve the real script location even when invoked through a symlink
# (the one-line installer symlinks clishe.sh into ~/.local/bin/clishe).
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/clishe_brain.py"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/clishe"
INPUT_HISTORY_FILE="$DATA_DIR/input_history"

# ---------- Input routing tables ----------
# Real commands that are also everyday English words. Beginners type these
# at the start of plain sentences ("find my photos", "install htop",
# "help me set up ssh"), so they only count as commands when the line also
# has flags, paths or operators.
AMBIGUOUS_WORDS=" find make install kill open cut look more watch test time mail write wait yes sort touch cat head tail who join split paste fold nice help read let set locate show say "

# Programs whose normal form is "<program> <subcommand> <args>", e.g.
# "git status" or "systemctl status nginx". Several plain words after these
# are still a command, not a sentence.
TOOL_COMMANDS=" git apt apt-get dnf yum pacman zypper apk systemctl journalctl docker pip pip3 npm snap flatpak brew "

# "go" is both the Go toolchain and an English verb ("go back"). It's a
# command only when a real go subcommand follows.
GO_SUBCOMMANDS=" build run test mod get install fmt vet env version doc generate list work clean tool help bug fix "

# Destructive commands followed by several plain words ("rm the old files")
# read like a sentence. Let the AI interpret them instead of treating the
# words as file names.
CAUTION_WORDS=" rm mv cp shred ln chmod chown "

# Patterns for "explain"-style questions (matched case-insensitively).
RE_FILLER='^(okay|ok|so|well|hey|um|please),?[[:space:]]+(.*)$'
RE_EXPLAIN='^explain[[:space:]]+(.+)$'
RE_WHAT_DOES='^what[[:space:]]+does[[:space:]]+(.+)[[:space:]]+do\??$'
RE_WHAT_IS='^what[[:space:]]+(is|are)[[:space:]]+(.+)$'
RE_WHATS="^what's[[:space:]]+(.+)\$"
RE_TELL_ME='^tell[[:space:]]+me[[:space:]]+about[[:space:]]+(.+)$'
# "what does this mean?" about the output of the last command.
# "how do I install spotify?" / "install vs code" / "get vlc"
RE_INSTALL_APP="^(how (do i|do you|to|can i) )?(install|get|download) "
# "is this safe?" before running something found online.
RE_SAFE_QUESTION="^is (this|it|that) safe( to run)?[?:]*[[:space:]]*(.*)\$"
# "fix that" after a command fails.
RE_FIX="^(fix (that|it|this)|what went wrong|why did (that|it) fail|why didn'?t (that|it) work|help me fix (that|it))[?!. ]*\$"
RE_OUTPUT_QUESTION="^(what (does|do) (this|that|it|these|those) mean|explain (this|that|it|the output)|what am i looking at|i don'?t understand( (this|that|it))?)[?!. ]*\$"

# A placeholder in a KB or AI command, e.g. "cp <file> <destination>".
# Lowercase words only, so real redirections like "sort <in.txt" aren't
# mistaken for one.
RE_PLACEHOLDER='<([a-z]+( [a-z]+)*)>'
# Placeholder answers made only of these characters are used as typed.
RE_SAFE_VALUE='^[A-Za-z0-9_./~+:=@%,${}-]+$'

# Check dependencies
if ! command -v python3 &> /dev/null; then
    printf '%bError: python3 is required but was not found on this system.%b\n' "$RED" "$NC"
    exit 1
fi

if [ ! -f "$PYTHON_SCRIPT" ]; then
    printf '%bError: %s not found next to this script.%b\n' "$RED" "$PYTHON_SCRIPT" "$NC"
    exit 1
fi

# ---------- Output helpers ----------
# User and AI text is always printed with %s, never through echo -e, so a
# command like  printf 'a\nb'  is shown exactly as it will run.

# say "message"            -> "Clishe: message"
say() { printf '%bClishe: %b%s\n' "$BLUE" "$NC" "$1"; }

# say_cmd "label" "command" -> "Clishe: label command" (command highlighted)
say_cmd() { printf '%bClishe: %b%s%b%s%b\n' "$BLUE" "$NC" "$1" "$YELLOW" "$2" "$NC"; }

warn() { printf '%b%s%b\n' "$YELLOW" "$1" "$NC"; }

# CLISHE_DEBUG=1 lets Python's error messages through (for finding bugs).
brain() {
    if [[ -n "${CLISHE_DEBUG:-}" ]]; then
        python3 "$PYTHON_SCRIPT" "$@"
    else
        python3 "$PYTHON_SCRIPT" "$@" 2>/dev/null
    fi
}

# ---------- Functions ----------

usage() {
    cat <<'EOF'
Clishe - describe what you want in plain English.

Usage:
  clishe                    start an interactive session
  clishe explain <command>  explain what a command does, then exit
  clishe "<phrase>"         look up a phrase in your knowledge base (does not run it)
  clishe --list             show the phrases you've taught
  clishe practice [lesson]  hands-on exercises in a safe, throwaway folder
                            (clishe practice --list shows the lessons)
  clishe progress           the commands you've learned to type yourself
  clishe setup              find or set up a local AI model
  clishe tour               a quick tour of your computer
  clishe doctor             check your setup, and how to fix anything wrong
  clishe sheet              your own cheat sheet (save: clishe sheet > cheatsheet.txt)
  clishe check '<command>'  is it safe to run? (or: clishe check script.sh)
  clishe --init bash|zsh    print the Ctrl+G shortcut (and Tab completion) for your normal shell
                            (add  eval "$(clishe --init bash)"  to ~/.bashrc,
                             or   eval "$(clishe --init zsh)"   to ~/.zshrc)
  clishe --plain ...        words instead of symbols and drawings (screen readers);
                            or set "plain": true in ~/.config/clishe/config.json
  clishe --version          show the version
  clishe --help             show this help

Inside a session, also try: help, learned, teach, forget <phrase>, practice,
progress, setup, tour, exit
EOF
}

session_help() {
    cat <<'EOF'
Type what you want in plain English ("show me disk usage"), or any normal
shell command. Clishe shows you the command before it runs.

  explain <command>   what does a command do? (also: "what does ls do")
  what does this mean  explain the output of the command you just ran
  fix that            explain why the last command failed, and fix it
  undo that           reverse the last change (mv, cp, mkdir, touch, chmod, cd, Trash)
  check <command>     is it safe? what would it change? (also a script file)
  learned             list the phrases you've taught me
  teach               teach me a phrase -> command (or fix a wrong one)
  forget <phrase>     forget a phrase you taught me
  practice            hands-on exercises in a safe, throwaway folder
  progress            the commands you've learned to type yourself
  setup               find or set up a local AI model
  tour                a quick tour of your computer
  doctor              check your setup, and how to fix anything wrong
  sheet               your own cheat sheet of the commands you've learned
  help                show this message
  exit                leave (Ctrl-D works too)

Commands with <placeholders>, like "cp <file> <destination>", ask you to
fill in each value before running.

After you've asked for the same thing a few times, I'll ask you to type the
command yourself. Set "learn_mode" to "always" or "off" in the config to
change that.

Want this in your normal shell too? Add this line to ~/.bashrc:
  eval "$(clishe --init bash)"
(or, for zsh, eval "$(clishe --init zsh)" to ~/.zshrc)
Then type plain English at any prompt and press Ctrl+G.
EOF
}

# Parse "KEY=value" lines from clishe_brain.py into shell variables named
# <prefix>_STATUS, <prefix>_COMMAND, etc.
#   parse_brain_output "$output" RS
parse_brain_output() {
    local output="$1"
    local prefix="$2"
    local key value k
    # Reset first, so an empty or failed call can't leave the previous
    # call's STATUS or COMMAND behind.
    for k in STATUS COMMAND PROVIDER EXPLANATION HINT REASON PHRASE RESTORE MODE MANUAL UNVERIFIED; do
        printf -v "${prefix}_${k}" '%s' ""
    done
    while IFS='=' read -r key value; do
        case "$key" in
            STATUS|COMMAND|PROVIDER|EXPLANATION|HINT|REASON|PHRASE|RESTORE|MODE|MANUAL|UNVERIFIED)
                printf -v "${prefix}_${key}" '%s' "$value" ;;
        esac
    done <<< "$output"
}

# Turn the literal "\n" sequences the brain uses for line breaks back into
# real newlines.
decode_lines() { printf '%s' "${1//\\n/$'\n'}"; }

# Show why a command is risky and require a typed YES.
#   confirm_dangerous "<command>" [run|save]
# Returns 0 to go ahead, 1 to cancel.
confirm_dangerous() {
    local cmd="$1"
    local verb="${2:-run}"
    local output confirm reason
    output=$(brain --action check --command "$cmd")
    parse_brain_output "$output" CK

    if [ "$CK_STATUS" = "safe" ]; then
        return 0
    fi

    if [ "$CK_STATUS" = "danger" ]; then
        printf '%b%s This command looks potentially destructive:%b\n' "$RED" "$ICON_WARN" "$NC"
        printf '  %b%s%b\n' "$YELLOW" "$cmd" "$NC"
        while IFS= read -r reason; do
            [ -n "$reason" ] && printf '  - It %s.\n' "$reason"
        done <<< "$(decode_lines "$CK_REASON")"
    else
        # The safety check itself failed to run. Fail closed.
        printf '%b%s I could not run my safety check on:%b\n' "$RED" "$ICON_WARN" "$NC"
        printf '  %b%s%b\n' "$YELLOW" "$cmd" "$NC"
    fi
    read -r -p "Type YES to $verb it anyway, anything else to cancel: " confirm
    if [ "$confirm" != "YES" ]; then
        say "Cancelled."
        return 1
    fi
    return 0
}

# Quote a value typed into a placeholder so spaces and globs arrive intact:
#   report.pdf -> report.pdf      my notes.txt -> 'my notes.txt'
#   *.log      -> '*.log'         ~/My Files   -> ~/'My Files'
# shellcheck disable=SC2088  # the literal "~/" is intentional here
quote_value() {
    local v="$1"
    local sq="'"
    local esc="'\\''"
    if [[ "$v" =~ $RE_SAFE_VALUE ]]; then
        printf '%s' "$v"
    elif [[ "$v" == "~/"* ]]; then
        local rest="${v#\~/}"
        printf "~/'%s'" "${rest//$sq/$esc}"
    else
        printf "'%s'" "${v//$sq/$esc}"
    fi
}

# List the distinct placeholder names in a command, one per line, in order.
list_placeholders() {
    local rest="$1" seen=$'\n' label
    while [[ "$rest" =~ $RE_PLACEHOLDER ]]; do
        label="${BASH_REMATCH[1]}"
        if [[ "$seen" != *$'\n'"$label"$'\n'* ]]; then
            printf '%s\n' "$label"
            seen+="$label"$'\n'
        fi
        rest="${rest#*"${BASH_REMATCH[0]}"}"
    done
}

# Let the user edit a command before it runs, and print the result. bash 4+
# puts the command on the line to edit; the bash 3.2 that macOS ships can't
# (no read -i), so it shows the command and Enter keeps it unchanged.
edit_command() {
    local cmd="$1" edited
    if [ "${BASH_VERSINFO[0]}" -ge 4 ]; then
        read -r -e -i "$cmd" -p "Edit command: " edited
    else
        printf 'Now: %s\n' "$cmd" >&2
        read -r -e -p "Type the new command (Enter keeps it): " edited
        [ -z "$edited" ] && edited="$cmd"
    fi
    printf '%s' "$edited"
}

# replace_all <text> <find> <replacement>: every <find> becomes
# <replacement>, both taken literally. (Not ${text//find/replacement}: bash
# 3.2 keeps quotes in the replacement, and bash 5.2 treats & in it as the
# matched text.) Scans left to right, so a replacement containing <find>
# can't loop.
replace_all() {
    local rest="$1" find="$2" out=""
    while [[ "$rest" == *"$find"* ]]; do
        out+="${rest%%"$find"*}$3"
        rest="${rest#*"$find"}"
    done
    printf '%s' "$out$rest"
}

# Ask for each <placeholder> in a command and substitute the answers.
# Sets FILLED_COMMAND. Returns 1 if the user left a value blank (cancel).
fill_placeholders() {
    local cmd="$1" label value
    local -a labels
    FILLED_COMMAND="$cmd"
    while IFS= read -r label; do
        labels+=("$label")
    done < <(list_placeholders "$cmd")
    [ "${#labels[@]}" -eq 0 ] && return 0

    say "This one needs some details (leave blank to cancel):"
    for label in "${labels[@]}"; do
        read -r -e -p "  $label: " value
        if [ -z "$value" ]; then
            say "Cancelled."
            return 1
        fi
        value="$(quote_value "$value")"
        cmd="$(replace_all "$cmd" "<$label>" "$value")"
    done
    FILLED_COMMAND="$cmd"
    return 0
}

# Succeeds if the word is a program or shell builtin the user could run.
# Clishe's own functions (say, warn, brain, ...) don't count, or "say hi"
# would run Clishe's internals instead of being read as English.
is_runnable() {
    case "$(type -t -- "$1" 2>/dev/null)" in
        file|builtin|keyword) return 0 ;;
    esac
    return 1
}

word_count() {
    local -a w
    read -r -a w <<< "$1"
    echo "${#w[@]}"
}

# Succeeds if any word after the first looks like part of a real command
# line: a flag (-x), a path (/, ., ~), a variable, a quote, or a shell
# operator. Plain English sentences don't contain these.
has_command_markers() {
    local w
    local sq="'"
    local -a words
    read -r -a words <<< "$1"
    for w in "${words[@]:1}"; do
        case "$w" in
            -*|*/*|.*|'~'*|*'$'*|*'"'*|"$sq"*|*"$sq"|*'|'*|*'>'*|*'<'*|*'&'*|*';'*)
                return 0 ;;
        esac
    done
    return 1
}

# Decide whether what the user typed is a real command line (return 0) or
# plain English that should go to the AI (return 1).
looks_like_command() {
    local input="$1"
    local -a words
    read -r -a words <<< "$input"
    local first="${words[0]}"
    local count="${#words[@]}"

    [ -z "$first" ] && return 1

    # "sudo <something>": judge what comes after sudo.
    if [ "$first" = "sudo" ] && [ "$count" -gt 1 ]; then
        case "${words[1]}" in -*) return 0 ;; esac
        looks_like_command "${words[*]:1}"
        return $?
    fi

    # The first word must be something the shell can actually run.
    case "$first" in
        */*|.*) [ -e "$first" ] || return 1 ;;
        *) is_runnable "$first" || return 1 ;;
    esac

    # Flags, paths or operators mean the user is writing a real command.
    has_command_markers "$input" && return 0

    # "git status", "systemctl status nginx", "sudo apt update"
    [[ "$TOOL_COMMANDS" == *" $first "* ]] && return 0

    if [ "$first" = "go" ]; then
        [[ "$GO_SUBCOMMANDS" == *" ${words[1]:-} "* ]] && return 0
        return 1
    fi

    # Ambiguous English verbs: "cat notes.txt" (the file exists) is a
    # command, but "install htop" or "find files bigger than 100MB" is not.
    if [[ "$AMBIGUOUS_WORDS" == *" $first "* ]]; then
        if [ "$count" -eq 2 ] && [ -e "${words[1]}" ]; then
            return 0
        fi
        # touch makes new files, so the file not existing yet is expected.
        if [ "$first" = "touch" ] && [ "$count" -eq 2 ]; then
            return 0
        fi
        return 1
    fi

    # "rm the old files" reads like a sentence, not a file list - unless
    # the words are files that exist ("mv notes.txt drafts").
    if [[ "$CAUTION_WORDS" == *" $first "* ]] && [ "$count" -ge 3 ]; then
        local w
        for w in "${words[@]:1}"; do
            [ -e "$w" ] && return 0
        done
        return 1
    fi

    return 0
}

# Print the command being asked about if the input is an explain-style
# question ("explain tar", "what does chmod do", "what's grep"), or nothing.
# Loose forms ("what is ...") only count when the target starts with a real
# command, so "what is my ip" goes to the AI instead of being "explained".
detect_explain_target() {
    local s="$1"
    local target=""
    local explicit=0

    shopt -s nocasematch
    if [[ "$s" =~ $RE_FILLER ]]; then
        s="${BASH_REMATCH[2]}"
    fi
    if [[ "$s" =~ $RE_EXPLAIN ]]; then
        target="${BASH_REMATCH[1]}"
        explicit=1
    elif [[ "$s" =~ $RE_WHAT_DOES ]]; then
        target="${BASH_REMATCH[1]}"
    elif [[ "$s" =~ $RE_WHAT_IS ]]; then
        target="${BASH_REMATCH[2]}"
    elif [[ "$s" =~ $RE_WHATS ]]; then
        target="${BASH_REMATCH[1]}"
    elif [[ "$s" =~ $RE_TELL_ME ]]; then
        target="${BASH_REMATCH[1]}"
    fi
    shopt -u nocasematch

    # Drop a trailing "?" and surrounding whitespace.
    target="${target%\?}"
    target="${target#"${target%%[![:space:]]*}"}"
    target="${target%"${target##*[![:space:]]}"}"

    if [ -n "$target" ] && [ "$explicit" -eq 0 ]; then
        local first_word="${target%% *}"
        is_runnable "$first_word" || target=""
    fi

    printf '%s' "$target"
}

run_explain() {
    local target="$1"
    local output
    output=$(brain --action explain --command "$target")
    parse_brain_output "$output" EX

    if [ "$EX_STATUS" = "ok" ]; then
        printf '%bClishe (via %s): %b%s\n' "$BLUE" "$EX_PROVIDER" "$NC" "$(decode_lines "$EX_EXPLANATION")"
        return 0
    fi

    warn "I couldn't explain that: it isn't in my offline dictionary and no AI provider is available."
    warn "Try 'man ${target%% *}', or set up a provider in ~/.config/clishe/config.json (see the README)."
    return 1
}

# Print how to install a well-known program the user typed but doesn't
# have. Returns 1 if that's not what happened.
missing_hint() {
    local output
    output=$(brain --action missing --command "$1")
    parse_brain_output "$output" MS
    [ "$MS_STATUS" = "ok" ] || return 1
    printf '%b%s %b%s\n' "$YELLOW" "$ICON_TIP" "$NC" "$MS_HINT"
    return 0
}

# "Is this safe to run?" Says what a command or script would do, without
# running it. Returns 1 if there are warnings (for scripts and CI).
check_session() {
    local target="$1" output key value mode="" lines=0 warned=0 bullet="$ICON_BULLET"
    local -a effects=() report=() safer=()
    if [ -z "$target" ]; then
        read -r -e -p "Paste the command, or a script's file name, to check: " target
        [ -z "$target" ] && return 0
    fi
    output=$(brain --action inspect --command "$target")
    while IFS='=' read -r key value; do
        case "$key" in
            MODE) mode="$value" ;;
            LINES) lines="$value" ;;
            EFFECT) effects+=("$value") ;;
            RLINE) report+=("$(printf '  %b%s%b' "$YELLOW" "$value" "$NC")") ;;
            WARN) warned=1
                  report+=("$(printf '  %b%s It %s.%b' "$RED" "$ICON_WARN" "$value" "$NC")") ;;
            SAFER) safer+=("$value") ;;
        esac
    done <<< "$output"
    if [ -z "$mode" ]; then
        warn "I couldn't check that."
        return 1
    fi

    if [ "$mode" = "script" ]; then
        say "Checked $target ($lines lines). Nothing was run."
    elif get_breakdown "$target"; then
        say "Here's what each part means (nothing was run):"
        printf '\n%s\n' "$BREAKDOWN"
    else
        say_cmd "Checking (nothing was run): " "$target"
    fi
    echo "What it does:"
    for value in "${effects[@]}"; do
        printf '  %s %s\n' "$bullet" "$value"
    done
    if [ "${#report[@]}" -gt 0 ]; then
        [ "$mode" = "script" ] && echo "Lines to look at:"
        printf '%s\n' "${report[@]}"
    fi
    if [ "${#safer[@]}" -gt 0 ]; then
        printf '  %bSafer: download it, read it, then check it:%b\n' "$GREEN" "$NC"
        printf '    %s\n' "${safer[@]}"
    fi
    echo ""
    if [ "$warned" -eq 1 ]; then
        printf "%bRead the warnings above before running it.%b\n" "$RED" "$NC"
        return 1
    fi
    printf "%b%s%b Nothing risky that I know of. That's not a guarantee: only run it if you understand what it does.\n" "$GREEN" "$ICON_OK" "$NC"
    return 0
}

# "How do I install Spotify?": the right way to get an app on this system
# (apps.py). Returns 1 when it isn't an app Clishe knows, so the request
# goes on to the usual steps.
install_app() {
    local output key value status="" app="" how="" command="" answer step
    local -a app_setup=() app_others=()
    output=$(brain --action app --phrase "$1")
    while IFS='=' read -r key value; do
        case "$key" in
            STATUS) status="$value" ;;
            APP) app="$value" ;;
            HOW) how="$value" ;;
            COMMAND) command="$value" ;;
            SETUP) app_setup+=("$value") ;;
            OTHER) app_others+=("$value") ;;
        esac
    done <<< "$output"

    case "$status" in
        installed)
            say "$app is already installed. Type $app to start it."
            return 0 ;;
        ok) ;;
        *) return 1 ;;
    esac
    say "$how"
    [ -n "$command" ] || return 0
    if [ "${#app_setup[@]}" -gt 0 ]; then
        say "First, a one-time setup:"
        for step in "${app_setup[@]}"; do
            printf '  %b%s%b\n' "$YELLOW" "$step" "$NC"
        done
    fi
    say_cmd "To install $app: " "$command"
    for step in "${app_others[@]}"; do
        printf '  %bAnother way: %s%b\n' "$DIM" "$step" "$NC"
    done
    read -r -p "Run it now? [Y/n]: " answer
    [[ "$answer" =~ ^[Nn] ]] && return 0
    TIP_PHRASE=""
    for step in "${app_setup[@]}" "$command"; do
        prepare_and_run "$step"
        [ "$LAST_EXIT" -eq 0 ] || return 0
    done
    return 0
}

# "undo that": reverse the last change, after showing the commands that
# will do it.
undo_last() {
    local output key value status="" original="" explanation="" answer joined
    local -a commands=()
    output=$(brain --action undo-plan)
    while IFS='=' read -r key value; do
        case "$key" in
            STATUS) status="$value" ;;
            ORIGINAL) original="$value" ;;
            EXPLANATION) explanation="$value" ;;
            COMMAND) commands+=("$value") ;;
        esac
    done <<< "$output"

    if [ "$status" = "none" ] || [ -z "$status" ]; then
        say "There's nothing (more) for me to undo. I can undo mv, cp, mkdir, touch, chmod, cd and moving files to the Trash."
        return
    fi
    say_cmd "The last change was: " "$original"
    if [ "$status" = "impossible" ]; then
        say "$explanation"
        brain --action undo-done >/dev/null
        return
    fi
    say "$explanation To undo it:"
    for value in "${commands[@]}"; do
        printf '  %b%s%b\n' "$YELLOW" "$value" "$NC"
    done
    read -r -p "Run it? [Y/n]: " answer
    [[ "$answer" =~ ^[Nn] ]] && return
    joined="${commands[0]}"
    for value in "${commands[@]:1}"; do joined+=" && $value"; done
    CLISHE_UNDOING=1 TIP_PHRASE=""
    prepare_and_run "$joined"
    CLISHE_UNDOING=""
    if [ "$LAST_EXIT" -eq 0 ]; then
        brain --action undo-done >/dev/null
        say "Undone."
    fi
}

# "fix that": explain why the last command failed and offer a fixed one.
fix_last() {
    local output answer fixed
    if [ -z "${LAST_RUN_COMMAND:-}" ]; then
        say "Run a command first. If it fails, ask me to fix it."
        return
    fi
    if [ "$LAST_EXIT" -eq 0 ] || [ "$LAST_EXIT" -eq 130 ]; then
        say_cmd "Your last command didn't fail: " "$LAST_RUN_COMMAND"
        return
    fi
    say "Let me look at what went wrong..."
    output=$(brain --action fix --command "$LAST_RUN_COMMAND" --error "$LAST_STDERR")
    parse_brain_output "$output" FX
    if [ "$FX_STATUS" != "ok" ]; then
        say "I'm not sure what went wrong. Try 'man ${LAST_RUN_COMMAND%% *}', or read the error message above carefully: it usually names the problem."
        return
    fi
    if [ "$FX_PROVIDER" = "offline" ]; then
        say "$(decode_lines "$FX_EXPLANATION")"
    else
        printf '%bClishe (via %s): %b%s\n' "$BLUE" "$FX_PROVIDER" "$NC" "$(decode_lines "$FX_EXPLANATION")"
    fi
    [ -n "$FX_COMMAND" ] || return
    say_cmd "Try: " "$FX_COMMAND"
    if [ -n "$FX_UNVERIFIED" ]; then
        warn "  $ICON_WARN The manual doesn't mention: $FX_UNVERIFIED. The AI may have made it up, so check before running."
    fi
    read -r -p "Run it? [Y/n/e=edit]: " answer
    [[ "$answer" =~ ^[Nn] ]] && return
    fixed="$FX_COMMAND"
    if [[ "$answer" =~ ^[Ee] ]]; then
        fixed=$(edit_command "$fixed")
        [ -z "$fixed" ] && return
    fi
    TIP_PHRASE=""
    prepare_and_run "$fixed"
}

# Explain the output of the last command that ran ("what does this mean?").
explain_last_output() {
    local output
    if [ -z "${LAST_RUN_COMMAND:-}" ]; then
        say "Run a command first, then ask me what its output means."
        return
    fi
    output=$(brain --action output --command "$LAST_RUN_COMMAND")
    parse_brain_output "$output" OG
    if [ "$OG_STATUS" = "ok" ]; then
        say_cmd "About the output of " "$LAST_RUN_COMMAND"
        printf '%s\n' "$(decode_lines "$OG_EXPLANATION")"
    else
        say "I don't have a guide for the output of '$LAST_RUN_COMMAND' yet. Try 'man ${LAST_RUN_COMMAND%% *}' for the full manual."
    fi
}

# Offer the closest known phrase for a near-miss. On yes, sets
# command_to_run / learn_phrase (so the new wording is remembered) and
# returns 0.
offer_close_match() {
    local phrase="$1" output answer
    output=$(brain --action suggest --phrase "$phrase")
    parse_brain_output "$output" SG
    [ "$SG_STATUS" = "ok" ] || return 1

    printf '%bClishe%s: %bDid you mean "%s"? That runs: %b%s%b\n' \
        "$BLUE" "${SG_PROVIDER:+ (via $SG_PROVIDER)}" "$NC" "$SG_PHRASE" "$YELLOW" "$SG_COMMAND" "$NC"
    read -r -p "Use it? [Y/n]: " answer
    if [[ "$answer" =~ ^[Nn] ]]; then
        return 1
    fi
    command_to_run="$SG_COMMAND"
    learn_phrase="$phrase"
    return 0
}

# Ask the user to type a command for a phrase. Sets command_to_run and
# learn_phrase. Returns 1 if they skip.
teach_prompt() {
    local phrase="$1" teach_command
    read -r -e -p "What command should I run? (blank to skip) " teach_command
    if [ -z "$teach_command" ]; then
        warn "No command provided. Skipping."
        return 1
    fi
    command_to_run="$teach_command"
    learn_phrase="$phrase"
    return 0
}

# Draw a command with each part labelled underneath (see breakdown.py)
# into BREAKDOWN. With a phrase, only the first time that phrase is used.
# Returns 1 when there's no breakdown, so the caller shows the command the
# usual way.
get_breakdown() {
    local key value tree label width
    BREAKDOWN=""
    width=$(( $(tput cols 2>/dev/null || echo 80) - 2 ))
    while IFS='=' read -r key value; do
        case "$key" in
            CMD) BREAKDOWN+="$(printf '  %b%s%b' "$YELLOW" "$value" "$NC")"$'\n' ;;
            LINE)
                tree="${value%%$'\t'*}"
                label="${value#*$'\t'}"
                BREAKDOWN+="$(printf '  %b%s%b%s' "$DIM" "$tree" "$NC" "$label")"$'\n' ;;
        esac
    done < <(brain --action breakdown --command "$1" --phrase "${2:-}" --width "$width")
    [ -n "$BREAKDOWN" ]
}

# Ask the AI to turn a phrase into a command. On approval, sets
# command_to_run and learn_phrase and returns 0. Returns 1 if the user
# skipped. If no AI is available (or it declines), falls back to "teach me".
# Nothing is saved here: the caller saves only after the safety check.
resolve_with_ai() {
    local phrase="$1"
    local approve resolve_output err_file provider_errors line
    say "I don't know that. Let me think..."

    err_file=$(mktemp)
    resolve_output=$(python3 "$PYTHON_SCRIPT" --action resolve --phrase "$phrase" 2>"$err_file")
    provider_errors=$(grep '^\[' "$err_file" | head -3)
    rm -f "$err_file"
    parse_brain_output "$resolve_output" RS

    if [ "$RS_STATUS" = "ok" ]; then
        command_to_run="$RS_COMMAND"
        if get_breakdown "$command_to_run"; then
            # The command with each part labelled: the manual's words are
            # already in the labels.
            printf '%bClishe (via %s): %bI think you mean:\n\n%s\n' \
                "$BLUE" "$RS_PROVIDER" "$NC" "$BREAKDOWN"
            if [ -n "$RS_EXPLANATION" ]; then
                printf '  %b%s%b\n' "$DIM" "$(decode_lines "$RS_EXPLANATION")" "$NC"
            fi
            if [ -n "$RS_MANUAL" ] && [ -z "$RS_UNVERIFIED" ]; then
                printf '  %b%s%b %severy option is in the manual%b\n' "$GREEN" "$ICON_OK" "$NC" "$DIM" "$NC"
            fi
        else
            printf '%bClishe (via %s): %bI think you mean: %b%s%b\n' \
                "$BLUE" "$RS_PROVIDER" "$NC" "$YELLOW" "$command_to_run" "$NC"
            if [ -n "$RS_EXPLANATION" ]; then
                printf '  %b%s%b\n' "$DIM" "$(decode_lines "$RS_EXPLANATION")" "$NC"
            fi
        fi
        # What your own manual says about each flag: learn it from the
        # source, and catch a flag the model made up.
        if [ -n "$RS_MANUAL" ] && [ -z "$BREAKDOWN" ]; then
            printf '  %bFrom the manual:%b\n' "$DIM" "$NC"
            while IFS= read -r line; do
                [ -n "$line" ] && printf '    %b%s%b\n' "$DIM" "$line" "$NC"
            done <<< "$(decode_lines "$RS_MANUAL")"
        fi
        if [ -n "$RS_UNVERIFIED" ]; then
            warn "  $ICON_WARN The manual doesn't mention: $RS_UNVERIFIED. The AI may have made it up, so check before running."
        fi
        read -r -p "Run this? [Y/n/e=edit]: " approve
        if [[ "$approve" =~ ^[Nn]$ ]]; then
            say "Okay, skipping. (Not saved - I'll ask again next time.)"
            return 1
        elif [[ "$approve" =~ ^[Ee] ]]; then
            command_to_run=$(edit_command "$command_to_run")
        fi
        if [ -z "$command_to_run" ]; then
            say "Nothing to run. Skipping."
            return 1
        fi
        learn_phrase="$phrase"
        return 0
    fi

    if [ "$RS_STATUS" = "declined" ]; then
        printf '%bClishe (via %s): %bThat looked unclear or risky, so I won'"'"'t guess. Teach me instead:\n' \
            "$YELLOW" "$RS_PROVIDER" "$NC"
    else
        say "I don't know that, and no AI provider is available right now. Teach me!"
        if [ -n "$provider_errors" ]; then
            printf '%b%s%b\n' "$DIM" "$provider_errors" "$NC"
        fi
    fi
    teach_prompt "$phrase"
}

# For a plain "rm", offer to move the files to the Trash instead, so they
# can be restored. May replace FILLED_COMMAND and sets TRASH_RESTORE.
offer_trash() {
    local output answer
    TRASH_RESTORE=""
    output=$(brain --action trash --command "$FILLED_COMMAND")
    parse_brain_output "$output" TR
    [ "$TR_STATUS" = "ok" ] || return 0
    if [ "$TR_MODE" != "always" ]; then
        say_cmd "Move it to the Trash instead, so you can get it back? That runs: " "$TR_COMMAND"
        read -r -p "Use the Trash? [Y/n]: " answer
        [[ "$answer" =~ ^[Nn] ]] && return 0
    fi
    FILLED_COMMAND="$TR_COMMAND"
    TRASH_RESTORE="$TR_RESTORE"
}

# Fill placeholders, safety-check, optionally remember, then run.
#   prepare_and_run "<command or template>" ["<phrase to remember it as>"]
# The template (with its <placeholders>) is what gets remembered, so the
# phrase keeps asking for fresh values next time.
prepare_and_run() {
    local template="$1" phrase="${2:-}"
    LAST_EXIT=0
    LAST_STDERR=""

    fill_placeholders "$template" || { echo ""; return 1; }
    TRASH_RESTORE=""
    [ -z "${CLISHE_UNDOING:-}" ] && offer_trash
    # Show the final command whenever it differs from what was shown first
    # (placeholders filled in, or switched to the Trash).
    if [ "$FILLED_COMMAND" != "$template" ]; then
        say_cmd "Running: " "$FILLED_COMMAND"
    fi

    # Safety check before executing anything, whether it came from the KB,
    # an AI provider, or manual teaching.
    if ! confirm_dangerous "$FILLED_COMMAND"; then
        echo ""
        return 1
    fi

    # Note what's there now, so "undo that" can put it back (only for
    # commands undo knows; see undo.py).
    local undo_note=""
    if [ -z "${CLISHE_UNDOING:-}" ]; then
        case "${FILLED_COMMAND%% *}" in
            mv|cp|mkdir|touch|chmod|cd|rm|trash|trash-put|gio|sudo|brew|flatpak)
                undo_note=$(brain --action undo-before --command "$FILLED_COMMAND" --cwd "$PWD") ;;
        esac
    fi

    run_command "$FILLED_COMMAND"
    if [ -n "$undo_note" ] && [ "$LAST_EXIT" -eq 0 ]; then
        brain --action undo-record --state "$undo_note" --cwd "$PWD" >/dev/null
    fi
    if [ -n "$TRASH_RESTORE" ] && [ "$LAST_EXIT" -eq 0 ]; then
        say "Moved to the Trash. Changed your mind? $TRASH_RESTORE."
        echo ""
    fi

    # Remember the phrase only once its command has worked (Ctrl-C counts:
    # that's how you stop ping or tail -f). Saving first meant a wrong
    # command came back every time. Only what was approved, including
    # edits, is saved, never a raw unreviewed suggestion.
    if [ -n "$phrase" ]; then
        if [ "$LAST_EXIT" -eq 0 ] || [ "$LAST_EXIT" -eq 130 ]; then
            if [ "$(brain --action learn --phrase "$phrase" --command "$template")" = "learned" ]; then
                say "Saved for next time - I won't need to ask again."
                echo ""
            fi
        else
            say "That didn't work, so I won't remember it for \"$phrase\". (If it was right after all, type 'teach' to save it.)"
            echo ""
        fi
    fi
}

# Run, show hints, log, suggest the next command.
# Sets LAST_EXIT and LAST_STDERR for the caller.
run_command() {
    local cmd="$1"
    local stderr_file diagnose_output
    LAST_EXIT=0
    LAST_STDERR=""
    LAST_RUN_COMMAND="$cmd"

    echo ""
    stderr_file=$(mktemp)
    # Redirect stderr straight to a temp file (synchronous - avoids the race
    # condition of process substitution) then replay it. This runs in this
    # shell (no pipeline), so "cd" and "export" keep working.
    eval "$cmd" 2>"$stderr_file"
    LAST_EXIT=$?
    cat "$stderr_file" >&2
    LAST_STDERR=$(cat "$stderr_file")
    rm -f "$stderr_file"
    echo ""

    if [ "$LAST_EXIT" -ne 0 ]; then
        if [ "$LAST_EXIT" -eq 130 ]; then
            say "Stopped (Ctrl-C)."
        else
            printf '%bCommand exited with code: %s%b\n' "$RED" "$LAST_EXIT" "$NC"
        fi
        if [ -n "$LAST_STDERR" ]; then
            diagnose_output=$(brain --action diagnose --error "$LAST_STDERR")
            parse_brain_output "$diagnose_output" DX
            if [ "$DX_STATUS" = "ok" ]; then
                printf '%b%s %b%s\n' "$YELLOW" "$ICON_TIP" "$NC" "$DX_HINT"
            fi
        fi
        [ "$LAST_EXIT" -ne 130 ] && \
            printf "%b(Type 'fix that' and I'll suggest a fix.)%b\n" "$DIM" "$NC"
    else
        # Only successful commands are logged, so failed guesses don't
        # pollute the next-command suggestions.
        # Logging also returns tips: "you can type this yourself now",
        # or a cheer when you just did.
        # (One call: the next-command suggestion comes back here too.)
        local log_output line
        log_output=$(brain --action log --command "$cmd" --phrase "${TIP_PHRASE:-}")
        while IFS= read -r line; do
            case "$line" in
                TIP=*) printf '%b%s %b%s\n' "$YELLOW" "$ICON_TIP" "$NC" "${line#TIP=}" ;;
                GUIDE=1) printf '%b(Not sure what that output means? Ask me: what does this mean)%b\n' "$DIM" "$NC" ;;
                PREDICT=*) say_cmd "$ICON_TIP You might want to run: " "${line#PREDICT=}" ;;
            esac
        done <<< "$log_output"
    fi
    echo ""
}

list_learned() {
    local output phrase cmd
    output=$(brain --action list)
    if [ -z "$output" ]; then
        say "You haven't taught me anything yet. Type 'teach' to start."
        return
    fi
    say "Here's what you've taught me:"
    while IFS=$'\t' read -r phrase cmd; do
        printf '  %s %b→%b %b%s%b\n' "$phrase" "$DIM" "$NC" "$YELLOW" "$cmd" "$NC"
    done <<< "$output"
}

forget_phrase() {
    local phrase="$1"
    if [ -z "$phrase" ]; then
        read -r -e -p "Which phrase should I forget? " phrase
        [ -z "$phrase" ] && return
    fi
    if [ "$(brain --action forget --phrase "$phrase")" = "forgotten" ]; then
        say "Forgotten: \"$phrase\"."
    else
        say "I don't have \"$phrase\" in the phrases you taught me. (Type 'learned' to see them.)"
    fi
}

teach_session() {
    local phrase teach_command
    read -r -e -p "Phrase (what you'd type): " phrase
    [ -z "$phrase" ] && return
    read -r -e -p "Command to run for it: " teach_command
    [ -z "$teach_command" ] && return
    # Same check as before running, so a risky command is never saved
    # without a typed YES.
    confirm_dangerous "$teach_command" save || return
    if [ "$(brain --action learn --phrase "$phrase" --command "$teach_command")" = "learned" ]; then
        say "Got it. \"$phrase\" now runs: $teach_command"
    else
        warn "Couldn't save that."
    fi
}

# ---------- Learning by doing ----------

# "Your turn": after you've asked for a phrase a few times, type its command
# yourself. Returns 0 if it ran what you typed, 1 to carry on as usual (the
# command is then run for you). Sets YT_SHOWN=1 if it already showed it.
your_turn() {
    local phrase="$1" output typed
    YT_SHOWN=0
    output=$(brain --action turn --phrase "$phrase")
    parse_brain_output "$output" YT
    [ "$YT_STATUS" = "ask" ] || return 1

    printf '%b%s Your turn!%b You know this one. Type the command for "%s" (or press Enter to see it):\n' \
        "$YELLOW" "$ICON_TIP" "$NC" "$phrase"
    read -r -e -p "  \$ " typed
    [ -z "$typed" ] && return 1

    output=$(brain --action attempt --phrase "$phrase" --command "$typed")
    parse_brain_output "$output" AT
    if [ "$AT_STATUS" = "right" ]; then
        say "$ICON_OK That's it!"
        TIP_PHRASE=""
        prepare_and_run "$typed"
        return 0
    fi
    if [ "$AT_STATUS" = "close" ]; then
        say_cmd "Close! Right command, different options. It's: " "$AT_COMMAND"
    else
        say_cmd "Not quite. It's: " "$AT_COMMAND"
    fi
    YT_SHOWN=1
    return 1
}

show_progress() {
    local output key value learned="" total=0 others="" to_try="" next=""
    local -a words
    output=$(brain --action progress)
    while IFS='=' read -r key value; do
        case "$key" in
            LEARNED) learned="$value" ;;
            TOTAL) total="$value" ;;
            OTHERS) others="$value" ;;
            TO_TRY) to_try="$value" ;;
            NEXT) next="$value" ;;
        esac
    done <<< "$output"
    read -r -a words <<< "$learned"

    say "You've typed ${#words[@]} of $total everyday commands yourself."
    [ -n "$learned" ] && printf '  %b%s%b\n' "$GREEN" "$learned" "$NC"
    [ -n "$others" ] && printf '  Also: %s\n' "$others"
    if [ -n "$to_try" ]; then
        printf "You've asked me for these, but haven't typed them yourself yet: %b%s%b\n" "$YELLOW" "$to_try" "$NC"
    fi
    if [ -n "$next" ]; then
        printf 'Good ones to learn next: %s. Try: explain %s\n' "$next" "${next%% *}"
    fi
    echo "Type 'practice' for hands-on exercises in a safe, throwaway folder."
}

# The throwaway folder practice works in, and how to tidy it away.
PRACTICE_PREFIX="clishe-practice."

# Remove this session's practice folder and go back to where the learner
# started. Safe to call more than once.
practice_cleanup() {
    cd "${PRACTICE_HOME_DIR:-$HOME}" 2>/dev/null || true
    if [[ -n "${SANDBOX:-}" && "$(basename "$SANDBOX")" == "$PRACTICE_PREFIX"* ]]; then
        rm -rf -- "$SANDBOX"
    fi
    SANDBOX=""
}

# Folders left by a practice that couldn't clean up (kill -9, a crash):
# only ours (our name, our user, straight in the temp folder), and only
# when untouched for a day, so a practice open in another terminal is safe.
sweep_practice_folders() {
    find "${TMPDIR:-/tmp}" -maxdepth 1 -type d -name "${PRACTICE_PREFIX}??????" \
        -user "$(id -un)" -mmin +1440 -exec rm -rf -- {} + 2>/dev/null
    return 0
}

# Hands-on exercises from a lesson pack (lessons/*.json, see lessons.py),
# run in a throwaway folder. With no pack named and more than one around,
# asks which one.
practice_session() {
    local pack="${1:-}" start=0 i cmd status answer key value title="" finished="" count
    local orig_dir="$PWD" choice n
    local -a names=() tasks=() hints=() answers=() needs=()
    mkdir -p "$DATA_DIR" 2>/dev/null

    if [ -z "$pack" ]; then
        while IFS= read -r value; do
            names+=("${value%%$'\t'*}")
        done < <(brain --action lessons | sed -n 's/^PACK=//p')
        if [ "${#names[@]}" -gt 1 ]; then
            say "Which lesson? (each runs in a throwaway folder)"
            n=0
            while IFS=$'\t' read -r key count title value; do
                n=$((n + 1))
                printf '  %s. %s (%s exercises): %s\n' "$n" "$title" "$count" "$value"
            done < <(brain --action lessons | sed -n 's/^PACK=//p')
            read -r -p "Pick a number or a name [1]: " choice
            pack=""
            for value in "${names[@]}"; do
                [ "$value" = "$choice" ] && pack="$value"
            done
            if [ -z "$pack" ]; then
                [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#names[@]}" ] || choice=1
                pack="${names[$((choice - 1))]}"
            fi
        else
            pack="${names[0]:-basics}"
        fi
    fi

    while IFS='=' read -r key value; do
        case "$key" in
            STATUS) status="$value" ;;
            TITLE) title="$value" ;;
            DONE) finished="$value" ;;
            TASK) tasks+=("$value") ;;
            HINT) hints+=("$value") ;;
            ANSWER) answers+=("$value") ;;
            MISSING) needs+=("$value") ;;
        esac
    done < <(brain --action lesson --phrase "$pack")
    if [ "$status" = "missing" ]; then
        warn "This lesson needs a program that isn't installed yet:"
        for value in "${needs[@]}"; do
            printf '  %s\n' "$value"
        done
        return 1
    fi
    if [ "$status" != "ok" ]; then
        warn "There's no lesson called '$pack'. See the ones you have with: clishe practice --list"
        return 1
    fi
    count="${#tasks[@]}"

    local done_file="$DATA_DIR/practice_done_$pack"
    # Progress from before lessons had names belongs to the basics.
    if [ "$pack" = "basics" ] && [ -f "$DATA_DIR/practice_done" ] && [ ! -f "$done_file" ]; then
        mv "$DATA_DIR/practice_done" "$done_file" 2>/dev/null
    fi
    [ -f "$done_file" ] && start=$(cat "$done_file" 2>/dev/null)
    [[ "$start" =~ ^[0-9]+$ ]] || start=0
    if [ "$start" -ge "$count" ]; then
        start=0
    elif [ "$start" -gt 0 ]; then
        read -r -p "Pick up where you left off, at exercise $((start + 1)) of $count? [Y/n]: " answer
        [[ "$answer" =~ ^[Nn] ]] && start=0
    fi

    sweep_practice_folders
    # However practice ends - quit, Ctrl-C, the terminal closing, being
    # told to stop - the folder goes. The session's own traps come back
    # afterwards. Set before the folder is made, so there's no moment when
    # the folder exists and nothing would remove it.
    local saved_traps
    saved_traps="$(trap -p INT EXIT HUP TERM)"
    SANDBOX="" PRACTICE_HOME_DIR="$orig_dir"
    trap 'printf "\n"' INT          # Ctrl-C stops a running command, not practice
    trap 'practice_cleanup' EXIT
    trap 'practice_cleanup; exit 129' HUP
    trap 'practice_cleanup; exit 143' TERM
    if ! SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/${PRACTICE_PREFIX}XXXXXX")" || ! cd "$SANDBOX"; then
        practice_cleanup
        trap - INT EXIT HUP TERM
        eval "$saved_traps"
        return 1
    fi
    SANDBOX="$PWD"  # the same spelling cd will use (no "//" from TMPDIR)
    # Picking up later: quietly redo the earlier steps, so the folder looks
    # the way the next exercise expects.
    for ((i = 0; i < start; i++)); do
        eval "${answers[$i]}" >/dev/null 2>&1
    done

    say "Practice time: $title. You're in a throwaway folder, so nothing here can hurt your files."
    echo "Type real commands. Also: 'hint', 'answer', 'skip', 'quit'."
    for ((i = start; i < count; i++)); do
        echo ""
        printf '%b%s/%s%b %s\n' "$BLUE" "$((i + 1))" "$count" "$NC" "${tasks[$i]}"
        local tries=0
        while true; do
            # Read in a subshell with the normal Ctrl-C, like the main
            # prompt: Ctrl-C (or the end of input) here means "quit".
            if ! cmd=$(trap - INT; IFS= read -r -e -p "practice\$ " l; s=$?; printf '%s' "$l"; exit $s); then
                echo ""
                cmd="quit"
            fi
            case "$cmd" in
                "") continue ;;
                hint) printf '  %b%s%b\n' "$DIM" "${hints[$i]}" "$NC"; continue ;;
                answer|show) say_cmd "One way: " "${answers[$i]}"; continue ;;
                skip) say_cmd "Skipped. One way: " "${answers[$i]}"
                      eval "${answers[$i]}" >/dev/null 2>&1; break ;;
                quit|exit) printf '%s' "$i" > "$done_file"
                      say "See you next time - I'll remember where you got to."
                      practice_cleanup
                      trap - INT EXIT HUP TERM
                      eval "$saved_traps"
                      return 0 ;;
            esac
            history -s "$cmd"
            confirm_dangerous "$cmd" || continue
            eval "$cmd"
            status=$?
            [ "$status" -eq 0 ] && brain --action log --command "$cmd" >/dev/null
            if [ "$(brain --action lesson-check --phrase "$pack" --step "$i" \
                    --command "$cmd" --cwd "$PWD" --state "$SANDBOX")" = "yes" ]; then
                printf '%b%s Nice!%b\n' "$GREEN" "$ICON_OK" "$NC"
                break
            fi
            tries=$((tries + 1))
            if [ "$tries" -ge 2 ]; then
                printf '  %bHint: %s%b\n' "$DIM" "${hints[$i]}" "$NC"
            else
                echo "  Not yet - try again, or type 'hint'."
            fi
        done
        printf '%s' "$((i + 1))" > "$done_file"
    done
    echo ""
    say "${ICON_CHEER}All $count done!${finished:+ $finished}"
    practice_cleanup
    trap - INT EXIT HUP TERM
    eval "$saved_traps"
    : > "$done_file"
}

# The lesson packs you have, for: clishe practice --list
list_lessons() {
    local name count title description
    say "Lessons (start one with: clishe practice <name>)"
    while IFS=$'\t' read -r name count title description; do
        printf '  %b%-12s%b %s (%s exercises): %s\n' "$YELLOW" "$name" "$NC" "$title" "$count" "$description"
    done < <(brain --action lessons | sed -n 's/^PACK=//p')
    echo "Add your own: put a lesson file in ${XDG_DATA_HOME:-$HOME/.local/share}/clishe/lessons/ (see CONTRIBUTING.md)."
}

# "clishe sheet": your own cheat sheet, plain text so it can be saved
# (clishe sheet > cheatsheet.txt) and printed.
cheat_sheet() {
    local key value command width=0
    local -a learned=() asked=()
    while IFS='=' read -r key value; do
        case "$key" in
            LEARNED) learned+=("$value") ;;
            ASKED) asked+=("$value") ;;
        esac
    done < <(brain --action sheet)
    if [ "${#learned[@]}" -eq 0 ] && [ "${#asked[@]}" -eq 0 ]; then
        say "Your cheat sheet is empty so far. Run a few commands (or try 'practice'), then ask again."
        return 0
    fi
    for value in "${learned[@]}" "${asked[@]}"; do
        command="${value%%$'\t'*}"
        [ "${#command}" -gt "$width" ] && width="${#command}"
    done
    [ "$width" -gt 34 ] && width=34
    if [ "${#learned[@]}" -gt 0 ]; then
        printf 'MY LINUX CHEAT SHEET: %s commands I type myself\n\n' "${#learned[@]}"
        for value in "${learned[@]}"; do
            printf '  %-*s  %s\n' "$width" "${value%%$'\t'*}" "${value#*$'\t'}"
        done
    fi
    if [ "${#asked[@]}" -gt 0 ]; then
        printf '\nSTILL LEARNING: what I ask for, and the command to type instead\n\n'
        for value in "${asked[@]}"; do
            printf '  %-*s  %s\n' "$width" "${value#*$'\t'}" "${value%%$'\t'*}"
        done
    fi
    [ -t 1 ] && printf '\n%bSave it with: clishe sheet > cheatsheet.txt%b\n' "$DIM" "$NC"
    return 0
}

# "clishe doctor": check what commonly goes wrong and say how to fix it.
# Returns 1 if there's a real problem.
doctor_session() {
    local status title detail fix problems=0 notes=0 mark
    say "Checking your setup..."
    echo ""
    while IFS=$'\t' read -r status title detail fix; do
        case "$status" in
            ok)   mark="$(printf '%b%s%b' "$GREEN" "$ICON_OK" "$NC")" ;;
            note) mark="$(printf '%b%s%b' "$YELLOW" "$ICON_NOTE" "$NC")"; notes=$((notes + 1)) ;;
            *)    mark="$(printf '%b%s%b' "$RED" "$ICON_FAIL" "$NC")"; problems=$((problems + 1)) ;;
        esac
        printf '%s %s\n' "$mark" "$title"
        [ -n "$detail" ] && printf '    %b%s%b\n' "$DIM" "$detail" "$NC"
        [ -n "$fix" ] && printf '    Fix: %s\n' "$fix"
    done < <(CLISHE_BASH="$BASH_VERSION" CLISHE_ON_PATH="$(command -v clishe 2>/dev/null)" \
             brain --action doctor | sed -n 's/^CHECK=//p')
    echo ""
    if [ "$problems" -gt 0 ]; then
        say "$problems problem(s) to fix, and $notes thing(s) worth knowing. The Fix lines above say how."
        return 1
    fi
    if [ "$notes" -gt 0 ]; then
        say "Everything works. $notes thing(s) above are worth knowing."
    else
        say "Everything looks good."
    fi
    return 0
}

# A walk through this computer in plain English, one stop at a time.
tour_session() {
    local key value label answer stops=0
    local -a lines=()
    while IFS= read -r value; do lines+=("$value"); done \
        < <(brain --action tour --width "$(( $(tput cols 2>/dev/null || echo 80) - 2 ))")
    if [ "${#lines[@]}" -eq 0 ]; then
        warn "I couldn't look around this computer, sorry."
        return 1
    fi
    say "Here's a quick tour of your computer. Each stop has a command you can try later."
    for value in "${lines[@]}" "STOP="; do
        key="${value%%=*}"
        value="${value#*=}"
        case "$key" in
            STOP)
                if [ "$stops" -gt 0 ]; then
                    [ -z "$value" ] && break
                    echo ""
                    read -r -p "Enter for the next stop, q to finish: " answer || break
                    [[ "$answer" =~ ^[Qq] ]] && break
                fi
                stops=$((stops + 1))
                printf '\n%b%s%b\n' "$BLUE" "$value" "$NC" ;;
            FACT)
                label="${value%%$'\t'*}"
                printf '  %-20s %s\n' "$label" "${value#*$'\t'}" ;;
            NOTE) printf '  %b%s%b\n' "$DIM" "$value" "$NC" ;;
            TRY) printf '  Try: %b%s%b\n' "$YELLOW" "$value" "$NC" ;;
        esac
    done
    echo ""
    say "That's the tour. Ask me 'explain <command>' about any command you saw."
}

# Check this computer for a local AI model and help get one running.
setup_session() {
    local output key value model="" running=0 ready=0 configured="" answer
    say "Checking this computer for a local AI model..."
    echo ""
    output=$(brain --action setup)
    while IFS='=' read -r key value; do
        case "$key" in
            LINE) printf '  %s\n' "$value" ;;
            MODEL) model="$value" ;;
            RUNNING) running="$value" ;;
            READY) ready="$value" ;;
            CONFIGURED) configured="$value" ;;
        esac
    done <<< "$output"
    echo ""
    [ -n "$model" ] || return 0

    if [ "$running" = 1 ] && [ "$ready" != 1 ]; then
        read -r -p "Download $model now? This runs: ollama pull $model [y/N]: " answer
        if [[ "$answer" =~ ^[Yy] ]]; then
            ollama pull "$model" && ready=1
        fi
    fi
    if [ "$ready" = 1 ] && [ "$configured" != "$model" ]; then
        read -r -p "Use $model for Clishe? [Y/n]: " answer
        if [[ ! "$answer" =~ ^[Nn] ]] \
            && [ "$(brain --action set-model --command "$model")" = "saved" ]; then
            say "Done. Ask me something I don't know, and $model will answer, right here on your computer."
        fi
    elif [ "$ready" = 1 ]; then
        say "All set: Clishe uses $model, on your computer."
    fi
}

# Everything above is a function library. When this file is sourced (by
# the tests), stop here instead of starting a session.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

# Git Bash, MSYS and Cygwin on Windows: the Python backend can't run there,
# so Clishe would start and quietly do nothing. Point to WSL instead.
case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*)
        echo "Clishe runs on Linux and macOS, not directly on Windows." >&2
        echo "To use it on Windows, install WSL: open PowerShell and type: wsl --install" >&2
        echo "More about WSL: https://learn.microsoft.com/windows/wsl/install" >&2
        exit 1
        ;;
esac

# "plain": true in the config turns plain mode on too.
if [ -z "$PLAIN" ] && [ "$(brain --action setting --phrase plain)" = "true" ]; then
    PLAIN=1
    set_symbols
fi

# ---------- One-shot (non-interactive) mode ----------
# clishe explain "<command>"  or  clishe "<phrase>"  runs once and exits,
# so Clishe works from scripts and aliases.
if [ $# -gt 0 ]; then
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -V|--version)
            echo "clishe $CLISHE_VERSION"
            exit 0
            ;;
        --list)
            brain --action list
            exit 0
            ;;
        --init)
            # Default to the shell the user runs, so a plain --init works too.
            init_shell="${2:-$(basename "${SHELL:-bash}")}"
            case "$init_shell" in
                bash|zsh)
                    printf '__CLISHE_BRAIN=%q\nsource %q\n' \
                        "$PYTHON_SCRIPT" "$SCRIPT_DIR/clishe-bind.$init_shell"
                    exit 0 ;;
                *)
                    echo "The Ctrl+G shortcut works in bash and zsh: eval \"\$(clishe --init bash)\" or --init zsh" >&2
                    exit 1 ;;
            esac
            ;;
        practice)
            case "${2:-}" in
                --list|-l|list) list_lessons; exit 0 ;;
                *) practice_session "${2:-}"; exit $? ;;
            esac ;;
        progress)
            [ $# -eq 1 ] && { show_progress; exit 0; } ;;
        setup)
            [ $# -eq 1 ] && { setup_session; exit 0; } ;;
        tour)
            [ $# -eq 1 ] && { tour_session; exit $?; } ;;
        doctor)
            [ $# -eq 1 ] && { doctor_session; exit $?; } ;;
        sheet|cheatsheet)
            [ $# -eq 1 ] && { cheat_sheet; exit 0; } ;;
        check)
            shift
            check_session "$*"
            exit $? ;;
        explain)
            if [ $# -gt 1 ]; then
                shift
                run_explain "$*"
                exit $?
            fi
            ;;
    esac

    # Plain output (no colors) so it's safe to use inside $( ... ).
    kb_result=$(brain --action query --phrase "$*")
    if [ -n "$kb_result" ]; then
        printf '%s\n' "$kb_result"
        exit 0
    fi
    echo "Not in the knowledge base yet. Run clishe with no arguments to ask the AI or teach it." >&2
    exit 1
fi

# ---------- Interactive session ----------

# Arrow keys recall what you typed before, across sessions.
mkdir -p "$DATA_DIR" 2>/dev/null
HISTFILE="$INPUT_HISTORY_FILE"
HISTSIZE=500
HISTFILESIZE=500
history -r "$HISTFILE" 2>/dev/null

# Ctrl-C stops the running command (or clears the prompt), not Clishe.
trap 'printf "\n"' INT
PROMPT="$(printf '%bYou: %b' "$GREEN" "$NC")"

# Read one line at the prompt. It runs in a subshell with the default
# Ctrl-C behaviour, so Ctrl-C abandons the line and the loop shows a clean
# new prompt (readline doesn't redraw properly after a trapped ^C).
read_input() {
    local line status
    line=$(trap - INT; IFS= read -r -e -p "$PROMPT" l; s=$?; printf '%s' "$l"; exit $s)
    status=$?
    user_input="$line"
    return $status
}

if [ -n "$PLAIN" ]; then
    printf '%bWelcome to Clishe v%s.%b\n' "$BLUE" "$CLISHE_VERSION" "$NC"
else
    printf '%b╔═══════════════════════════════════════╗%b\n' "$BLUE" "$NC"
    printf '%b║         Welcome to Clishe %-12s║%b\n' "$BLUE" "v$CLISHE_VERSION" "$NC"
    printf '%b║  Natural Language Command Interface   ║%b\n' "$BLUE" "$NC"
    printf '%b╚═══════════════════════════════════════╝%b\n' "$BLUE" "$NC"
fi
printf "%bSay what you want in plain English. Type 'help' for tips, 'exit' to quit.%b\n\n" "$BLUE" "$NC"

# First time ever: show a few things to try instead of a blank prompt.
WELCOMED_FILE="$DATA_DIR/.welcomed"
if [ ! -e "$WELCOMED_FILE" ]; then
    cat <<'WELCOME'
First time here? Try typing one of these:

  show me disk usage        how full your disk is
  list files                what's in this folder
  how much memory is free   how much RAM you have left
  explain tar -xzvf         what each part of a command means
  delete a file             (I always ask before anything risky)
  tour                      a quick tour of your own computer

After any command, ask "what does this mean" to understand its output.
You can also use me in your normal terminal with Ctrl+G. Type 'help' to see how.

WELCOME
    : > "$WELCOMED_FILE" 2>/dev/null
fi

while true; do
    read_input
    read_status=$?
    if [ "$read_status" -ne 0 ]; then
        if [ "$read_status" -gt 128 ]; then
            continue  # Ctrl-C at the prompt: just show a fresh prompt
        fi
        echo ""       # Ctrl-D or end of piped input
        say "Goodbye!"
        break
    fi

    # Trim surrounding whitespace.
    user_input="${user_input#"${user_input%%[![:space:]]*}"}"
    user_input="${user_input%"${user_input##*[![:space:]]}"}"
    [ -z "$user_input" ] && continue

    history -s "$user_input"
    history -w "$HISTFILE" 2>/dev/null
    chmod 600 "$HISTFILE" 2>/dev/null

    command_to_run=""
    learn_phrase=""
    input_kind=""

    # "is this safe?" / "check <command or script>": look, don't run.
    shopt -s nocasematch
    if [[ "$user_input" =~ $RE_SAFE_QUESTION ]]; then
        shopt -u nocasematch
        check_session "${BASH_REMATCH[3]}"
        echo ""
        continue
    fi
    shopt -u nocasematch
    case "$user_input" in
        "check "*)
            # Only for a real command or a file, so phrases like
            # "check my ip address" keep working.
            check_target="${user_input#check }"
            if [ -f "$check_target" ] || looks_like_command "$check_target"; then
                check_session "$check_target"
                echo ""
                continue
            fi ;;
    esac

    # "fix that" after a command fails.
    shopt -s nocasematch
    if [[ "$user_input" =~ $RE_FIX ]]; then
        shopt -u nocasematch
        fix_last
        echo ""
        continue
    fi
    shopt -u nocasematch

    # "what does this mean?" right after a command.
    shopt -s nocasematch
    if [[ "$user_input" =~ $RE_OUTPUT_QUESTION ]]; then
        shopt -u nocasematch
        explain_last_output
        echo ""
        continue
    fi
    shopt -u nocasematch

    # Clishe's own commands.
    case "$user_input" in
        exit|quit)
            say "Goodbye!"
            break ;;
        help|\?)
            session_help; echo ""; continue ;;
        learned|"what have you learned"|"list learned")
            list_learned; echo ""; continue ;;
        teach)
            teach_session; echo ""; continue ;;
        setup)
            setup_session; echo ""; continue ;;
        sheet|"cheat sheet"|"my cheat sheet"|"show my cheat sheet")
            cheat_sheet; echo ""; continue ;;
        doctor|"check my setup"|"is clishe working")
            doctor_session; echo ""; continue ;;
        tour|"show me around"|"tour my computer")
            tour_session; echo ""; continue ;;
        forget|"forget "*)
            forget_target="${user_input#forget}"
            forget_phrase "${forget_target# }"; echo ""; continue ;;
        practice|"practice "*)
            practice_target="${user_input#practice}"
            practice_target="${practice_target# }"
            case "$practice_target" in
                list|--list) list_lessons ;;
                *) practice_session "$practice_target" ;;
            esac
            echo ""; continue ;;
        undo|"undo that"|"undo it"|"undo last"|"undo the last command"|"take that back")
            undo_last; echo ""; continue ;;
        progress|"my progress"|"what have i learned")
            show_progress; echo ""; continue ;;
    esac

    # 1. Exact match in your knowledge base (or the bundled seed KB).
    #    This runs first so a phrase you taught, like "what's my ip", can't
    #    be mistaken for an explain-style question.
    kb_result=$(brain --action query --phrase "$user_input")

    if [ -n "$kb_result" ]; then
        command_to_run="$kb_result"
        input_kind="kb"
        if your_turn "$user_input"; then
            continue
        fi
        if [ "$YT_SHOWN" != 1 ]; then
            # The first time a phrase is used, show what each part means.
            if get_breakdown "$command_to_run" "$user_input"; then
                say "I know this!"
                printf '\n%s\n' "$BREAKDOWN"
            else
                say_cmd "I know this! " "$command_to_run"
            fi
        fi
    else
        # "how do I install spotify?": apps and well-known tools.
        shopt -s nocasematch
        if [[ "$user_input" =~ $RE_INSTALL_APP ]]; then
            shopt -u nocasematch
            if install_app "$user_input"; then
                echo ""
                continue
            fi
        fi
        shopt -u nocasematch

        # 2. "explain tar", "what does chmod do", "what's grep"
        explain_target=$(detect_explain_target "$user_input")
        if [ -n "$explain_target" ]; then
            say "Let me look that up..."
            run_explain "$explain_target"
            echo ""
            continue
        fi

        # 3. A real command line, or plain English?
        if looks_like_command "$user_input"; then
            command_to_run="$user_input"
            input_kind="native"
            say_cmd "Executing: " "$command_to_run"
        # A well-known program that isn't installed ("htop"): say how to
        # get it, rather than treating it as English.
        elif missing_hint "$user_input"; then
            echo ""
            continue
        # 4. Close to a phrase I know? (offline, asks first)
        elif offer_close_match "$user_input"; then
            input_kind="kb"
        # 5. Ask the AI, or be taught.
        elif resolve_with_ai "$user_input"; then
            input_kind="ai"
        else
            echo ""
            continue
        fi
    fi

    # Count phrase uses (for "you can type this yourself" tips). Commands
    # typed directly count as "you did it yourself".
    TIP_PHRASE=""
    [ "$input_kind" != "native" ] && TIP_PHRASE="$user_input"

    prepare_and_run "$command_to_run" "$learn_phrase"

    # A "command" that failed with an error message, when the input reads
    # like a sentence, was probably plain English - offer to ask the AI.
    if [ "$input_kind" = "native" ] && [ "$LAST_EXIT" -ne 0 ] && [ "$LAST_EXIT" -ne 130 ] \
        && [ -n "$LAST_STDERR" ] \
        && ! has_command_markers "$user_input" && [ "$(word_count "$user_input")" -ge 3 ]; then
        read -r -p "That didn't work. Did you mean it as plain English? Ask the AI? [y/N]: " retry
        if [[ "$retry" =~ ^[Yy]$ ]]; then
            learn_phrase=""
            TIP_PHRASE="$user_input"
            if resolve_with_ai "$user_input"; then
                prepare_and_run "$command_to_run" "$learn_phrase"
            fi
        fi
        echo ""
    fi
done
