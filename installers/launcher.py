# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""PyInstaller entry script for PulseDeck."""

import sys

from pulsedeck.main import main

if __name__ == "__main__":
    sys.exit(main())
