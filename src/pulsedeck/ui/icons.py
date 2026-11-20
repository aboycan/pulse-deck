# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Original vector icons drawn with QPainter.

Drawing the icons in code keeps every visual asset original to PulseDeck,
makes them recolour with the active theme, and keeps them crisp on HiDPI
screens.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_cache: dict[tuple[str, str, int], QIcon] = {}


def _tri(path: QPainterPath, x: float, y: float, w: float, h: float) -> None:
    path.moveTo(x, y)
    path.lineTo(x + w, y + h / 2)
    path.lineTo(x, y + h)
    path.closeSubpath()


def _tri_left(path: QPainterPath, x: float, y: float, w: float, h: float) -> None:
    path.moveTo(x + w, y)
    path.lineTo(x, y + h / 2)
    path.lineTo(x + w, y + h)
    path.closeSubpath()


def _draw(name: str, p: QPainter, s: float, color: QColor) -> None:
    fill = QPainterPath()
    pen = QPen(color, s * 0.09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    m = s * 0.2  # margin
    w = s - 2 * m
    if name == "play":
        _tri(fill, m + w * 0.12, m, w * 0.85, w)
    elif name == "pause":
        fill.addRoundedRect(QRectF(m + w * 0.1, m, w * 0.28, w), s * 0.04, s * 0.04)
        fill.addRoundedRect(QRectF(m + w * 0.62, m, w * 0.28, w), s * 0.04, s * 0.04)
    elif name == "stop":
        fill.addRoundedRect(QRectF(m + w * 0.05, m + w * 0.05, w * 0.9, w * 0.9), s * 0.06, s * 0.06)
    elif name == "next":
        _tri(fill, m, m, w * 0.72, w)
        fill.addRect(QRectF(m + w * 0.78, m, w * 0.18, w))
    elif name == "previous":
        fill.addRect(QRectF(m + w * 0.04, m, w * 0.18, w))
        _tri_left(fill, m + w * 0.28, m, w * 0.72, w)
    elif name == "forward":
        _tri(fill, m, m + w * 0.1, w * 0.5, w * 0.8)
        _tri(fill, m + w * 0.5, m + w * 0.1, w * 0.5, w * 0.8)
    elif name == "rewind":
        _tri_left(fill, m, m + w * 0.1, w * 0.5, w * 0.8)
        _tri_left(fill, m + w * 0.5, m + w * 0.1, w * 0.5, w * 0.8)
    elif name in ("volume", "mute"):
        fill.moveTo(m, m + w * 0.35)
        fill.lineTo(m + w * 0.22, m + w * 0.35)
        fill.lineTo(m + w * 0.5, m + w * 0.08)
        fill.lineTo(m + w * 0.5, m + w * 0.92)
        fill.lineTo(m + w * 0.22, m + w * 0.65)
        fill.lineTo(m, m + w * 0.65)
        fill.closeSubpath()
        p.setPen(pen)
        if name == "volume":
            for radius in (0.2, 0.38):
                rect = QRectF(m + w * 0.5 - w * radius, m + w * 0.5 - w * radius, w * radius * 2, w * radius * 2)
                p.drawArc(rect, -45 * 16, 90 * 16)
        else:
            p.drawLine(QPointF(m + w * 0.66, m + w * 0.32), QPointF(m + w, m + w * 0.68))
            p.drawLine(QPointF(m + w, m + w * 0.32), QPointF(m + w * 0.66, m + w * 0.68))
    elif name == "shuffle":
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(m, m + w * 0.25)
        path.cubicTo(m + w * 0.45, m + w * 0.25, m + w * 0.45, m + w * 0.75, m + w * 0.85, m + w * 0.75)
        path.moveTo(m, m + w * 0.75)
        path.cubicTo(m + w * 0.45, m + w * 0.75, m + w * 0.45, m + w * 0.25, m + w * 0.85, m + w * 0.25)
        p.drawPath(path)
        for y in (0.25, 0.75):
            _tri(fill, m + w * 0.78, m + w * (y - 0.14), w * 0.22, w * 0.28)
    elif name in ("repeat", "repeat_one"):
        p.setPen(pen)
        rect = QRectF(m + w * 0.05, m + w * 0.2, w * 0.82, w * 0.6)
        path = QPainterPath()
        path.addRoundedRect(rect, w * 0.25, w * 0.25)
        p.drawPath(path)
        _tri(fill, m + w * 0.52, m + w * 0.06, w * 0.24, w * 0.28)
        if name == "repeat_one":
            font = p.font()
            font.setPixelSize(int(w * 0.5))
            font.setBold(True)
            p.setFont(font)
            p.setPen(color)
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter.value), "1")
    elif name == "equalizer":
        p.setPen(pen)
        for i, level in enumerate((0.3, 0.7, 0.45, 0.6)):
            x = m + w * (0.1 + i * 0.27)
            p.drawLine(QPointF(x, m), QPointF(x, m + w))
            fill.addEllipse(QPointF(x, m + w * level), w * 0.09, w * 0.09)
    elif name == "playlist":
        p.setPen(pen)
        for i in range(3):
            y = m + w * (0.15 + i * 0.3)
            p.drawLine(QPointF(m + w * 0.32, y), QPointF(m + w, y))
            fill.addEllipse(QPointF(m + w * 0.08, y), w * 0.07, w * 0.07)
    elif name == "library":
        p.setPen(pen)
        for i, h in enumerate((0.9, 0.75, 0.9)):
            x = m + w * (0.08 + i * 0.25)
            p.drawLine(QPointF(x, m + w), QPointF(x, m + w * (1 - h)))
        p.drawLine(QPointF(m + w * 0.72, m + w), QPointF(m + w * 0.95, m + w * 0.15))
    elif name == "info":
        p.setPen(pen)
        p.drawEllipse(QRectF(m, m, w, w))
        p.drawLine(QPointF(s / 2, m + w * 0.45), QPointF(s / 2, m + w * 0.78))
        fill.addEllipse(QPointF(s / 2, m + w * 0.25), w * 0.06, w * 0.06)
    elif name == "settings":
        p.setPen(pen)
        center = QPointF(s / 2, s / 2)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(center + QPointF(math.cos(a) * w * 0.32, math.sin(a) * w * 0.32),
                       center + QPointF(math.cos(a) * w * 0.5, math.sin(a) * w * 0.5))
        p.drawEllipse(center, w * 0.3, w * 0.3)
    elif name == "heart":
        fill.moveTo(s / 2, m + w * 0.95)
        fill.cubicTo(m - w * 0.2, m + w * 0.45, m + w * 0.15, m - w * 0.05, s / 2, m + w * 0.25)
        fill.cubicTo(m + w * 0.85, m - w * 0.05, m + w * 1.2, m + w * 0.45, s / 2, m + w * 0.95)
    elif name == "add":
        p.setPen(pen)
        p.drawLine(QPointF(s / 2, m), QPointF(s / 2, m + w))
        p.drawLine(QPointF(m, s / 2), QPointF(m + w, s / 2))
    elif name == "remove":
        p.setPen(pen)
        p.drawLine(QPointF(m, s / 2), QPointF(m + w, s / 2))
    elif name == "up":
        fill.moveTo(s / 2, m + w * 0.15)
        fill.lineTo(m + w, m + w * 0.8)
        fill.lineTo(m, m + w * 0.8)
        fill.closeSubpath()
    elif name == "down":
        fill.moveTo(m, m + w * 0.2)
        fill.lineTo(m + w, m + w * 0.2)
        fill.lineTo(s / 2, m + w * 0.85)
        fill.closeSubpath()
    elif name == "pin":
        p.setPen(pen)
        p.drawLine(QPointF(s / 2, m + w * 0.55), QPointF(s / 2, m + w))
        fill.addRoundedRect(QRectF(m + w * 0.25, m, w * 0.5, w * 0.55), w * 0.1, w * 0.1)
    elif name == "compact":
        p.setPen(pen)
        p.drawRect(QRectF(m, m + w * 0.3, w, w * 0.4))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(fill)


def icon(name: str, color: str = "#d6dbe4", size: int = 32) -> QIcon:
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    result = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw(name, painter, float(size * scale), QColor(color))
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        result.addPixmap(pixmap)
    _cache[key] = result
    return result


def clear_cache() -> None:
    _cache.clear()


def placeholder_artwork(size: int, background: str, foreground: str) -> QPixmap:
    """Neutral artwork placeholder: a disc outline with a pulse line."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(background))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fg = QColor(foreground)
    fg.setAlpha(140)
    pen = QPen(fg, max(2.0, size * 0.025))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    center = QPointF(size / 2, size / 2)
    p.drawEllipse(center, size * 0.32, size * 0.32)
    p.drawEllipse(center, size * 0.06, size * 0.06)
    path = QPainterPath()
    path.moveTo(size * 0.18, size * 0.5)
    for x, y in ((0.36, 0.5), (0.42, 0.36), (0.5, 0.66), (0.58, 0.42), (0.64, 0.5), (0.82, 0.5)):
        path.lineTo(size * x, size * y)
    accent = QColor(foreground)
    p.setPen(QPen(accent, max(2.0, size * 0.03), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.end()
    return pixmap
