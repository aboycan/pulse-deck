# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""PulseDeck setup - double-click this file on Windows, or run `python install.py`.

NOTE: An internet connection is required for the first-time setup (Python packages and
the libmpv audio engine are downloaded, about 150 MB).

Add --dev to also install the test tools (pytest etc.) for development.

Runs through the signed Python launcher, so Windows Smart App Control allows it
(unlike .bat files downloaded from the internet). Safe to run again at any
time: it only redoes what is missing and refreshes the PulseDeck shortcuts.
"""

import sys
from pathlib import Path

MIN_PYTHON = (3, 11)


def pause() -> None:
    # Keep the window open when started by double-click.
    if sys.platform.startswith("win") and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"PulseDeck needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer (this is {sys.version.split()[0]}).")
        print("Install it from https://www.python.org/downloads/ and run install.py again.")
        pause()
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
    import setup_dev

    try:
        code = setup_dev.main()
    except SystemExit as exc:  # setup_dev reports fatal problems this way
        if exc.code not in (0, None):
            print(exc.code if isinstance(exc.code, str) else "")
        code = 1 if exc.code not in (0, None) else 0
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        code = 1
    pause()
    return code


if __name__ == "__main__":
    sys.exit(main())
