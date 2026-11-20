# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Music library panel: folders, browsing, search, favourites and history."""

from __future__ import annotations

import os

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QSortFilterProxyModel, Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pulsedeck.library.models import TrackInfo, format_duration, format_size
from pulsedeck.library.search import search_library
from pulsedeck.ui.context_menus import MenuContext, build_menu, group_menu_items
from pulsedeck.ui.panels import PanelWindow
from pulsedeck.ui.song_actions import exec_song_menu, handle_song_action, playlist_choices

COLUMNS = (
    ("♥", "favourite"), ("Title", "title"), ("Artist", "artist"), ("Album", "album"), ("Time", "duration"),
    ("Genre", "genre"), ("Year", "year"), ("Bitrate", "bitrate"), ("Sample rate", "sample_rate"),
    ("Size", "file_size"), ("Plays", "play_count"),
)
SORT_ROLE = int(Qt.ItemDataRole.UserRole.value) + 1
KEY_ROLE = Qt.ItemDataRole.UserRole


def _key(kind: str, value: str) -> str:
    """Tree items store plain strings (Qt would turn tuples into lists)."""
    return f"{kind}\x1f{value}"


def _parse(key: str | None) -> tuple[str, str] | None:
    if not key:
        return None
    kind, _, value = str(key).partition("\x1f")
    return kind, value
VIEW_ALL, VIEW_FAV, VIEW_RECENT, VIEW_MOST, VIEW_ADDED = "all", "favourites", "recent", "most", "added"


class LibraryModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.tracks: list[TrackInfo] = []

    def set_tracks(self, tracks: list[TrackInfo]) -> None:
        self.beginResetModel()
        self.tracks = tracks
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        return 0 if parent.isValid() else len(self.tracks)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802,ANN201
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][0]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return ["text/uri-list"]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:  # noqa: N802
        rows = sorted({i.row() for i in indexes})
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.tracks[r].path) for r in rows])
        return mime

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid():
            return None
        track = self.tracks[index.row()]
        key = COLUMNS[index.column()][1]
        if role == SORT_ROLE:
            value = getattr(track, key) if key != "title" else track.display_title
            return value.casefold() if isinstance(value, str) else (value or 0)
        if role == Qt.ItemDataRole.DisplayRole:
            if key == "favourite":
                return "♥" if track.favourite else ""
            if key == "title":
                return track.display_title
            if key == "duration":
                return format_duration(track.duration) if track.duration else ""
            if key == "bitrate":
                return f"{round(track.bitrate / 1000)} kbps" if track.bitrate else ""
            if key == "sample_rate":
                return f"{track.sample_rate / 1000:g} kHz" if track.sample_rate else ""
            if key == "file_size":
                return format_size(track.file_size) if track.file_size else ""
            if key == "play_count":
                return str(track.play_count) if track.play_count else ""
            return str(getattr(track, key) or "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return track.path
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("duration", "bitrate", "sample_rate", "file_size",
                                                                  "play_count", "year"):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None


class LibraryWindow(PanelWindow):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(controller, "library", "Music Library", parent)
        self.resize(980, 560)
        self.view = VIEW_ALL
        self.filters: dict[str, str] = {}

        # browse tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._on_tree_selected)

        # search
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search library  (words, or artist: album: genre: year:)")
        self.search.setClearButtonEnabled(True)
        self.scope = QComboBox()
        for label, value in (("All fields", "all"), ("Title", "title"), ("Artist", "artist"),
                             ("Album", "album"), ("Genre", "genre")):
            self.scope.addItem(label, value)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_tracks)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.scope.currentIndexChanged.connect(lambda _i: self.refresh_tracks())

        # tracks table
        self.model = LibraryModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 28)
        for col, width in ((2, 160), (3, 160), (4, 60), (5, 100), (6, 50), (7, 80), (8, 80), (9, 70), (10, 50)):
            header.resizeSection(col, width)
        self.table.doubleClicked.connect(self._play_index)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._song_menu)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_preview())

        # artwork preview
        self.preview = QLabel()
        self.preview.setFixedSize(160, 160)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_text = QLabel("")
        self.preview_text.setWordWrap(True)
        self.preview_text.setProperty("role", "muted")
        self.preview_text.setFixedWidth(160)
        preview_box = QVBoxLayout()
        preview_box.addWidget(self.preview)
        preview_box.addWidget(self.preview_text)
        preview_box.addStretch(1)

        # folder controls
        add_folder = QPushButton("Add Folder…")
        add_folder.clicked.connect(self.add_folder)
        add_files = QPushButton("Add Files…")
        add_files.clicked.connect(self.add_files)
        folders_btn = QPushButton("Folders")
        self.folders_menu = QMenu(folders_btn)
        self.folders_menu.aboutToShow.connect(self._populate_folders_menu)
        folders_btn.setMenu(self.folders_menu)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(lambda: controller.scan_library(None))
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(14)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(controller.cancel_scan)
        self.cancel_btn.hide()
        self.status = QLabel("")
        self.status.setProperty("role", "muted")

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.scope)
        bottom = QHBoxLayout()
        for widget in (add_folder, add_files, folders_btn, self.rescan_btn):
            bottom.addWidget(widget)
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.status)

        center = QWidget()
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.table, 1)
        center_layout.addLayout(preview_box)

        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(center)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 780])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)

        controller.library_changed.connect(self.reload)
        controller.settings_changed.connect(lambda key: key == "library.columns" and self._apply_columns())
        self._apply_columns()
        controller.favourites_changed.connect(self.refresh_tracks)
        controller.history_changed.connect(self._on_history)
        controller.scan_progress.connect(self._on_scan_progress)
        controller.scan_finished.connect(self._on_scan_finished)
        self._loaded = False

    def showEvent(self, event) -> None:  # noqa: N802,ANN001
        self._loaded = True
        super().showEvent(event)
        QTimer.singleShot(0, self.reload)

    def _apply_columns(self) -> None:
        optional = {"genre", "year", "bitrate", "sample_rate", "file_size", "play_count"}
        shown = set(self.controller.config.get("library.columns") or [])
        for index, (_label, key) in enumerate(COLUMNS):
            self.table.setColumnHidden(index, key in optional and key not in shown)

    # -- tree --------------------------------------------------------------
    def reload(self) -> None:
        current = self.tree.currentItem()
        selected = current.data(0, KEY_ROLE) if current else _key("view", self.view)
        self.tree.blockSignals(True)
        self.tree.clear()
        views = QTreeWidgetItem(self.tree, ["Library"])
        for label, view in (("All Music", VIEW_ALL), ("Favourites", VIEW_FAV), ("Recently Played", VIEW_RECENT),
                            ("Most Played", VIEW_MOST), ("Recently Added", VIEW_ADDED)):
            item = QTreeWidgetItem(views, [label])
            item.setData(0, KEY_ROLE, _key("view", view))
        views.setExpanded(True)
        db = self.controller.db
        for title, column in (("Artists", "artist"), ("Albums", "album"), ("Genres", "genre"), ("Years", "year")):
            node = QTreeWidgetItem(self.tree, [title])
            node.setData(0, KEY_ROLE, _key("group", column))
            for value in db.distinct_values(column):
                child = QTreeWidgetItem(node, [value])
                child.setData(0, KEY_ROLE, _key(column, value))
        self.tree.blockSignals(False)
        self._reselect(selected)
        self.refresh_tracks()

    def _reselect(self, data: str) -> None:
        iterator = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while iterator:
            item = iterator.pop(0)
            if item.data(0, KEY_ROLE) == data:
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(item)
                self.tree.blockSignals(False)
                return
            iterator.extend(item.child(i) for i in range(item.childCount()))

    def _on_tree_selected(self, item: QTreeWidgetItem | None, _prev=None) -> None:  # noqa: ANN001
        if item is None:
            return
        data = _parse(item.data(0, KEY_ROLE))
        if not data:
            return
        kind, value = data
        if kind == "view":
            self.view, self.filters = value, {}
        elif kind in ("artist", "album", "genre", "year"):
            self.view, self.filters = VIEW_ALL, {kind: value}
        else:
            return
        self.refresh_tracks()

    def _on_history(self) -> None:
        if self.view in (VIEW_RECENT, VIEW_MOST) and self.isVisible():
            self.refresh_tracks()

    # -- tracks ------------------------------------------------------------
    def refresh_tracks(self) -> None:
        if not self.isVisible() and self._loaded:
            return
        c = self.controller
        text = self.search.text().strip()
        if self.view == VIEW_ALL:
            tracks = search_library(c.db, text, self.scope.currentData() or "all", **self.filters)
        elif self.view == VIEW_FAV:
            tracks = search_library(c.db, text, self.scope.currentData() or "all", favourites_only=True)
            known = {t.path for t in tracks}
            tracks += [c.track_info(p) for p in c.db.favourites() if p not in known and os.path.exists(p)
                       and not text]
        elif self.view == VIEW_RECENT:
            tracks = [c.db.get_track(p) or c.track_info(p) for p in c.db.recently_played(200)]
        elif self.view == VIEW_MOST:
            tracks = []
            for path, count in c.db.most_played(200):
                info = c.db.get_track(path) or c.track_info(path)
                info.play_count = count
                tracks.append(info)
        else:
            tracks = c.db.recently_added(200)
        if text and self.view in (VIEW_RECENT, VIEW_MOST):
            from pulsedeck.library.search import matches  # noqa: PLC0415

            tracks = [t for t in tracks if matches(t, text)]
        self.model.set_tracks(tracks)
        total = sum(t.duration for t in tracks)
        self.status.setText(f"{len(tracks)} tracks · {format_duration(total)} · "
                            f"{c.db.track_count()} in library")
        self._update_preview()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _selected_tracks(self) -> list[TrackInfo]:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.tracks[r] for r in rows]

    def _visible_tracks(self) -> list[TrackInfo]:
        return [self.model.tracks[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                for r in range(self.proxy.rowCount())]

    def _play_index(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self._play_tracks([self.model.tracks[self.proxy.mapToSource(index).row()]])

    def _play_tracks(self, tracks: list[TrackInfo]) -> None:
        if tracks:
            self.controller.add_paths(self.controller.active_playlist.id, [t.path for t in tracks], play=True)

    def _update_preview(self) -> None:
        tracks = self._selected_tracks()
        if not tracks:
            self.preview.clear()
            self.preview_text.setText("")
            return
        track = tracks[0]
        thumb = self.controller.artwork.thumbnail(track.path, 320)
        if thumb:
            pixmap = QPixmap(str(thumb)).scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pixmap)
        else:
            self.preview.setText("No artwork")
        self.preview_text.setText(f"<b>{track.display_title}</b><br>{track.display_artist}<br>{track.album}")

    def _song_menu(self, pos) -> None:  # noqa: ANN001
        tracks = self._selected_tracks()
        exec_song_menu(self, self.controller, [t.path for t in tracks], self.table.viewport().mapToGlobal(pos),
                       in_library=True, play_handler=lambda: self._play_tracks(tracks))

    def _tree_menu(self, pos) -> None:  # noqa: ANN001
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = _parse(item.data(0, KEY_ROLE))
        if not data or data[0] not in ("artist", "album", "genre", "year"):
            return
        kind, value = data
        tracks = self.controller.db.query_tracks(**{kind: value})
        paths = [t.path for t in tracks]

        def handler(action: str, target: str | None) -> None:
            if action == "play_all":
                self._play_tracks(tracks)
            elif action == "add_group_to":
                handle_song_action(self, self.controller, action, target, paths)
            elif action == "view_albums":
                self._show_albums(kind, value, tracks)
            elif action == "view_group_info":
                self._show_group_info(kind, value, tracks)

        ctx = MenuContext(dynamic={"playlists": playlist_choices(self.controller)})
        if not tracks:
            ctx.disabled.update({"play_all", "add_group_to"})
        build_menu(group_menu_items("artist" if kind == "artist" else "album"), ctx, handler,
                   self).exec(self.tree.viewport().mapToGlobal(pos))

    def _show_albums(self, kind: str, value: str, tracks: list[TrackInfo]) -> None:
        if kind != "artist":
            self.view, self.filters = VIEW_ALL, {kind: value}
            self.refresh_tracks()
            return
        albums = self.controller.db.albums_for_artist(value)
        if not albums:
            QMessageBox.information(self, value, "No albums found for this artist.")
            return
        album, ok = QInputDialog.getItem(self, f"Albums by {value}", "Choose an album to show:", albums, 0, False)
        if ok and album:
            self.view, self.filters = VIEW_ALL, {"album": album}
            self._reselect(_key("album", album))
            self.refresh_tracks()

    def _show_group_info(self, kind: str, value: str, tracks: list[TrackInfo]) -> None:
        albums = sorted({t.album for t in tracks if t.album}, key=str.casefold)
        artists = sorted({t.display_artist for t in tracks}, key=str.casefold)
        years = sorted({t.year for t in tracks if t.year})
        genres = sorted({t.genre for t in tracks if t.genre}, key=str.casefold)
        size = sum(t.file_size for t in tracks)
        lines = [
            f"<b>{kind.title()}: {value}</b>",
            f"Tracks: {len(tracks)}",
            f"Total time: {format_duration(sum(t.duration for t in tracks))}",
            f"Total size: {format_size(size)}",
        ]
        if kind != "artist":
            lines.append(f"Artists: {', '.join(artists[:10])}{'…' if len(artists) > 10 else ''}")
        lines.append(f"Albums: {len(albums)}")
        if years:
            lines.append(f"Years: {years[0]}" + (f"–{years[-1]}" if len(years) > 1 else ""))
        if genres:
            lines.append(f"Genres: {', '.join(genres[:6])}")
        QMessageBox.information(self, "Information", "<br>".join(lines))

    # -- folders -----------------------------------------------------------
    def _populate_folders_menu(self) -> None:
        self.folders_menu.clear()
        folders = self.controller.db.folders()
        if not folders:
            self.folders_menu.addAction("(no library folders)").setEnabled(False)
        for folder in folders:
            sub = self.folders_menu.addMenu(folder)
            sub.addAction("Rescan").triggered.connect(lambda _c=False, f=folder: self.controller.scan_library([f]))
            sub.addAction("Remove from Library…").triggered.connect(lambda _c=False, f=folder: self.remove_folder(f))

    def add_folder(self) -> None:
        start = self.controller.config.get("library.default_music_dir") or ""
        folder = QFileDialog.getExistingDirectory(self, "Add music folder", start)
        if folder:
            self.controller.add_library_folder(folder)

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add files to library")
        if files:
            self.controller.add_files_to_library(files)

    def remove_folder(self, folder: str) -> None:
        answer = QMessageBox.question(
            self, "Remove folder",
            f"Remove '{folder}' and its tracks from the library?\n\nNo files will be deleted from disk.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            removed = self.controller.remove_library_folder(folder)
            self.controller.message.emit(f"Removed {removed} tracks from the library")

    def _on_scan_progress(self, index: int, total: int, path: str) -> None:
        self.progress.show()
        self.cancel_btn.show()
        self.rescan_btn.setEnabled(False)
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(index)
        self.status.setText(f"Scanning {index}/{total}: {os.path.basename(path)}")

    def _on_scan_finished(self, result) -> None:  # noqa: ANN001
        self.progress.hide()
        self.cancel_btn.hide()
        self.rescan_btn.setEnabled(True)
        self.reload()
        message = f"Scan {'cancelled' if result.cancelled else 'complete'}: {result.summary}"
        self.status.setText(message)
        if result.errors and self.isVisible():
            details = "\n".join(f"{os.path.basename(p)}: {e}" for p, e in result.errors[:15])
            more = f"\n… and {len(result.errors) - 15} more" if len(result.errors) > 15 else ""
            QMessageBox.information(self, "Library scan",
                                    f"{message}\n\nSome files could not be read:\n{details}{more}")
