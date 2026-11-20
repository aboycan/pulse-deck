# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""JSON configuration with defaults, dotted-key access and atomic saves."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pulsedeck.core import platform

log = logging.getLogger(__name__)

CONFIG_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "general": {
        "startup": "restore",          # "restore" | "empty" | "library"
        "minimize_to_tray": True,
        "close_to_tray": False,
        "restore_session": True,
        "confirm_delete_playlist": True,
        "notifications": True,
        "single_instance": True,
    },
    "audio": {
        "output_device": "auto",
        "volume": 80,
        "muted": False,
        "balance": 0.0,                # -1.0 (left) .. 1.0 (right)
        "speed": 1.0,
        "crossfade_seconds": 0.0,      # 0 = gapless
        "gapless": True,
        "normalization": False,
        "replaygain": "off",           # "off" | "track" | "album"
        "replaygain_preamp": 0.0,
        "clip_protection": True,
        "seek_step_seconds": 5,
    },
    "equalizer": {
        "enabled": True,
        "bypass": False,
        "preamp": 0.0,
        "auto_preamp": True,
        "gains": [0.0] * 10,
        "preset": "Flat",
        "default_preset": "Flat",
    },
    "playback": {
        "shuffle": False,
        "repeat": "off",               # "off" | "one" | "all"
    },
    "library": {
        "folders": [],
        "default_music_dir": "",
        "auto_scan": True,
        "duplicate_detection": "path+metadata",  # "path" | "path+metadata"
        "columns": ["title", "artist", "album", "duration", "genre", "year"],
        "show_bitrate": True,
    },
    "interface": {
        "theme": "classic_dark",
        "accent_color": "",
        "font_size": 10,
        "compact_mode": False,
        "always_on_top": False,
        "panels": {
            "playlist": True,
            "equalizer": False,
            "library": False,
            "info": False,
        },
        "geometry": {},
    },
    "shortcuts": {},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Configuration:
    """Application settings persisted as ``settings.json``."""

    FILE_NAME = "settings.json"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or platform.config_dir() / self.FILE_NAME
        self._data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, Any], None]] = []

    # -- persistence -----------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._data = copy.deepcopy(DEFAULTS)
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("settings root is not an object")
            except (OSError, ValueError) as exc:
                log.warning("Settings file unreadable (%s); using defaults", exc)
                backup = self.path.with_suffix(".corrupt.json")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                self._data = copy.deepcopy(DEFAULTS)
                return
            self._data = _deep_merge(DEFAULTS, raw)
            self._data["version"] = CONFIG_VERSION

    def save(self) -> None:
        with self._lock:
            text = json.dumps(self._data, indent=2, sort_keys=True)
        atomic_write_text(self.path, text)

    # -- access ----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        with self._lock:
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            if node.get(parts[-1]) == value:
                return
            node[parts[-1]] = copy.deepcopy(value)
        for listener in list(self._listeners):
            try:
                listener(key, value)
            except Exception:  # pragma: no cover - listener bugs must not break settings
                log.exception("Configuration listener failed for %s", key)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            with self._lock:
                self._data = copy.deepcopy(DEFAULTS)
            return
        node: Any = DEFAULTS
        for part in key.split("."):
            node = node[part]
        self.set(key, copy.deepcopy(node))

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        self._listeners.append(callback)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)
