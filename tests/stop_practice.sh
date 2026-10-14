#!/bin/bash
# Helper for tests/test_shell_functions.sh: start `clishe practice`, stop it
# the way a terminal would (a signal to the whole process group), and print
# "<folders left> <progress saved>".
#   bash tests/stop_practice.sh <path to clishe.sh> <INT|TERM|HUP>
set -m  # the practice gets its own process group, like a job in a terminal
clishe="$1" sig="$2"
started=$(date +%s)
work="$(mktemp -d)" home="$(mktemp -d)"
mkfifo "$work/in"
HOME="$home" TMPDIR="$work/" NO_COLOR=1 "$clishe" practice basics < "$work/in" > /dev/null 2>&1 &
pid=$!
exec 7>"$work/in"
for _ in $(seq 1 100); do
    compgen -G "$work/clishe-practice.*" > /dev/null && break
    sleep 0.1
done
kill -"$sig" -- "-$pid" 2>/dev/null
signalled=$(date +%s)
# Wait for the practice to actually tidy up, instead of guessing how long
# that takes. What this checks is that the folder goes away, so wait for
# that - or for the process to exit - up to 20s. The old fixed 5s budget
# was a wall-clock assumption rather than the behaviour under test, and on
# a loaded CI machine it wasn't always enough: that test failed on the
# Python 3.9 job while passing on 3.11, 3.12 and macOS, and the same
# failure had already happened before these changes (#60).
# SIGKILL stays the last resort, so a genuinely stuck run can't hang.
for _ in $(seq 1 200); do
    kill -0 "$pid" 2>/dev/null || break
    compgen -G "$work/clishe-practice.*" > /dev/null || break
    sleep 0.1
done
cleaned=$(date +%s)
kill -9 "$pid" 2>/dev/null
exec 7>&-
wait "$pid" 2>/dev/null
left=$(compgen -G "$work/clishe-practice.*" | wc -l | tr -d ' ')
saved=$(cat "$home/.local/share/clishe/practice_done_basics" 2>/dev/null || echo none)
# If it failed, say on stderr how long things took: stdout has to stay
# exactly "<left> <saved>" because the caller compares it to a fixed string.
if [ "$left" != "0" ]; then
    echo "stop_practice.sh: $left folder(s) left after SIG$sig;" \
         "folder appeared +$((signalled - started))s, still there" \
         "$((cleaned - signalled))s after the signal" >&2
fi
echo "$left $saved"
rm -rf "$work" "$home"
