# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QSlider, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget


class JumpSlider(QSlider):
    """Slider that jumps straight to the clicked position (seek/volume bars)."""

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            handle = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
            )
            if not handle.contains(event.position().toPoint()):
                if self.orientation() == Qt.Orientation.Horizontal:
                    span, pos = self.width(), event.position().x()
                else:
                    span, pos = self.height(), self.height() - event.position().y()
                value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(pos), max(1, span))
                self.setSliderDown(True)
                self.setValue(value)
                self.sliderMoved.emit(value)
                self.setSliderDown(False)
                self.sliderReleased.emit()
                event.accept()
                return
        super().mousePressEvent(event)


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ArtworkDialog(QDialog):
    """Shows album artwork at full size (scaled to fit the screen)."""

    def __init__(self, data: bytes, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or "Artwork")
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(data))
        screen = self.screen().availableGeometry() if self.screen() else None
        max_side = int(min(screen.width(), screen.height()) * 0.8) if screen else 900
        if pixmap.width() > max_side or pixmap.height() > max_side:
            pixmap = pixmap.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        label = QLabel()
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        area = QScrollArea()
        area.setWidget(label)
        area.setWidgetResizable(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)
        self.resize(min(pixmap.width() + 24, max_side + 24), min(pixmap.height() + 24, max_side + 24))
