"""
The `clishe` command when Clishe is installed with pipx or pip. It runs the
bundled clishe.sh with bash, exactly like the git install does.
"""
import os
import shutil
import sys
from pathlib import Path


WINDOWS_MESSAGE = (
    "Clishe runs on Linux and macOS, not directly on Windows.\n"
    "To use it on Windows, install WSL (Windows Subsystem for Linux):\n"
    "  1. Open PowerShell and type: wsl --install\n"
    "  2. Restart, open the new Ubuntu app, and install Clishe there:\n"
    "     sudo apt install pipx && pipx install clishe\n"
    "More about WSL: https://learn.microsoft.com/windows/wsl/install"
)


def main():
    # On Windows, `bash` may be Git Bash or WSL's launcher, and `python3`
    # a Microsoft Store shortcut: Clishe would start but quietly do nothing.
    if sys.platform == "win32":
        print(WINDOWS_MESSAGE, file=sys.stderr)
        return 1
    bash = shutil.which("bash")
    if not bash:
        print("Clishe needs bash, which wasn't found on this system.", file=sys.stderr)
        return 1
    script = Path(__file__).resolve().parent / "clishe.sh"
    os.execv(bash, [bash, str(script), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
