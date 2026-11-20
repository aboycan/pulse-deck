# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Settings panel. Every change is applied immediately and saved."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pulsedeck.audio.audio_devices import list_devices
from pulsedeck.core import platform
from pulsedeck.ui import shortcuts
from pulsedeck.ui.panels import PanelWindow
from pulsedeck.ui.theme import available_themes, user_theme_dir

LIBRARY_COLUMN_CHOICES = (("genre", "Genre"), ("year", "Year"), ("bitrate", "Bitrate"),
                          ("sample_rate", "Sample rate"), ("file_size", "Size"), ("play_count", "Plays"))


class SettingsWindow(PanelWindow):
    def __init__(self, controller, apply_theme, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(controller, "settings", "Settings", parent)
        self.apply_theme = apply_theme
        self.resize(560, 520)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._audio_tab(), "Audio")
        tabs.addTab(self._library_tab(), "Library")
        tabs.addTab(self._interface_tab(), "Interface")
        tabs.addTab(self._keyboard_tab(), "Keyboard")
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(tabs)
        layout.addLayout(bottom)

    def keyPressEvent(self, event) -> None:  # noqa: N802,ANN001
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    # -- helpers -------------------------------------------------------
    def _check(self, label: str, key: str, tooltip: str = "") -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(bool(self.controller.config.get(key)))
        box.setToolTip(tooltip)
        box.toggled.connect(lambda v: self.controller.set_setting(key, bool(v)))
        return box

    def _combo(self, key: str, choices: list[tuple[str, str]]) -> QComboBox:
        combo = QComboBox()
        for value, label in choices:
            combo.addItem(label, value)
        index = combo.findData(self.controller.config.get(key))
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _i: self.controller.set_setting(key, combo.currentData()))
        return combo

    # -- tabs ------------------------------------------------------------
    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("On startup", self._combo("general.startup", [
            ("restore", "Restore my last session"), ("empty", "Start with an empty player")]))
        form.addRow(self._check("Restore previous session (playlist, track and position)", "general.restore_session"))
        form.addRow(self._check("Minimize to system tray", "general.minimize_to_tray"))
        form.addRow(self._check("Closing the main window keeps PulseDeck running in the tray",
                                "general.close_to_tray"))
        form.addRow(self._check("Show a notification when the track changes", "general.notifications"))
        form.addRow(self._check("Ask before deleting playlists", "general.confirm_delete_playlist"))
        form.addRow(self._check("Open files in the running PulseDeck instead of a new window",
                                "general.single_instance"))
        clear = QPushButton("Clear Playback History…")
        clear.clicked.connect(self._clear_history)
        form.addRow(clear)
        return page

    def _audio_tab(self) -> QWidget:
        c = self.controller
        page = QWidget()
        form = QFormLayout(page)
        self.device = QComboBox()
        for device in list_devices(c.engine):
            self.device.addItem(device.description, device.name)
        self.device.setCurrentIndex(max(0, self.device.findData(c.config.get("audio.output_device"))))
        self.device.currentIndexChanged.connect(
            lambda _i: c.set_setting("audio.output_device", self.device.currentData()))
        form.addRow("Output device", self.device)

        eq_enabled = QCheckBox("Equalizer enabled")
        eq_enabled.setChecked(c.eq.enabled)

        def toggle_eq(on: bool) -> None:
            c.eq.enabled = bool(on)
            c.apply_equalizer()

        eq_enabled.toggled.connect(toggle_eq)
        c.equalizer_changed.connect(lambda: (eq_enabled.blockSignals(True), eq_enabled.setChecked(c.eq.enabled),
                                             eq_enabled.blockSignals(False)))
        form.addRow(eq_enabled)
        form.addRow("Default EQ preset", self._combo("equalizer.default_preset",
                                                      [(n, n) for n in c.presets.names()]))

        crossfade = QDoubleSpinBox()
        crossfade.setRange(0.0, 12.0)
        crossfade.setSingleStep(0.5)
        crossfade.setSuffix(" s")
        crossfade.setSpecialValueText("Off (gapless)")
        crossfade.setValue(float(c.config.get("audio.crossfade_seconds", 0.0)))
        crossfade.valueChanged.connect(lambda v: c.set_setting("audio.crossfade_seconds", float(v)))
        form.addRow("Crossfade", crossfade)
        form.addRow(self._check("Gapless playback", "audio.gapless",
                                "Play consecutive tracks without a gap (when crossfade is off)"))
        form.addRow(self._check("Volume normalization", "audio.normalization",
                                "Even out loudness differences between and within tracks"))
        form.addRow("ReplayGain", self._combo("audio.replaygain", [
            ("off", "Off"), ("track", "Track gain"), ("album", "Album gain")]))
        rg_pre = QDoubleSpinBox()
        rg_pre.setRange(-15.0, 15.0)
        rg_pre.setSuffix(" dB")
        rg_pre.setValue(float(c.config.get("audio.replaygain_preamp", 0.0)))
        rg_pre.valueChanged.connect(lambda v: c.set_setting("audio.replaygain_preamp", float(v)))
        form.addRow("ReplayGain preamp", rg_pre)
        form.addRow(self._check("Clip protection (limiter after EQ)", "audio.clip_protection"))

        speed = QDoubleSpinBox()
        speed.setRange(0.25, 4.0)
        speed.setSingleStep(0.05)
        speed.setSuffix("×")
        speed.setValue(float(c.config.get("audio.speed", 1.0)))
        speed.valueChanged.connect(lambda v: c.set_setting("audio.speed", round(float(v), 2)))
        form.addRow("Playback speed", speed)

        balance_row = QHBoxLayout()
        balance = QSlider(Qt.Orientation.Horizontal)
        balance.setRange(-100, 100)
        balance.setValue(int(float(c.config.get("audio.balance", 0.0)) * 100))
        balance_label = QLabel()

        def on_balance(v: int) -> None:
            balance_label.setText("Centre" if v == 0 else f"{abs(v)}% {'L' if v < 0 else 'R'}")
            c.set_setting("audio.balance", v / 100)

        balance.valueChanged.connect(on_balance)
        on_balance(balance.value())
        centre = QPushButton("Centre")
        centre.clicked.connect(lambda: balance.setValue(0))
        balance_row.addWidget(QLabel("L"))
        balance_row.addWidget(balance, 1)
        balance_row.addWidget(QLabel("R"))
        balance_row.addWidget(balance_label)
        balance_row.addWidget(centre)
        form.addRow("Balance", balance_row)

        seek = QSpinBox()
        seek.setRange(1, 60)
        seek.setSuffix(" s")
        seek.setValue(int(c.config.get("audio.seek_step_seconds", 5)))
        seek.valueChanged.connect(lambda v: c.set_setting("audio.seek_step_seconds", int(v)))
        form.addRow("Fast forward / rewind step", seek)
        if c.audio_error:
            warning = QLabel(c.audio_error)
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #e5534b;")
            form.addRow(warning)
        return page

    def _library_tab(self) -> QWidget:
        c = self.controller
        page = QWidget()
        form = QFormLayout(page)
        folder_row = QHBoxLayout()
        folder = QLineEdit(c.config.get("library.default_music_dir") or "")
        folder.setPlaceholderText("Your Music folder")
        folder.editingFinished.connect(lambda: c.set_setting("library.default_music_dir", folder.text().strip()))
        browse = QPushButton("Browse…")

        def pick() -> None:
            chosen = QFileDialog.getExistingDirectory(self, "Default music folder", folder.text())
            if chosen:
                folder.setText(chosen)
                c.set_setting("library.default_music_dir", chosen)

        browse.clicked.connect(pick)
        folder_row.addWidget(folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Default music folder", folder_row)
        form.addRow(self._check("Rescan library folders automatically at startup", "library.auto_scan"))
        form.addRow("Duplicate detection", self._combo("library.duplicate_detection", [
            ("path", "Same file path only"), ("path+metadata", "Same path, or same title/artist/album/length")]))
        form.addRow(QLabel("Library columns to show:"))
        columns = set(c.config.get("library.columns") or [])
        for key, label in LIBRARY_COLUMN_CHOICES:
            box = QCheckBox(label)
            box.setChecked(key in columns)
            box.toggled.connect(lambda on, k=key: self._toggle_column(k, on))
            form.addRow(box)
        form.addRow(self._check("Show bitrate and sample rate in the player", "library.show_bitrate"))
        return page

    def _toggle_column(self, key: str, on: bool) -> None:
        columns = list(self.controller.config.get("library.columns") or [])
        if on and key not in columns:
            columns.append(key)
        elif not on and key in columns:
            columns.remove(key)
        self.controller.set_setting("library.columns", columns)

    def _interface_tab(self) -> QWidget:
        c = self.controller
        page = QWidget()
        form = QFormLayout(page)
        self.theme_combo = QComboBox()
        for theme in available_themes().values():
            self.theme_combo.addItem(theme.name, theme.id)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(c.config.get("interface.theme"))))
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        theme_row = QHBoxLayout()
        theme_row.addWidget(self.theme_combo, 1)
        open_dir = QPushButton("Theme Folder…")
        open_dir.setToolTip("Put your own theme .json files here (see docs/THEMES.md)")
        open_dir.clicked.connect(lambda: platform.open_folder(user_theme_dir()))
        theme_row.addWidget(open_dir)
        form.addRow("Theme", theme_row)

        accent_row = QHBoxLayout()
        self.accent_btn = QPushButton("Choose…")
        self.accent_btn.clicked.connect(self._pick_accent)
        reset_accent = QPushButton("Use theme colour")
        reset_accent.clicked.connect(lambda: self._set_accent(""))
        accent_row.addWidget(self.accent_btn)
        accent_row.addWidget(reset_accent)
        accent_row.addStretch(1)
        form.addRow("Accent colour", accent_row)
        self._update_accent_button()

        font = QSpinBox()
        font.setRange(8, 18)
        font.setSuffix(" pt")
        font.setValue(int(c.config.get("interface.font_size", 10)))
        font.valueChanged.connect(lambda v: (c.set_setting("interface.font_size", int(v)), self.apply_theme()))
        form.addRow("Font size", font)
        form.addRow(self._check("Compact player", "interface.compact_mode"))
        form.addRow(self._check("Keep the player always on top", "interface.always_on_top"))
        form.addRow(QLabel("Panels to show at startup:"))
        panels = c.config.get("interface.panels", {}) or {}
        for key, label in (("playlist", "Playlist editor"), ("equalizer", "Equalizer"), ("library", "Music library"),
                           ("info", "Audio information")):
            box = QCheckBox(label)
            box.setChecked(bool(panels.get(key)))
            box.toggled.connect(lambda on, k=key: self._set_panel(k, on))
            form.addRow(box)
        return page

    def _set_panel(self, key: str, on: bool) -> None:
        panels = dict(self.controller.config.get("interface.panels", {}) or {})
        panels[key] = bool(on)
        self.controller.set_setting("interface.panels", panels)

    def _theme_changed(self, _index: int) -> None:
        self.controller.set_setting("interface.theme", self.theme_combo.currentData())
        self.apply_theme()

    def _pick_accent(self) -> None:
        current = self.controller.config.get("interface.accent_color") or "#3ad6a0"
        color = QColorDialog.getColor(QColor(current), self, "Accent colour")
        if color.isValid():
            self._set_accent(color.name())

    def _set_accent(self, value: str) -> None:
        self.controller.set_setting("interface.accent_color", value)
        self._update_accent_button()
        self.apply_theme()

    def _update_accent_button(self) -> None:
        value = self.controller.config.get("interface.accent_color") or ""
        self.accent_btn.setText(value or "Theme default")

    def _keyboard_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.shortcut_table = QTableWidget(len(shortcuts.ACTIONS), 2)
        self.shortcut_table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.shortcut_table.verticalHeader().hide()
        self.shortcut_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.shortcut_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.key_edits: dict[str, QKeySequenceEdit] = {}
        mapping = shortcuts.effective(self.controller.config.get("shortcuts", {}))
        for row, action in enumerate(shortcuts.ACTIONS):
            label = QLabel(action.label)
            edit = QKeySequenceEdit(QKeySequence(mapping[action.id]))
            edit.editingFinished.connect(self._shortcuts_edited)
            self.key_edits[action.id] = edit
            self.shortcut_table.setCellWidget(row, 0, label)
            self.shortcut_table.setCellWidget(row, 1, edit)
        self.conflict_label = QLabel("")
        self.conflict_label.setWordWrap(True)
        reset = QPushButton("Restore Defaults")
        reset.clicked.connect(self._reset_shortcuts)
        note = QLabel("Media keys (Play/Pause, Next, Previous, Stop) work system-wide where the "
                      "operating system allows it. Escape closes the active dialog.")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(self.shortcut_table, 1)
        layout.addWidget(self.conflict_label)
        row = QHBoxLayout()
        row.addWidget(reset)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(note)
        return page

    def _shortcuts_edited(self) -> None:
        mapping = {k: e.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                   for k, e in self.key_edits.items()}
        clashes = shortcuts.conflicts(mapping)
        if clashes:
            labels = {a.id: a.label for a in shortcuts.ACTIONS}
            text = "; ".join(f"{seq}: {', '.join(labels[i] for i in ids)}" for seq, ids in clashes.items())
            self.conflict_label.setText(f"Conflicting shortcuts - {text}")
        else:
            self.conflict_label.setText("")
        defaults = shortcuts.defaults()
        overrides = {k: v for k, v in mapping.items() if v != defaults[k]}
        self.controller.set_setting("shortcuts", overrides)

    def _reset_shortcuts(self) -> None:
        for key, value in shortcuts.defaults().items():
            self.key_edits[key].setKeySequence(QKeySequence(value))
        self.conflict_label.setText("")
        self.controller.set_setting("shortcuts", {})

    def _clear_history(self) -> None:
        answer = QMessageBox.question(self, "Clear history",
                                      "Clear the recently played and most played lists?")
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.clear_history()
            self.controller.message.emit("Playback history cleared")
