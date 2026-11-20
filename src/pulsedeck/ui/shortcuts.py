# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Configurable keyboard shortcuts.

On macOS Qt maps "Ctrl" to the Command key automatically, so the defaults
below follow each platform's conventions without per-platform tables.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortcutAction:
    id: str
    label: str
    default: str


ACTIONS: tuple[ShortcutAction, ...] = (
    ShortcutAction("play_pause", "Play / Pause", "Space"),
    ShortcutAction("stop", "Stop", "Ctrl+."),
    ShortcutAction("open_files", "Open files", "Ctrl+O"),
    ShortcutAction("open_folder", "Open folder", "Ctrl+Shift+O"),
    ShortcutAction("save_playlist", "Save playlist", "Ctrl+S"),
    ShortcutAction("new_playlist", "New playlist", "Ctrl+N"),
    ShortcutAction("search", "Search", "Ctrl+F"),
    ShortcutAction("next", "Next track", "Ctrl+Right"),
    ShortcutAction("previous", "Previous track", "Ctrl+Left"),
    ShortcutAction("volume_up", "Volume up", "Ctrl+Up"),
    ShortcutAction("volume_down", "Volume down", "Ctrl+Down"),
    ShortcutAction("mute", "Mute / unmute", "Ctrl+M"),
    ShortcutAction("forward", "Fast forward", "Shift+Right"),
    ShortcutAction("rewind", "Rewind", "Shift+Left"),
    ShortcutAction("shuffle", "Toggle shuffle", "Ctrl+H"),
    ShortcutAction("repeat", "Cycle repeat mode", "Ctrl+R"),
    ShortcutAction("toggle_playlist", "Show/hide playlist editor", "Ctrl+1"),
    ShortcutAction("toggle_equalizer", "Show/hide equalizer", "Ctrl+2"),
    ShortcutAction("toggle_library", "Show/hide library", "Ctrl+3"),
    ShortcutAction("toggle_info", "Show/hide audio information", "Ctrl+4"),
    ShortcutAction("settings", "Settings", "Ctrl+,"),
    ShortcutAction("quit", "Quit", "Ctrl+Q"),
)
# "Escape closes the active dialog" is handled natively by every QDialog.

ACTION_IDS = {a.id for a in ACTIONS}


def defaults() -> dict[str, str]:
    return {a.id: a.default for a in ACTIONS}


def effective(overrides: dict[str, str] | None) -> dict[str, str]:
    result = defaults()
    for key, value in (overrides or {}).items():
        if key in ACTION_IDS and isinstance(value, str):
            result[key] = value
    return result


def conflicts(mapping: dict[str, str]) -> dict[str, list[str]]:
    """Key sequences bound to more than one action."""
    seen: dict[str, list[str]] = {}
    for action, seq in mapping.items():
        if seq:
            seen.setdefault(seq.casefold(), []).append(action)
    return {seq: ids for seq, ids in seen.items() if len(ids) > 1}
