# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Shared handling of song context-menu actions (playlist and library views)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QWidget

from pulsedeck.core import platform
from pulsedeck.ui.context_menus import MenuContext, build_menu, song_menu_items


def playlist_choices(controller) -> list[tuple[str, str]]:  # noqa: ANN001
    return [(p.id, p.name) for p in controller.playlists.all()]


def song_menu_context(controller, paths: list[str], in_playlist: bool, in_library: bool) -> MenuContext:  # noqa: ANN001
    ctx = MenuContext(dynamic={"playlists": playlist_choices(controller)})
    if not in_playlist:
        ctx.disabled.add("remove_playlist")
    if not in_library:
        ctx.disabled.add("remove_library")
    if len(paths) != 1:
        ctx.disabled.update({"info", "edit", "reveal", "open_folder"})
    exists = [p for p in paths if os.path.isfile(p)]
    if not exists:
        ctx.disabled.update({"play", "play_next", "reveal", "open_folder", "info", "edit"})
    if paths and all(controller.db.is_favourite(p) for p in paths):
        ctx.labels["favourite"] = "Remove from Favourites"
    if len(paths) > 1:
        ctx.labels["copy_path"] = "Copy File Paths"
    return ctx


def exec_song_menu(parent: QWidget, controller, paths: list[str], global_pos, *,  # noqa: ANN001
                   playlist_id: str | None = None, indices: list[int] | None = None,
                   in_library: bool = False, play_handler=None) -> None:  # noqa: ANN001
    if not paths:
        return
    ctx = song_menu_context(controller, paths, playlist_id is not None, in_library)

    def handler(action: str, value: str | None) -> None:
        handle_song_action(parent, controller, action, value, paths, playlist_id=playlist_id,
                           indices=indices or [], play_handler=play_handler)

    build_menu(song_menu_items(), ctx, handler, parent).exec(global_pos)


def handle_song_action(parent: QWidget, controller, action: str, value: str | None, paths: list[str], *,  # noqa: ANN001,C901
                       playlist_id: str | None = None, indices: list[int] | None = None,
                       play_handler=None) -> None:  # noqa: ANN001
    c = controller
    if action == "play":
        if play_handler is not None:
            play_handler()
        else:
            c.add_paths(c.active_playlist.id, paths, play=True)
    elif action == "play_next":
        c.play_paths_next(paths)
    elif action == "add_current":
        c.add_paths(c.active_playlist.id, paths)
        c.message.emit(f"Added {len(paths)} track(s) to '{c.active_playlist.name}'")
    elif action == "add_new":
        name, ok = QInputDialog.getText(parent, "New playlist", "Playlist name:",
                                        text=c.playlists.unique_name("New playlist"))
        if ok and name.strip():
            playlist = c.new_playlist(name.strip(), paths)
            c.message.emit(f"Created '{playlist.name}'")
    elif action in ("add_to", "add_group_to") and value:
        c.add_paths(value, paths)
        target = c.playlists.get(value)
        c.message.emit(f"Added {len(paths)} track(s) to '{target.name if target else ''}'")
    elif action == "remove_playlist" and playlist_id is not None:
        c.remove_entries(playlist_id, indices or [])
    elif action == "remove_library":
        answer = QMessageBox.question(
            parent, "Remove from library",
            f"Remove {len(paths)} track(s) from the library?\n\nThe files themselves are not deleted.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            c.remove_from_library(paths)
    elif action == "reveal":
        if not platform.reveal_in_file_manager(paths[0]):
            c.message.emit("Could not open the file manager")
    elif action == "open_folder":
        if not platform.open_folder(os.path.dirname(paths[0])):
            c.message.emit("Could not open the folder")
    elif action == "copy_path":
        QApplication.clipboard().setText("\n".join(paths))
        c.message.emit("Path copied to clipboard" if len(paths) == 1 else f"{len(paths)} paths copied")
    elif action == "info":
        c.show_info_requested.emit(paths[0], False)
    elif action == "edit":
        c.show_info_requested.emit(paths[0], True)
    elif action == "favourite":
        make_fav = not all(c.db.is_favourite(p) for p in paths)
        for path in paths:
            c.set_favourite(path, make_fav)
        c.message.emit("Added to favourites" if make_fav else "Removed from favourites")
