# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Platform detection, per-user directories and file-manager integration.

Only the standard library is used here so the module can be imported by
tests and build scripts without Qt being installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pulsedeck import APP_NAME

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

#: Environment variable that relocates every per-user directory (portable
#: mode, tests, CI).
HOME_OVERRIDE_ENV = "PULSEDECK_HOME"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory holding bundled resources (PyInstaller-aware)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    if is_frozen():
        return bundle_dir() / "pulsedeck" / "assets"
    return bundle_dir() / "assets"


def _override_root() -> Path | None:
    value = os.environ.get(HOME_OVERRIDE_ENV)
    return Path(value).expanduser() if value else None


def config_dir() -> Path:
    root = _override_root()
    if root:
        path = root / "config"
    elif IS_WINDOWS:
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif IS_MACOS:
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "pulsedeck"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    root = _override_root()
    if root:
        path = root / "data"
    elif IS_WINDOWS:
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif IS_MACOS:
        path = Path.home() / "Library" / "Application Support" / APP_NAME / "Data"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pulsedeck"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    root = _override_root()
    if root:
        path = root / "cache"
    elif IS_WINDOWS:
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME / "Cache"
    elif IS_MACOS:
        path = Path.home() / "Library" / "Caches" / APP_NAME
    else:
        path = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pulsedeck"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_music_dir() -> Path:
    candidate = Path.home() / "Music"
    return candidate if candidate.is_dir() else Path.home()


def normalize_path(path: str | os.PathLike[str]) -> str:
    """Canonical key for a file path, used for duplicate detection.

    Resolves symlinks and ``..`` segments and folds case on case-insensitive
    platforms (Windows always, macOS default APFS volumes).
    """
    p = os.path.abspath(os.path.expanduser(os.fspath(path)))
    try:
        p = os.path.realpath(p)
    except OSError:
        pass
    p = os.path.normpath(p)
    if IS_WINDOWS or IS_MACOS:
        p = os.path.normcase(p) if IS_WINDOWS else p.casefold()
    return p


def reveal_in_file_manager(path: str | os.PathLike[str]) -> bool:
    """Select ``path`` in Explorer/Finder, or open its folder on Linux."""
    target = Path(path)
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603,S607
        elif IS_MACOS:
            subprocess.Popen(["open", "-R", str(target)])  # noqa: S603,S607
        else:
            # Try the freedesktop FileManager1 interface first, fall back to xdg-open.
            uri = target.resolve().as_uri()
            try:
                subprocess.Popen(  # noqa: S603
                    [
                        "dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                        "--type=method_call", "/org/freedesktop/FileManager1",
                        "org.freedesktop.FileManager1.ShowItems",
                        f"array:string:{uri}", "string:",
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                return open_folder(target.parent)
        return True
    except OSError:
        return False


def open_folder(path: str | os.PathLike[str]) -> bool:
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    try:
        if IS_WINDOWS:
            os.startfile(str(folder))  # type: ignore[attr-defined]  # noqa: S606
        elif IS_MACOS:
            subprocess.Popen(["open", str(folder)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603,S607
        return True
    except OSError:
        return False


def windows_app_identity_values(display_name: str, icon_path: str | os.PathLike[str] | None) -> dict[str, str]:
    """Registry values that make Windows show ``display_name`` (not the raw app ID) on notifications."""
    values = {"DisplayName": display_name}
    if icon_path and os.path.exists(icon_path):
        values["IconUri"] = os.path.abspath(os.fspath(icon_path))
    return values


def register_windows_app_identity(app_id: str, display_name: str,
                                  icon_path: str | os.PathLike[str] | None = None) -> bool:
    """Register the AppUserModelID under HKCU so notifications are titled with the app's name.

    Without this, Windows labels notifications from unpackaged apps with the
    raw ID (e.g. "io.github.pulsedeck.PulseDeck"). Per-user, no admin needed,
    and safe to call on every start.
    """
    if not IS_WINDOWS:
        return False
    try:
        import winreg  # noqa: PLC0415

        key_path = rf"Software\Classes\AppUserModelId\{app_id}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in windows_app_identity_values(display_name, icon_path).items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        return True
    except OSError:
        return False


def platform_name() -> str:
    if IS_WINDOWS:
        return "windows"
    if IS_MACOS:
        return "macos"
    return "linux"
