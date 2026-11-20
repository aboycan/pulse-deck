# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Uninstall PulseDeck (source setup) - double-click on Windows, or run `python uninstall.py`.

Removes, after asking:
  * the PulseDeck shortcuts (Start Menu, Desktop, this folder) and the Windows
    notification-name registration;
  * the private Python environment (.venv) and the downloaded audio engine,
    about 350 MB - after this you can simply delete the PulseDeck folder;
  * optionally, your settings, playlists, library database, equalizer presets,
    original-tag backups, artwork cache and logs.

Your music files are never touched. For the packaged Windows installer use
"Add or remove programs" instead; this script is for the install.py setup.

Options: --yes (no questions: remove shortcuts and .venv, keep your data)
         --remove-data (with --yes: also delete settings, playlists and library)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
APP_ID = "io.github.pulsedeck.PulseDeck"


def pause() -> None:
    if IS_WINDOWS and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass


def ask(question: str, default: bool, assume: bool | None) -> bool:
    if assume is not None:
        return assume
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer in ("y", "yes")


def user_data_dirs() -> list[Path]:
    """Where PulseDeck keeps settings and data (mirrors pulsedeck.core.platform)."""
    override = os.environ.get("PULSEDECK_HOME")
    if override:
        return [Path(override).expanduser()]
    home = Path.home()
    if IS_WINDOWS:
        return [Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "PulseDeck",
                Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "PulseDeck"]
    if IS_MACOS:
        return [home / "Library" / "Application Support" / "PulseDeck", home / "Library" / "Caches" / "PulseDeck"]
    return [Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "pulsedeck",
            Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "pulsedeck",
            Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "pulsedeck"]


def windows_shortcuts() -> list[Path]:
    paths = [ROOT / "PulseDeck.lnk"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        paths += [start_menu / "PulseDeck.lnk", start_menu / "Uninstall PulseDeck.lnk"]
    desktops = {Path.home() / "Desktop"}
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=30)
        if out.stdout.strip():
            desktops.add(Path(out.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    paths += [d / "PulseDeck.lnk" for d in desktops]
    return paths


def unregister_windows_identity() -> None:
    try:
        import winreg

        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{APP_ID}")
        print("  Removed notification-name registration")
    except OSError:
        pass  # not registered


def environment_paths() -> list[Path]:
    return [ROOT / ".venv", ROOT / "src" / "pulsedeck" / "audio" / "lib", ROOT / "src" / "pulsedeck.egg-info",
            ROOT / "build", ROOT / "dist"]


def remove(path: Path, failures: list[str]) -> None:
    if not (path.exists() or path.is_symlink()):
        return
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        print(f"  Removed {path}")
    except OSError as exc:
        failures.append(f"{path} ({exc.strerror or exc})")


def relaunch_outside_venv() -> None:
    """Python inside .venv cannot delete .venv on Windows, so restart with the base interpreter."""
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv and Path(sys.prefix).resolve() == (ROOT / ".venv").resolve():
        base = getattr(sys, "_base_executable", None)
        if base and Path(base).exists() and Path(base).resolve() != Path(sys.executable).resolve():
            raise SystemExit(subprocess.call([base, str(Path(__file__).resolve()), *sys.argv[1:]]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Uninstall PulseDeck (source setup)")
    parser.add_argument("--yes", "-y", action="store_true", help="don't ask; keep your data unless --remove-data")
    parser.add_argument("--remove-data", action="store_true", help="also delete settings, playlists and library")
    args = parser.parse_args()
    relaunch_outside_venv()

    print("PulseDeck uninstaller")
    print("Your music files are never touched.")
    print("Please close PulseDeck first (right-click the tray icon > Quit).\n")
    yes = True if args.yes else None
    failures: list[str] = []

    if not ask("Remove the PulseDeck shortcuts?", True, yes):
        print("Nothing removed.")
        pause()
        return 0
    if IS_WINDOWS:
        for shortcut in windows_shortcuts():
            remove(shortcut, failures)
        unregister_windows_identity()

    if ask("Remove the Python environment and audio engine from this folder (about 350 MB)?", True, yes):
        for path in environment_paths():
            remove(path, failures)

    data = [d for d in user_data_dirs() if d.exists()]
    if data:
        print("\nYour PulseDeck data (settings, playlists, library, EQ presets, original-tag backups, logs):")
        for d in data:
            print(f"  {d}")
        if ask("Delete this data too? This cannot be undone.", False, args.remove_data if args.yes else None):
            for d in data:
                remove(d, failures)
        else:
            print("  Kept - a future install will pick it up again.")

    if failures:
        print("\nSome items could not be removed (is PulseDeck still running?):")
        for item in failures:
            print(f"  {item}")
        print("Close PulseDeck and run uninstall.py again.")
        pause()
        return 1
    print("\nPulseDeck has been uninstalled. You can now delete this folder.")
    pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
