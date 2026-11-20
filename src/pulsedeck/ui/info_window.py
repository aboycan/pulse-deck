# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Audio information panel with a safe metadata editor."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pulsedeck.library import metadata as md
from pulsedeck.library.models import TrackInfo, format_duration, format_size
from pulsedeck.ui.panels import PanelWindow
from pulsedeck.ui.widgets import ArtworkDialog, ClickableLabel

FIELD_LABELS = {
    "title": "Title", "artist": "Artist", "album_artist": "Album artist", "album": "Album", "genre": "Genre",
    "year": "Year", "track_number": "Track number", "disc_number": "Disc number", "composer": "Composer",
    "copyright": "Copyright",
}


class InfoWindow(PanelWindow):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(controller, "info", "Audio Information", parent)
        self.resize(560, 560)
        self.info: TrackInfo | None = None
        self.follow = QCheckBox("Follow the playing track")
        self.follow.setChecked(True)
        self.follow.toggled.connect(lambda on: on and self.show_track(controller.current_track))

        self.art = ClickableLabel()
        self.art.setFixedSize(150, 150)
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art.setCursor(Qt.CursorShape.PointingHandCursor)
        self.art.setToolTip("Click to view full size")
        self.art.clicked.connect(self._view_art)

        self.edits: dict[str, QLineEdit] = {}
        tags_box = QGroupBox("Tags")
        tags_form = QFormLayout(tags_box)
        for key, label in FIELD_LABELS.items():
            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.textEdited.connect(self._on_edited)
            self.edits[key] = edit
            tags_form.addRow(label, edit)

        self.stream_labels: dict[str, QLabel] = {}
        stream_box = QGroupBox("File")
        stream_form = QFormLayout(stream_box)
        for key, label in (("duration", "Duration"), ("bitrate", "Bitrate"), ("sample_rate", "Sample rate"),
                           ("channels", "Channels"), ("codec", "Format"), ("file_size", "File size"),
                           ("artwork", "Embedded artwork"), ("replaygain", "ReplayGain"), ("path", "Location")):
            value = QLabel("")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            self.stream_labels[key] = value
            stream_form.addRow(label, value)

        self.edit_btn = QPushButton("Edit Tags")
        self.edit_btn.setCheckable(True)
        self.edit_btn.toggled.connect(self.set_editing)
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("accent", True)
        self.save_btn.clicked.connect(self.save)
        self.revert_btn = QPushButton("Revert")
        self.revert_btn.clicked.connect(lambda: self.show_track(self.info))
        self.restore_btn = QPushButton("Restore Original Tags…")
        self.restore_btn.clicked.connect(self.restore_original)
        self.note = QLabel("Only tags are changed; the audio data is never modified. "
                           "The original tags are kept so they can be restored.")
        self.note.setWordWrap(True)
        self.note.setProperty("role", "muted")

        header = QHBoxLayout()
        header.addWidget(self.art)
        header_right = QVBoxLayout()
        self.heading = QLabel("")
        self.heading.setObjectName("TitleLabel")
        self.heading.setWordWrap(True)
        header_right.addWidget(self.heading)
        header_right.addWidget(self.follow)
        header_right.addStretch(1)
        header.addLayout(header_right, 1)
        buttons = QHBoxLayout()
        for button in (self.edit_btn, self.save_btn, self.revert_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.restore_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(header)
        layout.addWidget(tags_box)
        layout.addWidget(stream_box)
        layout.addLayout(buttons)
        layout.addWidget(self.note)
        layout.addStretch(1)

        controller.track_changed.connect(self._on_track_changed)
        controller.show_info_requested.connect(self.open_for)
        self.set_editing(False)
        self.show_track(controller.current_track)

    def _on_track_changed(self, info: TrackInfo | None) -> None:
        if self.follow.isChecked() and not self.edit_btn.isChecked():
            self.show_track(info)

    def open_for(self, path: str, edit: bool) -> None:
        self.follow.setChecked(False)
        self.show_track(self.controller.track_info(path, refresh=True))
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit_btn.setChecked(edit)

    def show_track(self, info: TrackInfo | None) -> None:
        self.info = info
        self._dirty = False
        self.save_btn.setEnabled(False)
        if info is None:
            self.heading.setText("Nothing playing")
            for edit in self.edits.values():
                edit.clear()
            for label in self.stream_labels.values():
                label.clear()
            self.art.clear()
            self.edit_btn.setEnabled(False)
            self.restore_btn.setEnabled(False)
            return
        self.heading.setText(f"{info.display_title}\n{info.display_artist}")
        for key, edit in self.edits.items():
            edit.setText(str(getattr(info, key) or ""))
        s = self.stream_labels
        s["duration"].setText(format_duration(info.duration) if info.duration else "Unknown")
        s["bitrate"].setText(f"{round(info.bitrate / 1000)} kbps" if info.bitrate else "Unknown")
        s["sample_rate"].setText(f"{info.sample_rate:,} Hz" if info.sample_rate else "Unknown")
        s["channels"].setText({1: "1 (mono)", 2: "2 (stereo)"}.get(info.channels, str(info.channels or "Unknown")))
        s["codec"].setText((info.codec or os.path.splitext(info.path)[1].lstrip(".")).upper())
        s["file_size"].setText(f"{format_size(info.file_size)} ({info.file_size:,} bytes)" if info.file_size else "")
        s["artwork"].setText("Yes" if info.has_artwork else "No")
        rg = []
        if info.replaygain_track_gain is not None:
            rg.append(f"track {info.replaygain_track_gain:+.2f} dB")
        if info.replaygain_album_gain is not None:
            rg.append(f"album {info.replaygain_album_gain:+.2f} dB")
        s["replaygain"].setText(", ".join(rg) or "None")
        s["path"].setText(info.path)
        thumb = self.controller.artwork.thumbnail(info.path, 300)
        if thumb:
            self.art.setPixmap(QPixmap(str(thumb)).scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
        else:
            self.art.setText("No artwork")
        exists = os.path.isfile(info.path)
        self.edit_btn.setEnabled(exists and md.MUTAGEN_AVAILABLE)
        self.restore_btn.setEnabled(exists and md.backup_path_for(info.path).exists())

    def set_editing(self, editing: bool) -> None:
        for edit in self.edits.values():
            edit.setReadOnly(not editing)
        self.revert_btn.setEnabled(editing)
        self.save_btn.setVisible(editing)
        self.revert_btn.setVisible(editing)
        if not editing and getattr(self, "_dirty", False):
            self.show_track(self.info)

    def _on_edited(self, _text: str) -> None:
        self._dirty = True
        self.save_btn.setEnabled(True)

    def save(self) -> None:
        if self.info is None:
            return
        changes = {}
        for key, edit in self.edits.items():
            value = edit.text().strip()
            if value != str(getattr(self.info, key) or ""):
                changes[key] = value
        if not changes:
            self.edit_btn.setChecked(False)
            return
        try:
            updated = self.controller.save_metadata(self.info.path, changes)
        except md.MetadataError as exc:
            QMessageBox.warning(self, "Could not save tags", f"{exc}\n\nThe file was not changed.")
            return
        self._dirty = False
        self.edit_btn.setChecked(False)
        self.show_track(updated)
        self.controller.message.emit("Tags saved")

    def restore_original(self) -> None:
        if self.info is None:
            return
        answer = QMessageBox.question(self, "Restore tags",
                                      "Restore the tags this file had before you first edited it in PulseDeck?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = md.restore_original_metadata(self.info.path)
            self.controller.refresh_file(self.info.path, restored)
        except md.MetadataError as exc:
            QMessageBox.warning(self, "Restore tags", str(exc))
            return
        self.show_track(restored)

    def _view_art(self) -> None:
        if self.info is None:
            return
        data = self.controller.artwork.load_original(self.info.path)
        if data:
            ArtworkDialog(data, f"{self.info.display_title} - artwork", self).exec()
