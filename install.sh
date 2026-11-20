#!/usr/bin/env bash
# PulseDeck one-step setup for macOS and Linux.
# INTERNET CONNECTION REQUIRED: downloads Python packages and the libmpv audio engine
# (and Python itself if a 3.11+ version is missing).
set -euo pipefail
cd "$(dirname "$0")"
echo
echo " PulseDeck setup"
echo " NOTE: An internet connection is required for this first-time setup."
echo

find_python() {
    for c in python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
            echo "$c"; return 0
        fi
    done
    return 1
}

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
PY="$(find_python || true)"

if [ -z "$PY" ]; then
    echo "Python 3.11+ was not found."
    read -r -p "Install Python now (internet required)? [Y/n] " answer
    case "${answer:-y}" in [Nn]*) exit 1 ;; esac
    if [ "$(uname)" = "Darwin" ]; then
        command -v brew >/dev/null 2>&1 || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
        brew install python@3.12
    elif command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update
        $SUDO apt-get install -y python3.12 python3.12-venv || $SUDO apt-get install -y python3.11 python3.11-venv
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y python3.12 || $SUDO dnf install -y python3.11
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO zypper --non-interactive install python312 || $SUDO zypper --non-interactive install python311
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -S --needed --noconfirm python
    else
        echo "Please install Python 3.11 or newer with your package manager, then run ./install.sh again."; exit 1
    fi
    PY="$(find_python || true)"
    [ -n "$PY" ] || { echo "Python 3.11+ still not found."; exit 1; }
fi

# Debian/Ubuntu split venv support into a separate package.
if ! "$PY" -c 'import ensurepip' >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
    v="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    echo "Installing python$v-venv (needed for a private environment)..."
    $SUDO apt-get install -y "python$v-venv"
fi

echo "Using Python: $PY ($("$PY" --version))"
"$PY" scripts/setup_dev.py "$@"
chmod +x run.sh
echo
echo "Done. Start PulseDeck with: ./run.sh"
