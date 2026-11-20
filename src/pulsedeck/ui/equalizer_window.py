# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""10-band graphic equalizer panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from pulsedeck.audio.equalizer import (
    BAND_LABELS,
    BANDS,
    CUSTOM_PRESET_NAME,
    MAX_GAIN,
    MAX_PREAMP,
    MIN_GAIN,
    MIN_PREAMP,
    EqualizerState,
    PresetError,
)
from pulsedeck.ui.panels import PanelWindow

SCALE = 10  # slider units per dB (0.1 dB resolution)


def _fmt_db(value: float) -> str:
    return f"{value:+.1f}" if value else "0.0"


class ResetSlider(QSlider):
    """Vertical slider that returns to 0 dB on double-click."""

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802,ANN001
        self.setValue(0)
        event.accept()


class BandSlider(QWidget):
    def __init__(self, label: str, low: float, high: float, accessible: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.slider = ResetSlider(Qt.Orientation.Vertical)
        self.slider.setRange(int(low * SCALE), int(high * SCALE))
        self.slider.setSingleStep(5)
        self.slider.setPageStep(30)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
        self.slider.setTickInterval(int(6 * SCALE))
        self.slider.setMinimumHeight(150)
        self.slider.setAccessibleName(accessible)
        self.value_label = QLabel("0.0")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setProperty("role", "muted")
        self.value_label.setMinimumWidth(38)
        self.name = QLabel(label)
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setToolTip("Double-click the slider to reset to 0 dB")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.value_label)
        layout.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.name)
        self.slider.valueChanged.connect(lambda v: self.value_label.setText(_fmt_db(v / SCALE)))

    def value(self) -> float:
        return self.slider.value() / SCALE

    def set_value(self, db: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(db * SCALE)))
        self.slider.blockSignals(False)
        self.value_label.setText(_fmt_db(db))


class EqualizerWindow(PanelWindow):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(controller, "equalizer", "Equalizer", parent)
        self.resize(620, 330)
        self._updating = False

        self.enabled_box = QCheckBox("Enabled")
        self.enabled_box.setToolTip("Turn the equalizer on or off")
        self.bypass = QPushButton("Bypass")
        self.bypass.setCheckable(True)
        self.bypass.setToolTip("Temporarily bypass all equalizer processing to compare with the original audio")
        self.auto_preamp = QCheckBox("Auto preamp")
        self.auto_preamp.setToolTip("Lower the level automatically when bands are boosted, to avoid clipping")
        self.reset = QPushButton("Reset")
        self.reset.setToolTip("Set all bands and the preamp to 0 dB")
        top = QHBoxLayout()
        top.addWidget(self.enabled_box)
        top.addWidget(self.auto_preamp)
        top.addStretch(1)
        top.addWidget(self.bypass)
        top.addWidget(self.reset)

        self.preamp = BandSlider("Preamp", MIN_PREAMP, MAX_PREAMP, "Preamp")
        self.bands = [BandSlider(label, MIN_GAIN, MAX_GAIN, f"{freq} Hz band")
                      for label, freq in zip(BAND_LABELS, BANDS, strict=True)]
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.addWidget(self.preamp, 0, 0)
        scale = QVBoxLayout()
        for text in (f"+{MAX_GAIN:g} dB", "0 dB", f"{MIN_GAIN:g} dB"):
            label = QLabel(text)
            label.setProperty("role", "muted")
            scale.addWidget(label)
            if text != f"{MIN_GAIN:g} dB":
                scale.addStretch(1)
        grid.addLayout(scale, 0, 1)
        for i, band in enumerate(self.bands):
            grid.addWidget(band, 0, i + 2)
        self.headroom = QLabel("")
        self.headroom.setProperty("role", "muted")

        self.presets = QComboBox()
        self.presets.setMinimumWidth(160)
        self.presets.setAccessibleName("Preset")
        save_btn = QPushButton("Save As…")
        self.rename_btn = QPushButton("Rename…")
        self.delete_btn = QPushButton("Delete")
        import_btn = QPushButton("Import…")
        export_btn = QPushButton("Export…")
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Preset:"))
        bottom.addWidget(self.presets)
        for button in (save_btn, self.rename_btn, self.delete_btn, import_btn, export_btn):
            bottom.addWidget(button)
        bottom.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(top)
        layout.addLayout(grid, 1)
        layout.addWidget(self.headroom)
        layout.addLayout(bottom)

        self.enabled_box.toggled.connect(self._on_enabled)
        self.bypass.toggled.connect(self._on_bypass)
        self.auto_preamp.toggled.connect(self._on_auto_preamp)
        self.reset.clicked.connect(self._on_reset)
        self.preamp.slider.valueChanged.connect(self._on_slider)
        for band in self.bands:
            band.slider.valueChanged.connect(self._on_slider)
        self.presets.activated.connect(self._on_preset_chosen)
        save_btn.clicked.connect(self.save_preset)
        self.rename_btn.clicked.connect(self.rename_preset)
        self.delete_btn.clicked.connect(self.delete_preset)
        import_btn.clicked.connect(self.import_presets)
        export_btn.clicked.connect(self.export_preset)
        controller.equalizer_changed.connect(self.sync_from_state)
        self.reload_presets()
        self.sync_from_state()

    # -- state <-> widgets -------------------------------------------------
    @property
    def state(self) -> EqualizerState:
        return self.controller.eq

    def sync_from_state(self) -> None:
        self._updating = True
        s = self.state
        self.enabled_box.setChecked(s.enabled)
        self.bypass.setChecked(s.bypass)
        self.auto_preamp.setChecked(s.auto_preamp)
        self.preamp.set_value(s.preamp)
        for band, gain in zip(self.bands, s.gains, strict=True):
            band.set_value(gain)
        for widget in [self.preamp, *self.bands]:
            widget.setEnabled(s.enabled)
        self._select_preset_name(s.preset)
        self._updating = False
        self._update_headroom()

    def _update_headroom(self) -> None:
        s = self.state
        if not s.enabled:
            self.headroom.setText("Equalizer is off - audio is not processed.")
        elif s.bypass:
            self.headroom.setText("Bypassed - you are hearing the original audio.")
        elif s.auto_preamp and s.headroom_db:
            self.headroom.setText(f"Auto preamp: {s.headroom_db:+.1f} dB to prevent clipping "
                                  f"(output level {s.effective_preamp:+.1f} dB)")
        else:
            self.headroom.setText(f"Output level {s.effective_preamp:+.1f} dB")

    def _push(self) -> None:
        self.controller.apply_equalizer(self.state)
        self._update_headroom()

    def _on_slider(self, _value: int) -> None:
        if self._updating:
            return
        s = self.state
        s.preamp = self.preamp.value()
        for index, band in enumerate(self.bands):
            if s.gains[index] != band.value():
                s.set_band(index, band.value())
        if s.preset != CUSTOM_PRESET_NAME:
            preset = self.controller.presets.get(s.preset)
            if preset is None or list(preset.gains) != s.gains or preset.preamp != s.preamp:
                s.preset = CUSTOM_PRESET_NAME
        self._select_preset_name(s.preset)
        self._push()

    def _on_enabled(self, checked: bool) -> None:
        if self._updating:
            return
        self.state.enabled = checked
        for widget in [self.preamp, *self.bands]:
            widget.setEnabled(checked)
        self._push()

    def _on_bypass(self, checked: bool) -> None:
        if self._updating:
            return
        self.state.bypass = checked
        self._push()

    def _on_auto_preamp(self, checked: bool) -> None:
        if self._updating:
            return
        self.state.auto_preamp = checked
        self._push()

    def _on_reset(self) -> None:
        self.state.reset()
        self.sync_from_state()
        self._push()

    # -- presets -----------------------------------------------------------
    def reload_presets(self) -> None:
        self.presets.blockSignals(True)
        self.presets.clear()
        store = self.controller.presets
        for name in store.names():
            self.presets.addItem(name)
        self.presets.insertSeparator(len(store.names()) - len(store.custom_names()))
        self.presets.addItem(CUSTOM_PRESET_NAME)
        self.presets.blockSignals(False)
        self._select_preset_name(self.state.preset)

    def _select_preset_name(self, name: str) -> None:
        index = self.presets.findText(name)
        if index < 0:
            index = self.presets.findText(CUSTOM_PRESET_NAME)
        self.presets.blockSignals(True)
        self.presets.setCurrentIndex(index)
        self.presets.blockSignals(False)
        custom = name in self.controller.presets.custom_names()
        self.rename_btn.setEnabled(custom)
        self.delete_btn.setEnabled(custom)

    def _on_preset_chosen(self, index: int) -> None:
        name = self.presets.itemText(index)
        preset = self.controller.presets.get(name)
        if preset is None:
            return
        self.state.apply_preset(preset)
        if not self.state.enabled:
            self.state.enabled = True
        self.sync_from_state()
        self._push()

    def save_preset(self) -> None:
        suggestion = self.state.preset if self.state.preset in self.controller.presets.custom_names() else "My preset"
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:", text=suggestion)
        if not ok or not name.strip():
            return
        store = self.controller.presets
        if store.get(name) is not None and not store.is_builtin(name):
            answer = QMessageBox.question(self, "Save preset", f"Replace the existing preset '{name}'?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            preset = store.save(name, self.state.gains, self.state.preamp)
        except PresetError as exc:
            QMessageBox.warning(self, "Save preset", str(exc))
            return
        self.state.preset = preset.name
        self.reload_presets()
        self._push()

    def rename_preset(self) -> None:
        old = self.state.preset
        name, ok = QInputDialog.getText(self, "Rename preset", "New name:", text=old)
        if not ok or not name.strip() or name == old:
            return
        try:
            preset = self.controller.presets.rename(old, name)
        except PresetError as exc:
            QMessageBox.warning(self, "Rename preset", str(exc))
            return
        self.state.preset = preset.name
        self.reload_presets()
        self._push()

    def delete_preset(self) -> None:
        name = self.state.preset
        answer = QMessageBox.question(self, "Delete preset", f"Delete the preset '{name}'?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.presets.delete(name)
        except PresetError as exc:
            QMessageBox.warning(self, "Delete preset", str(exc))
            return
        self.state.preset = CUSTOM_PRESET_NAME
        self.reload_presets()
        self._push()

    def import_presets(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import presets", "", "Equalizer presets (*.json)")
        if not path:
            return
        try:
            imported = self.controller.presets.import_file(Path(path))
        except PresetError as exc:
            QMessageBox.warning(self, "Import presets", str(exc))
            return
        self.reload_presets()
        self.controller.message.emit(f"Imported {len(imported)} preset(s)")

    def export_preset(self) -> None:
        name = self.state.preset
        store = self.controller.presets
        if store.get(name) is None:
            name, ok = QInputDialog.getText(self, "Export preset", "Name for the current settings:", text="My preset")
            if not ok or not name.strip():
                return
            try:
                store.save(name, self.state.gains, self.state.preamp)
            except PresetError as exc:
                QMessageBox.warning(self, "Export preset", str(exc))
                return
            self.state.preset = name
            self.reload_presets()
        path, _ = QFileDialog.getSaveFileName(self, "Export preset", f"{name}.json", "Equalizer preset (*.json)")
        if not path:
            return
        try:
            store.export(name, Path(path))
        except (PresetError, OSError) as exc:
            QMessageBox.warning(self, "Export preset", str(exc))
