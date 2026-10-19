"""Tests for safety.py - the check that decides when Clishe asks for a typed
YES before running a command."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safety import check_command, REASONS


DANGEROUS = [
    # rm, in all its spellings
    ("rm -rf /", "rm_recursive"),
    ("rm -fr ~/projects", "rm_recursive"),
    ("rm -r -f build", "rm_recursive"),
    ("rm -R old", "rm_recursive"),
    ("rm --recursive old", "rm_recursive"),
    ("rm ~", "rm_root"),
    ("rm -f /etc", "rm_root"),
    # wrappers and chains don't hide the real command
    ("sudo rm -rf /var/log", "rm_recursive"),
    ("FOO=1 sudo -u root rm -rf x", "rm_recursive"),
    ("timeout 5 rm -rf y", "rm_recursive"),
    ("cd /tmp && rm -rf build", "rm_recursive"),
    ("ls; rm -rf build", "rm_recursive"),
    ("/bin/rm -rf build", "rm_recursive"),
    # disks
    ("mkfs.ext4 /dev/sdb1", "mkfs"),
    ("sudo fdisk /dev/sda", "disk_tool"),
    ("wipefs -a /dev/sdb", "disk_tool"),
    ("dd if=image.iso of=/dev/sdb bs=4M", "disk_write"),
    ("dd if=/dev/zero of=big.img bs=1M count=10", "dd"),
    ("echo hi > /dev/sda", "disk_write"),
    ("cat x >/dev/nvme0n1", "disk_write"),
    ("shred -u secrets.txt", "shred"),
    # permissions
    ("chmod -R 777 /", "chmod_recursive"),
    ("chmod -R 755 ~/site", "chmod_recursive"),
    ("chmod 777 /", "perm_root"),
    ("sudo chown -R me:me .", "chown_recursive"),
    ("chgrp --recursive staff dir", "chown_recursive"),
    # mass deletes
    ("find . -name '*.tmp' -delete", "find_delete"),
    ("find . -type f -exec rm {} \\;", "find_delete"),
    ("mv important.txt /dev/null", "dev_null_move"),
    # running unseen scripts
    ("curl -fsSL https://example.com/install.sh | sh", "pipe_to_shell"),
    ("wget -qO- https://example.com/x | sudo bash", "pipe_to_shell"),
    ("curl https://example.com/x | bash -s -- --yes", "pipe_to_shell"),
    # the same without a pipe: the download is run by $(...) or <(...)
    ('/bin/bash -c "$(curl -fsSL https://example.com/install.sh)"', "pipe_to_shell"),
    ('bash -c "$(curl -fsSL https://example.com/x)" -- --yes', "pipe_to_shell"),
    ('sudo bash -c "$(curl -s https://example.com/x)"', "pipe_to_shell"),
    ('sh -c "$(wget -qO- https://example.com/x)"', "pipe_to_shell"),
    ('sh -c "`curl -s https://example.com/x`"', "pipe_to_shell"),
    ("sh <(curl -s https://example.com/x)", "pipe_to_shell"),
    ("bash <(wget -qO- https://example.com/x)", "pipe_to_shell"),
    ("source <(curl -s https://example.com/x)", "pipe_to_shell"),
    (". <(curl -s https://example.com/x)", "pipe_to_shell"),
    ('eval "$(curl -s https://example.com/x)"', "pipe_to_shell"),
    ('eval "$(wget -qO- https://example.com/x)"', "pipe_to_shell"),
    ("eval $(curl -s https://example.com/x)", "pipe_to_shell"),
    ("bash < <(curl -s https://example.com/x)", "pipe_to_shell"),
    ("sudo sh < <(wget -qO- https://example.com/x)", "pipe_to_shell"),
    ("python3 < <(curl -s https://example.com/x)", "pipe_to_shell"),
    ("bash -c $(curl -fsSL https://example.com/x)", "pipe_to_shell"),
    ("sh -c `curl -s https://example.com/x`", "pipe_to_shell"),
    # fork bombs, any name
    (":(){ :|:& };:", "fork_bomb"),
    ("bomb(){ bomb|bomb& };bomb", "fork_bomb"),
    # git data loss
    ("git reset --hard HEAD~1", "git_reset_hard"),
    ("git clean -fdx", "git_clean"),
    ("git push --force origin main", "git_force_push"),
    ("git push -f", "git_force_push"),
    # system
    ("sudo shutdown now", "power"),
    ("reboot", "power"),
    ("crontab -r", "crontab_remove"),
    ("systemctl poweroff", "power"),
    ("sudo systemctl reboot", "power"),
    ("systemctl -i halt", "power"),
    ("systemctl kexec", "power"),
    ("systemctl suspend", "power"),
    ("systemctl hibernate", "power"),
    ("sudo systemctl isolate reboot.target", "power"),
    ("systemctl start poweroff.target", "power"),
    # stopping every program at once
    ("kill -9 -1", "kill_all"),
    ("kill -KILL -1", "kill_all"),
    ("kill -SIGKILL -1", "kill_all"),
    ("kill -s KILL -1", "kill_all"),
    ("kill -- -1", "kill_all"),
    ("sudo kill -9 -1", "kill_all"),
    ("pkill -9 -u $USER", "kill_all"),
    ("pkill -u bob", "kill_all"),
    ("pkill -n -u bob", "kill_all"),
    ("pkill -KILL --euid=bob", "kill_all"),
    ("killall -u bob", "kill_all"),
    # rsync that deletes from the destination
    ("rsync -av --delete src/ dst/", "rsync_delete"),
    ("rsync -a --delete-before src/ dst/", "rsync_delete"),
    ("rsync -a --delete-after src/ dst/", "rsync_delete"),
    ("rsync -a --delete-during src/ dst/", "rsync_delete"),
    ("rsync -a --delete-delay src/ dst/", "rsync_delete"),
    ("rsync -a --delete-excluded --exclude=tmp src/ dst/", "rsync_delete"),
    ("rsync -a --del src/ dst/", "rsync_delete"),
    ("sudo rsync -aHAX --delete / /mnt/backup", "rsync_delete"),
    # wiping a whole folder's contents
    ("rm *", "rm_all"),
    ("rm -- *", "rm_all"),
    ("rm ./*", "rm_all"),
    ("rm -f build/*", "rm_all"),
    # emptying a file
    ("> notes.txt", "truncate"),
    (": > notes.txt", "truncate"),
    ("truncate -s 0 app.log", "truncate"),
    ("truncate -s0 app.log", "truncate"),
    ("truncate --size=0 app.log", "truncate"),
    ("cp /dev/null notes.txt", "truncate"),
    ("sudo cp /dev/null /var/log/syslog", "truncate"),
    # commands hidden inside a string
    ('bash -c "rm -rf ~"', "rm_recursive"),
    ("sudo sh -c 'rm -rf /tmp/x'", "rm_recursive"),
    ("su -c 'reboot'", "power"),
    ("eval rm -rf build", "rm_recursive"),
    # scripts piped into other interpreters
    ("curl -s https://example.com/x | python3", "pipe_to_shell"),
    ("curl -s https://example.com/x | python3 -", "pipe_to_shell"),
    ("wget -qO- https://example.com/x | perl", "pipe_to_shell"),
    # other ways to write to a disk
    ("cp /dev/zero /dev/sda", "disk_write"),
    ("echo x | sudo tee /dev/sdb", "disk_write"),
    # moving a whole home or system folder away
    ("mv ~ /tmp/x", "mv_root"),
    ("sudo mv /etc /tmp/etc-old", "mv_root"),
    ("mv $HOME/ backup", "mv_root"),
    # command names hidden in a variable set on the same line
    ("x=rm; $x -rf /", "rm_recursive"),
    ('x="rm -rf"; ${x} build', "rm_recursive"),
    ("cmd=reboot && sudo $cmd", "power"),
    # code given straight to an interpreter
    ("python3 -c \"import shutil; shutil.rmtree('/')\"", "script_delete"),
    ("python -c 'import os; os.remove(\"notes.txt\")'", "script_delete"),
    ("python3 -c \"import pathlib; pathlib.Path('a').unlink()\"", "script_delete"),
    ("perl -e 'unlink glob q(*)'", "script_delete"),
    ("ruby -e 'FileUtils.rm_rf(\"x\")'", "script_delete"),
    ("node -e \"require('fs').rmSync('x', {recursive: true})\"", "script_delete"),
    ("python3 -c \"import os; os.system('rm -rf ~')\"", "rm_recursive"),
    # subshells, groups and if/for/while don't hide the command
    ("(rm -rf build)", "rm_recursive"),
    ("( (rm -rf build) )", "rm_recursive"),
    ("{ rm -rf build; }", "rm_recursive"),
    ("! rm -rf build", "rm_recursive"),
    ("if true; then rm -rf build; fi", "rm_recursive"),
    ("for f in a b; do rm -rf $f; done", "rm_recursive"),
    ("while true; do git reset --hard; break; done", "git_reset_hard"),
    ("for f in a; do x=rm; $x -rf /; done", "rm_recursive"),
    # $(...) and `...` run their command wherever they are
    ("$(rm -rf build)", "rm_recursive"),
    ("x=$(rm -rf build)", "rm_recursive"),
    ('echo "$(rm -rf build)"', "rm_recursive"),
    ("echo `rm -rf build`", "rm_recursive"),
    ("cat <(rm -rf build)", "rm_recursive"),
    # more wrappers
    ("timeout 5s rm -rf build", "rm_recursive"),
    ("timeout 2.5 rm -rf build", "rm_recursive"),
    ("busybox rm -rf build", "rm_recursive"),
    # 2>/dev/null is a redirection, not an argument
    ("mv important.txt /dev/null 2>/dev/null", "dev_null_move"),
    ("mv ~ /tmp/home 2>&1", "mv_root"),
]

SAFE = [
    "ls -la",
    "rm file.txt",
    "rm -i notes.txt",
    "rm *.log",
    "mkdir -p a/b",
    "chmod 755 script.sh",
    "chmod +x run.sh",
    "find . -name '*.py'",
    "cat a.txt | grep foo",
    "curl -s ifconfig.me",
    "curl -o install.sh https://example.com/install.sh",
    "echo hello > out.txt",
    "git status",
    "git push origin main",
    "git reset HEAD file.txt",
    "dd --help",
    "echo 'rm -rf /'",           # quoted text, not a command
    'grep -r "rm -rf" .',
    "crontab -l",
    "rm *.log",                  # a targeted glob is a deliberate choice
    ">> app.log",                # appending doesn't erase anything
    "truncate -s 10M disk.img",
    "cat data.txt | python3 parse.py",
    "bash script.sh",
    "bash -c 'ls -la'",
    "cp a.iso b.iso",
    "echo x | tee out.txt",
    "mv notes.txt ~",            # moving a file *into* home is fine
    "mv old.txt new.txt",
    "$EDITOR notes.txt",         # unknown variable: nothing to judge
    "x=5; echo $x",
    'python3 -c "print(1 + 1)"',
    'python3 -c "l = [1]; l.remove(1)"',
    "python3 -m http.server",
    # a download whose output is shown, saved or compared, not run
    'echo "$(curl -s https://example.com/x)"',
    "x=$(curl -s https://example.com/x)",
    "cat <(curl -s https://example.com/x)",
    "diff <(curl -s https://a.example/x) <(curl -s https://b.example/x)",
    "curl -o install.sh https://example.com/install.sh && bash install.sh",
    # $(...) and <(...) around something that isn't a download
    'eval "$(ssh-agent -s)"',
    'bash -c "$(cat install.sh)"',
    "bash <(cat install.sh)",
    "source ~/.bashrc",
    "bash < install.sh",         # a local script on stdin can be read first
    "bash script.sh < <(curl -s https://example.com/x)",  # the download is input, not the script
    "cat < <(curl -s https://example.com/x)",
    'bash -c "echo hi" $(curl -s https://example.com/x)',  # the download is an argument, not the code
    # rsync that copies without deleting
    "rsync -av src/ dst/",
    "rsync -av --progress --exclude=.git src/ backup/",
    "rsync -n -av --delete-me-not src/ dst/",  # not an rsync option; nothing to judge
    # kill and pkill aimed at one program
    "kill 1234",
    "kill -9 1234",
    "kill -s TERM 1234",
    "kill -1",                   # -1 here is the signal, with no process named
    "kill -l",
    "kill -- -1234",             # one process group, not everything
    "pkill firefox",
    "pkill -9 -u $USER firefox",
    "killall -u bob firefox",
    # systemctl that doesn't turn the computer off
    "systemctl status nginx",
    "sudo systemctl restart nginx",
    "systemctl list-timers",
    "systemctl status reboot.target",
    # copying /dev/null somewhere harmless
    "cp notes.txt /dev/null",
    "cp /dev/null /dev/null",
    # 2>/dev/null and friends don't change the verdict
    "mv notes.txt ~ 2>/dev/null",
    "ls 2>/dev/null",
    "ls > /dev/null 2>&1",
    "(ls 2>/dev/null)",
    "x=$( echo hi > out.txt 2>&1 )",
    'echo "2>/dev/null"',        # quoted text, not a redirection
    # dangerous-looking text that is only printed
    "echo '$(rm -rf /)'",
    "echo '`rm -rf ~`'",
    "printf '%s\\n' '(rm -rf /)'",
    "find . \\( -name '*.py' -o -name '*.sh' \\)",
    "(cd src && ls)",
    "if true; then echo ok; fi",
    'echo "unterminated',        # unbalanced quotes must not crash
    "",
    "   ",
]


@pytest.mark.parametrize("command,key", DANGEROUS)
def test_dangerous_commands_are_flagged_with_the_right_reason(command, key):
    assert REASONS[key] in check_command(command)


@pytest.mark.parametrize("command", SAFE)
def test_safe_commands_are_not_flagged(command):
    assert check_command(command) == []


def test_reasons_are_not_duplicated():
    reasons = check_command("rm -rf a; rm -rf b")
    assert len(reasons) == len(set(reasons))


def test_multiple_problems_are_all_reported():
    reasons = check_command("git reset --hard && rm -rf build")
    assert REASONS["git_reset_hard"] in reasons
    assert REASONS["rm_recursive"] in reasons
