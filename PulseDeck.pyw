# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Double-click to start PulseDeck.

This launcher is used instead of a .bat file because Windows Smart App Control
blocks batch files that came from the internet. A .pyw file runs through the
signed Python launcher, so it is allowed, and it opens no console window.

If PulseDeck has not been set up yet, it opens the installer (install.py).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform.startswith("win")
VENV_PYTHON = ROOT / ".venv" / ("Scripts/pythonw.exe" if IS_WINDOWS else "bin/python")


def show_error(message: str) -> None:
    if IS_WINDOWS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "PulseDeck", 0x10)
    else:
        print(message, file=sys.stderr)


def main() -> None:
    try:
        if VENV_PYTHON.exists():
            subprocess.Popen([str(VENV_PYTHON), "-m", "pulsedeck.main", *sys.argv[1:]], cwd=ROOT)
            return
        # Not set up yet: run the installer in a visible console window.
        console_python = Path(sys.executable)
        if console_python.name.lower() == "pythonw.exe":
            console_python = console_python.with_name("python.exe")
        flags = subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0
        subprocess.Popen([str(console_python), str(ROOT / "install.py")], cwd=ROOT, creationflags=flags)
    except Exception as exc:  # pythonw has no console, so show problems in a dialog
        show_error(f"PulseDeck could not start:\n\n{exc}\n\nTry double-clicking install.py to repair the setup.")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
