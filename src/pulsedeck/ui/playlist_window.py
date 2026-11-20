# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Playlist editor panel."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from pulsedeck.library.models import AUDIO_EXTENSIONS, format_duration
from pulsedeck.playlists.manager import PlaylistError, relink_missing
from pulsedeck.playlists.model import Playlist
from pulsedeck.ui.context_menus import MenuContext, build_menu, playlist_menu_items
from pulsedeck.ui.panels import PanelWindow
from pulsedeck.ui.song_actions import exec_song_menu

ROW_MIME = "application/x-pulsedeck-playlist-rows"
COLUMNS = (("#", None), ("Title", "title"), ("Artist", "artist"), ("Album", "album"), ("Time", "duration"))


class PlaylistModel(QAbstractTableModel):
    def __init__(self, controller, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.playlist: Playlist | None = None
        self.playing_row = -1
        self.accent = QColor("#3ad6a0")
        self.muted = QColor("#7f8898")

    def set_playlist(self, playlist: Playlist | None) -> None:
        self.beginResetModel()
        self.playlist = playlist
        self.endResetModel()

    def refresh(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        return 0 if parent.isValid() or self.playlist is None else len(self.playlist.entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802,ANN201
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201,C901
        if not index.isValid() or self.playlist is None:
            return None
        entry = self.playlist.entries[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return str(index.row() + 1)
            if column == 1:
                return entry.display_title
            if column == 2:
                return entry.artist
            if column == 3:
                return entry.album
            if column == 4:
                return format_duration(entry.duration) if entry.duration else ""
        elif role == Qt.ItemDataRole.ToolTipRole:
            return entry.path if entry.exists else f"File not found:\n{entry.path}"
        elif role == Qt.ItemDataRole.TextAlignmentRole and column in (0, 4):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.ForegroundRole:
            if index.row() == self.playing_row:
                return QBrush(self.accent)
            if not entry.exists:
                return QBrush(self.muted)
        elif role == Qt.ItemDataRole.FontRole:
            font = QFont()
            if index.row() == self.playing_row:
                font.setBold(True)
            if not entry.exists:
                font.setStrikeOut(True)
            return font
        return None

    # -- drag and drop -----------------------------------------------------
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsDropEnabled
        if not index.isValid():
            return base
        return base | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    def supportedDropActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [ROW_MIME, "text/uri-list"]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:  # noqa: N802
        rows = sorted({i.row() for i in indexes})
        mime = QMimeData()
        mime.setData(ROW_MIME, json.dumps({"playlist": self.playlist.id if self.playlist else "",
                                           "rows": rows}).encode("utf-8"))
        return mime

    def canDropMimeData(self, data: QMimeData, action, row: int, column: int, parent: QModelIndex) -> bool:  # noqa: N802,ANN001
        return data.hasFormat(ROW_MIME) or data.hasUrls()

    def dropMimeData(self, data: QMimeData, action, row: int, column: int, parent: QModelIndex) -> bool:  # noqa: N802,ANN001
        if self.playlist is None:
            return False
        destination = row if row >= 0 else (parent.row() if parent.isValid() else len(self.playlist.entries))
        if data.hasFormat(ROW_MIME):
            payload = json.loads(bytes(data.data(ROW_MIME)).decode("utf-8"))
            if payload.get("playlist") != self.playlist.id:
                return False
            self.playlist.move(payload.get("rows", []), destination)
            self.controller.playlist_edited(self.playlist.id)
            return False  # we moved the rows ourselves; stop Qt from removing the originals
        if data.hasUrls():
            paths = [u.toLocalFile() for u in data.urls() if u.isLocalFile()]
            self.controller.add_paths(self.playlist.id, paths, at=destination)
            return True
        return False


class PlaylistWindow(PanelWindow):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(controller, "playlist", "Playlist Editor", parent)
        self.resize(720, 460)
        self._selected_id = controller.active_playlist.id

        # left: playlists
        self.lists = QListWidget()
        self.lists.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lists.customContextMenuRequested.connect(self._playlist_menu)
        self.lists.currentItemChanged.connect(self._on_list_selected)
        self.lists.itemDoubleClicked.connect(lambda item: controller.play_playlist(item.data(Qt.ItemDataRole.UserRole)))
        self.lists.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lists.model().rowsMoved.connect(self._on_lists_reordered)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.create_playlist)
        load_btn = QPushButton("Import…")
        load_btn.clicked.connect(self.import_playlist)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Playlists"))
        left_layout.addWidget(self.lists, 1)
        row = QHBoxLayout()
        row.addWidget(new_btn)
        row.addWidget(load_btn)
        left_layout.addLayout(row)

        # right: tracks
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search in playlist  (e.g. artist:name, album:\"title\")")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.model = PlaylistModel(controller, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setDragDropOverwriteMode(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(2, 150)
        header.resizeSection(3, 150)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._sort_by_column)
        self._sort_reverse: dict[str, bool] = {}
        self.table.doubleClicked.connect(self._play_row)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._song_menu)

        buttons = QHBoxLayout()
        for label, slot in (("Add Files…", self.add_files), ("Add Folder…", self.add_folder),
                            ("Remove", self.remove_selected), ("▲", self.move_up), ("▼", self.move_down)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        sort_btn = QPushButton("Sort")
        sort_menu = QMenu(sort_btn)
        for label, key in (("By title", "title"), ("By artist", "artist"), ("By album", "album"),
                           ("By duration", "duration"), ("By file path", "path")):
            sort_menu.addAction(label).triggered.connect(lambda _c=False, k=key: self.sort_by(k))
        sort_menu.addSeparator()
        sort_menu.addAction("Shuffle order").triggered.connect(self.shuffle_order)
        sort_btn.setMenu(sort_menu)
        buttons.addWidget(sort_btn)
        more_btn = QPushButton("More")
        more_menu = QMenu(more_btn)
        more_menu.addAction("Remove missing files").triggered.connect(self.remove_missing)
        more_menu.addAction("Find moved files…").triggered.connect(self.find_moved)
        more_menu.addSeparator()
        more_menu.addAction("Export playlist…").triggered.connect(self.export_playlist)
        more_menu.addAction("Clear playlist").triggered.connect(self.clear_playlist)
        more_btn.setMenu(more_menu)
        buttons.addWidget(more_btn)
        buttons.addStretch(1)
        self.footer = QLabel("")
        self.footer.setProperty("role", "muted")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.search)
        right_layout.addWidget(self.table, 1)
        right_layout.addLayout(buttons)
        right_layout.addWidget(self.footer)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([170, 550])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)

        for sequence, slot in ((QKeySequence(QKeySequence.StandardKey.Delete), self.remove_selected),
                               (QKeySequence("Return"), lambda: self._play_row(self.table.currentIndex())),
                               (QKeySequence("Alt+Up"), self.move_up), (QKeySequence("Alt+Down"), self.move_down)):
            shortcut = QShortcut(sequence, self.table)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

        controller.playlists_changed.connect(self.reload_lists)
        controller.playlist_changed.connect(self._on_playlist_changed)
        controller.active_playlist_changed.connect(self._on_active_changed)
        controller.current_index_changed.connect(self._on_current_index)
        self.reload_lists()

    def apply_theme(self, theme) -> None:  # noqa: ANN001
        self.model.accent = QColor(theme.color("accent"))
        self.model.muted = QColor(theme.color("muted"))
        self.model.refresh()

    # -- playlists list ----------------------------------------------------
    def selected_playlist(self) -> Playlist:
        return self.controller.playlists.get(self._selected_id) or self.controller.active_playlist

    def reload_lists(self) -> None:
        self.lists.blockSignals(True)
        self.lists.clear()
        active = self.controller.active_playlist.id
        if self.controller.playlists.get(self._selected_id) is None:
            self._selected_id = active
        for playlist in self.controller.playlists.all():
            item = QListWidgetItem(("▶ " if playlist.id == active else "") + playlist.name)
            item.setData(Qt.ItemDataRole.UserRole, playlist.id)
            item.setToolTip(f"{len(playlist)} tracks · {format_duration(playlist.total_duration)}")
            self.lists.addItem(item)
            if playlist.id == self._selected_id:
                self.lists.setCurrentItem(item)
        self.lists.blockSignals(False)
        self._show_selected()

    def _on_lists_reordered(self, *_args) -> None:  # noqa: ANN002
        ids = [self.lists.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lists.count())]
        self.controller.playlists.reorder(ids)

    def _on_list_selected(self, current: QListWidgetItem | None, _previous=None) -> None:  # noqa: ANN001
        if current is not None:
            self._selected_id = current.data(Qt.ItemDataRole.UserRole)
            self._show_selected()

    def _show_selected(self) -> None:
        playlist = self.selected_playlist()
        self.model.set_playlist(playlist)
        self._update_playing_row()
        self._apply_filter(self.search.text())
        self._update_footer()

    def _on_playlist_changed(self, playlist_id: str) -> None:
        if playlist_id == self._selected_id:
            selection = [i.row() for i in self.table.selectionModel().selectedRows()]
            self.model.refresh()
            self._update_playing_row()
            self._apply_filter(self.search.text())
            self._update_footer()
            for row in selection:
                if row < self.model.rowCount():
                    self.table.selectRow(row)
        for i in range(self.lists.count()):
            item = self.lists.item(i)
            playlist = self.controller.playlists.get(item.data(Qt.ItemDataRole.UserRole))
            if playlist is not None:
                item.setToolTip(f"{len(playlist)} tracks · {format_duration(playlist.total_duration)}")

    def _on_active_changed(self, _playlist_id: str) -> None:
        self.reload_lists()

    def _on_current_index(self, playlist_id: str, index: int) -> None:
        if playlist_id == self._selected_id:
            self._update_playing_row()
            if index >= 0:
                self.table.scrollTo(self.model.index(index, 0), QAbstractItemView.ScrollHint.EnsureVisible)

    def _update_playing_row(self) -> None:
        c = self.controller
        self.model.playing_row = c.current_index if self._selected_id == c.active_playlist.id else -1
        self.model.dataChanged.emit(self.model.index(0, 0),
                                    self.model.index(max(0, self.model.rowCount() - 1), len(COLUMNS) - 1))

    def _update_footer(self) -> None:
        playlist = self.selected_playlist()
        missing = len(playlist.missing())
        text = f"{len(playlist)} tracks · {format_duration(playlist.total_duration)}"
        if missing:
            text += f" · {missing} missing"
        self.footer.setText(text)

    def _apply_filter(self, text: str) -> None:
        playlist = self.selected_playlist()
        visible = set(playlist.search(text))
        for row in range(self.model.rowCount()):
            self.table.setRowHidden(row, row not in visible)
        # Reordering a filtered view would be confusing; allow it only unfiltered.
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop if not text.strip()
                                   else QAbstractItemView.DragDropMode.DropOnly)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # -- playlist commands -------------------------------------------------
    def create_playlist(self) -> None:
        name, ok = QInputDialog.getText(self, "New playlist", "Playlist name:",
                                        text=self.controller.playlists.unique_name("New playlist"))
        if ok and name.strip():
            playlist = self.controller.new_playlist(name.strip())
            self._selected_id = playlist.id
            self.reload_lists()

    def rename_playlist(self, playlist_id: str | None = None) -> None:
        playlist = self.controller.playlists.get(playlist_id or self._selected_id)
        if playlist is None:
            return
        name, ok = QInputDialog.getText(self, "Rename playlist", "New name:", text=playlist.name)
        if ok:
            self.controller.rename_playlist(playlist.id, name)

    def delete_playlist(self, playlist_id: str | None = None) -> None:
        playlist = self.controller.playlists.get(playlist_id or self._selected_id)
        if playlist is None:
            return
        if self.controller.config.get("general.confirm_delete_playlist", True):
            answer = QMessageBox.question(self, "Delete playlist",
                                          f"Delete the playlist '{playlist.name}'?\n\nYour music files are not affected.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.controller.delete_playlist(playlist.id)

    def import_playlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import playlist", "",
                                              "Playlists (*.m3u *.m3u8 *.json);;All files (*)")
        if path:
            self.controller.open_paths([path], play=False)

    def export_playlist(self, playlist_id: str | None = None) -> None:
        playlist = self.controller.playlists.get(playlist_id or self._selected_id)
        if playlist is None:
            return
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export playlist", f"{playlist.name}.m3u8",
            "M3U8 playlist (*.m3u8);;M3U playlist (*.m3u);;PulseDeck playlist (*.json)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += {"M3U playlist (*.m3u)": ".m3u", "PulseDeck playlist (*.json)": ".json"}.get(chosen, ".m3u8")
        try:
            self.controller.playlists.export(playlist.id, path)
            self.controller.message.emit(f"Exported '{playlist.name}'")
        except (PlaylistError, OSError) as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def clear_playlist(self, playlist_id: str | None = None) -> None:
        playlist = self.controller.playlists.get(playlist_id or self._selected_id)
        if playlist is None or not playlist.entries:
            return
        answer = QMessageBox.question(self, "Clear playlist", f"Remove all tracks from '{playlist.name}'?")
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.clear_playlist(playlist.id)

    def _playlist_menu(self, pos) -> None:  # noqa: ANN001
        item = self.lists.itemAt(pos)
        if item is None:
            return
        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        c = self.controller

        def handler(action: str, _value: str | None) -> None:
            {
                "play_playlist": lambda: c.play_playlist(playlist_id),
                "shuffle_playlist": lambda: c.play_playlist(playlist_id, shuffle=True),
                "rename_playlist": lambda: self.rename_playlist(playlist_id),
                "duplicate_playlist": lambda: c.duplicate_playlist(playlist_id),
                "export_playlist": lambda: self.export_playlist(playlist_id),
                "clear_playlist": lambda: self.clear_playlist(playlist_id),
                "delete_playlist": lambda: self.delete_playlist(playlist_id),
            }[action]()

        playlist = c.playlists.get(playlist_id)
        ctx = MenuContext()
        if playlist is not None and not playlist.entries:
            ctx.disabled.update({"play_playlist", "shuffle_playlist", "clear_playlist"})
        build_menu(playlist_menu_items(), ctx, handler, self).exec(self.lists.mapToGlobal(pos))

    # -- track commands ----------------------------------------------------
    def _selected_rows(self) -> list[int]:
        return sorted(i.row() for i in self.table.selectionModel().selectedRows() if not self.table.isRowHidden(i.row()))

    def _play_row(self, index: QModelIndex | QPersistentModelIndex) -> None:
        if not index.isValid():
            return
        c = self.controller
        c.set_active_playlist(self._selected_id)
        c.play_index(index.row())

    def _song_menu(self, pos) -> None:  # noqa: ANN001
        index = self.table.indexAt(pos)
        rows = self._selected_rows()
        if index.isValid() and index.row() not in rows:
            self.table.selectRow(index.row())
            rows = [index.row()]
        if not rows:
            return
        playlist = self.selected_playlist()
        paths = [playlist.entries[r].path for r in rows]
        in_library = any(self.controller.db.get_track(p) is not None for p in paths)
        exec_song_menu(self, self.controller, paths, self.table.viewport().mapToGlobal(pos),
                       playlist_id=playlist.id, indices=rows, in_library=in_library,
                       play_handler=lambda: self._play_row(self.model.index(rows[0], 0)))

    def add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", "", f"Audio files ({exts});;All files (*)")
        if files:
            self.controller.add_paths(self._selected_id, files)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if folder:
            self.controller.add_paths(self._selected_id, [folder])

    def remove_selected(self) -> None:
        rows = self._selected_rows()
        if rows:
            self.controller.remove_entries(self._selected_id, rows)

    def _move(self, up: bool) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        playlist = self.selected_playlist()
        new_rows = playlist.move_up(rows) if up else playlist.move_down(rows)
        self.controller.playlist_edited(playlist.id)
        self.table.clearSelection()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in new_rows:
            self.table.selectionModel().select(self.model.index(row, 0), flags)

    def move_up(self) -> None:
        self._move(True)

    def move_down(self) -> None:
        self._move(False)

    def sort_by(self, key: str) -> None:
        playlist = self.selected_playlist()
        reverse = self._sort_reverse.get(key, False)
        playlist.sort(key, reverse=reverse)
        self._sort_reverse[key] = not reverse
        self.controller.playlist_edited(playlist.id)

    def _sort_by_column(self, column: int) -> None:
        key = COLUMNS[column][1]
        if key:
            self.sort_by(key)

    def shuffle_order(self) -> None:
        playlist = self.selected_playlist()
        playlist.shuffle_entries()
        self.controller.playlist_edited(playlist.id)

    def remove_missing(self) -> None:
        playlist = self.selected_playlist()
        missing = playlist.missing()
        if not missing:
            self.controller.message.emit("No missing files")
            return
        self.controller.remove_entries(playlist.id, missing)
        self.controller.message.emit(f"Removed {len(missing)} missing file(s)")

    def find_moved(self) -> None:
        playlist = self.selected_playlist()
        if not playlist.missing():
            self.controller.message.emit("No missing files")
            return
        roots = list(self.controller.db.folders())
        folder = QFileDialog.getExistingDirectory(self, "Search this folder for moved files")
        if folder:
            roots.insert(0, folder)
        if not roots:
            return
        fixed = relink_missing(playlist, roots)
        self.controller.playlist_edited(playlist.id)
        remaining = len(playlist.missing())
        QMessageBox.information(self, "Find moved files",
                                f"Relinked {fixed} file(s). {remaining} still missing.")
