# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Base class for the independent panel windows (playlist, EQ, library...)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QShowEvent
from PySide6.QtWidgets import QWidget

from pulsedeck.core.configuration import Configuration


def save_geometry(config: Configuration, name: str, widget: QWidget) -> None:
    geometry = dict(config.get("interface.geometry", {}) or {})
    geometry[name] = bytes(widget.saveGeometry().toBase64()).decode("ascii")
    config.set("interface.geometry", geometry)


def restore_geometry(config: Configuration, name: str, widget: QWidget) -> bool:
    data = (config.get("interface.geometry", {}) or {}).get(name)
    if not data:
        return False
    return bool(widget.restoreGeometry(QByteArray.fromBase64(data.encode("ascii"))))


class PanelWindow(QWidget):
    """Top-level tool window that remembers its geometry and visibility."""

    visibility_changed = Signal(str, bool)

    def __init__(self, controller, name: str, title: str, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent, Qt.WindowType.Window)
        self.controller = controller
        self.panel_name = name
        self.setWindowTitle(f"{title} - PulseDeck")
        self._geometry_restored = False

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        if not self._geometry_restored:
            restore_geometry(self.controller.config, self.panel_name, self)
            self._geometry_restored = True
        super().showEvent(event)
        self._set_visible_flag(True)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        save_geometry(self.controller.config, self.panel_name, self)
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        save_geometry(self.controller.config, self.panel_name, self)
        self._set_visible_flag(False)
        super().closeEvent(event)

    def _set_visible_flag(self, visible: bool) -> None:
        panels = dict(self.controller.config.get("interface.panels", {}) or {})
        if panels.get(self.panel_name) != visible:
            panels[self.panel_name] = visible
            self.controller.config.set("interface.panels", panels)
        self.visibility_changed.emit(self.panel_name, visible)

    def toggle(self) -> None:
        if self.isVisible():
            self.close()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
