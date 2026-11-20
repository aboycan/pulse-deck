# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Right-click context menus.

Menu contents are declared as plain data (``MenuItem`` lists) so the same
definitions drive every platform and can be checked by tests without a
display. :func:`build_menu` turns a definition into a ``QMenu``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pulsedeck.core import platform


@dataclass(frozen=True)
class MenuItem:
    id: str
    label: str
    shortcut: str = ""
    children_from: str = ""      # name of a dynamic submenu source (e.g. "playlists")


SEPARATOR = MenuItem("-", "")


def reveal_label() -> str:
    if platform.IS_WINDOWS:
        return "Show in File Explorer"
    if platform.IS_MACOS:
        return "Show in Finder"
    return "Show in File Manager"


def song_menu_items() -> list[MenuItem]:
    return [
        MenuItem("play", "Play"),
        MenuItem("play_next", "Play Next"),
        SEPARATOR,
        MenuItem("add_current", "Add to Current Playlist"),
        MenuItem("add_new", "Add to New Playlist…"),
        MenuItem("add_to", "Add to Playlist", children_from="playlists"),
        SEPARATOR,
        MenuItem("remove_playlist", "Remove from Playlist", "Del"),
        MenuItem("remove_library", "Remove from Library"),
        SEPARATOR,
        MenuItem("reveal", reveal_label()),
        MenuItem("open_folder", "Open Containing Folder"),
        MenuItem("copy_path", "Copy File Path"),
        SEPARATOR,
        MenuItem("info", "View Song Information"),
        MenuItem("edit", "Edit Metadata…"),
        MenuItem("favourite", "Set as Favourite"),
    ]


def playlist_menu_items() -> list[MenuItem]:
    return [
        MenuItem("play_playlist", "Play Playlist"),
        MenuItem("shuffle_playlist", "Shuffle Playlist"),
        SEPARATOR,
        MenuItem("rename_playlist", "Rename Playlist…", "F2"),
        MenuItem("duplicate_playlist", "Duplicate Playlist"),
        MenuItem("export_playlist", "Export Playlist…"),
        SEPARATOR,
        MenuItem("clear_playlist", "Clear Playlist"),
        MenuItem("delete_playlist", "Delete Playlist"),
    ]


def group_menu_items(kind: str) -> list[MenuItem]:
    """Menu for an album or artist row; ``kind`` is "album" or "artist"."""
    return [
        MenuItem("play_all", "Play All"),
        MenuItem("add_group_to", "Add to Playlist", children_from="playlists"),
        SEPARATOR,
        MenuItem("view_albums", "View Albums" if kind == "artist" else "View Album Tracks"),
        MenuItem("view_group_info", "View Information"),
    ]


@dataclass
class MenuContext:
    """Which actions are enabled and any label overrides."""

    disabled: set[str] = field(default_factory=set)
    hidden: set[str] = field(default_factory=set)
    labels: dict[str, str] = field(default_factory=dict)
    dynamic: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # source -> [(value, label)]


def resolve(items: list[MenuItem], ctx: MenuContext) -> list[tuple[MenuItem, bool, str]]:
    """Apply a context: returns ``(item, enabled, label)`` without Qt."""
    result: list[tuple[MenuItem, bool, str]] = []
    for item in items:
        if item.id in ctx.hidden:
            continue
        if item is SEPARATOR or item.id == "-":
            if result and result[-1][0].id != "-":
                result.append((item, True, ""))
            continue
        result.append((item, item.id not in ctx.disabled, ctx.labels.get(item.id, item.label)))
    while result and result[-1][0].id == "-":
        result.pop()
    return result


def build_menu(items: list[MenuItem], ctx: MenuContext, handler: Callable[[str, str | None], None],
               parent=None):  # noqa: ANN001 - QWidget, kept untyped to avoid importing Qt at module load
    """Create a QMenu. ``handler(action_id, value)`` is called on selection."""
    from PySide6.QtGui import QAction, QKeySequence  # noqa: PLC0415
    from PySide6.QtWidgets import QMenu  # noqa: PLC0415

    menu = QMenu(parent)
    for item, enabled, label in resolve(items, ctx):
        if item.id == "-":
            menu.addSeparator()
            continue
        if item.children_from:
            sub = menu.addMenu(label)
            choices = ctx.dynamic.get(item.children_from, [])
            if not choices:
                empty = sub.addAction("(none)")
                empty.setEnabled(False)
            for value, text in choices:
                action = sub.addAction(text)
                action.triggered.connect(lambda _=False, i=item.id, v=value: handler(i, v))
            sub.setEnabled(enabled)
            continue
        action = QAction(label, menu)
        if item.shortcut:
            action.setShortcut(QKeySequence(item.shortcut))
            action.setShortcutVisibleInContextMenu(True)
        action.setEnabled(enabled)
        action.triggered.connect(lambda _=False, i=item.id: handler(i, None))
        menu.addAction(action)
    return menu
