# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Theme loading and Qt style sheet generation.

Themes are small JSON files (see ``docs/THEMES.md``). Built-in themes live
in ``assets/themes``; users can drop their own into the ``themes`` folder in
their PulseDeck configuration directory. This module does not import Qt so
it can be validated by the test-suite on its own.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pulsedeck.core import platform

log = logging.getLogger(__name__)

REQUIRED_COLORS = (
    "window", "panel", "base", "alt_base", "text", "muted", "accent", "accent_text", "border",
    "highlight", "display_bg", "display_text", "display_dim", "groove", "danger", "button", "button_hover",
)
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
DEFAULT_THEME = "classic_dark"


class ThemeError(Exception):
    pass


@dataclass
class Theme:
    id: str
    name: str
    colors: dict[str, str]
    radius: int = 4
    font_family: str = ""
    source: Path | None = field(default=None, compare=False)

    def color(self, key: str) -> str:
        return self.colors[key]


def user_theme_dir() -> Path:
    path = platform.config_dir() / "themes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def builtin_theme_dir() -> Path:
    return platform.assets_dir() / "themes"


def parse_theme(data: dict, source: Path | None = None) -> Theme:
    if not isinstance(data, dict):
        raise ThemeError("Theme must be a JSON object")
    colors = data.get("colors")
    if not isinstance(colors, dict):
        raise ThemeError("Theme needs a 'colors' object")
    missing = [k for k in REQUIRED_COLORS if k not in colors]
    if missing:
        raise ThemeError(f"Theme is missing colors: {', '.join(missing)}")
    for key, value in colors.items():
        if not isinstance(value, str) or not _HEX.match(value):
            raise ThemeError(f"Color '{key}' must be #RRGGBB or #RRGGBBAA, got {value!r}")
    theme_id = str(data.get("id") or (source.stem if source else "")).strip()
    if not theme_id:
        raise ThemeError("Theme needs an 'id'")
    return Theme(
        id=theme_id,
        name=str(data.get("name") or theme_id),
        colors={k: str(v) for k, v in colors.items()},
        radius=max(0, min(16, int(data.get("radius", 4)))),
        font_family=str(data.get("font_family", "")),
        source=source,
    )


def load_theme_file(path: Path) -> Theme:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ThemeError(f"Cannot read theme {path.name}: {exc}") from exc
    return parse_theme(data, path)


def available_themes(extra_dirs: list[Path] | None = None) -> dict[str, Theme]:
    themes: dict[str, Theme] = {}
    dirs = [builtin_theme_dir(), user_theme_dir(), *(extra_dirs or [])]
    for directory in dirs:
        if not directory.is_dir():
            continue
        for file in sorted(directory.glob("*.json")):
            try:
                theme = load_theme_file(file)
            except ThemeError as exc:
                log.warning("%s", exc)
                continue
            themes[theme.id] = theme
    return themes


def get_theme(theme_id: str) -> Theme:
    themes = available_themes()
    if theme_id in themes:
        return themes[theme_id]
    if DEFAULT_THEME in themes:
        return themes[DEFAULT_THEME]
    raise ThemeError("No themes installed")


def _contrast_text(hex_color: str) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000000" if luminance > 150 else "#ffffff"


def with_accent(theme: Theme, accent: str | None) -> Theme:
    if not accent or not _HEX.match(accent):
        return theme
    colors = dict(theme.colors)
    colors["accent"] = accent
    colors["accent_text"] = _contrast_text(accent)
    return Theme(theme.id, theme.name, colors, theme.radius, theme.font_family, theme.source)


def build_stylesheet(theme: Theme, font_size: int = 10) -> str:
    c = theme.colors
    r = theme.radius
    font = f'font-family: "{theme.font_family}";' if theme.font_family else ""
    return f"""
* {{ font-size: {font_size}pt; {font} }}
QWidget {{ background-color: {c['window']}; color: {c['text']}; }}
QToolTip {{ background-color: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenuBar, QMenu {{ background-color: {c['panel']}; color: {c['text']}; }}
QMenu {{ border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: {r}px; }}
QMenu::item:selected, QMenuBar::item:selected {{ background-color: {c['highlight']}; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QFrame#Display {{ background-color: {c['display_bg']}; border: 1px solid {c['border']}; border-radius: {r}px; }}
QFrame#Display QLabel {{ background: transparent; color: {c['display_text']}; }}
QFrame#Display QLabel[role="dim"] {{ color: {c['display_dim']}; }}
QLabel#TimeLabel {{ font-size: {font_size + 10}pt; font-weight: 600; }}
QLabel#TitleLabel {{ font-size: {font_size + 2}pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {c['muted']}; }}
QPushButton, QToolButton {{
    background-color: {c['button']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: {r}px; padding: 4px 10px;
}}
QToolButton {{ padding: 4px; }}
QPushButton:hover, QToolButton:hover {{ background-color: {c['button_hover']}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked, QPushButton:checked {{
    background-color: {c['highlight']}; border-color: {c['accent']};
}}
QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; }}
QPushButton[accent="true"] {{ background-color: {c['accent']}; color: {c['accent_text']}; border-color: {c['accent']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QKeySequenceEdit, QPlainTextEdit, QTextEdit {{
    background-color: {c['base']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: {r}px; padding: 3px 6px; selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c['accent']}; }}
QComboBox QAbstractItemView {{ background-color: {c['panel']}; selection-background-color: {c['highlight']}; }}
QTableView, QTreeView, QListView, QListWidget, QTreeWidget {{
    background-color: {c['base']}; alternate-background-color: {c['alt_base']};
    border: 1px solid {c['border']}; border-radius: {r}px; gridline-color: {c['border']};
    selection-background-color: {c['highlight']}; selection-color: {c['text']};
}}
QHeaderView::section {{
    background-color: {c['panel']}; color: {c['muted']}; border: none;
    border-right: 1px solid {c['border']}; border-bottom: 1px solid {c['border']}; padding: 4px 6px;
}}
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: {r}px; top: -1px; }}
QTabBar::tab {{ background: {c['panel']}; color: {c['muted']}; padding: 6px 14px; border: 1px solid {c['border']};
    border-bottom: none; border-top-left-radius: {r}px; border-top-right-radius: {r}px; }}
QTabBar::tab:selected {{ color: {c['text']}; background: {c['window']}; border-bottom: 2px solid {c['accent']}; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: {r}px; margin-top: 14px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {c['muted']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['groove']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; background: {c['text']}; }}
QSlider::groove:vertical {{ width: 4px; background: {c['groove']}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:vertical {{ height: 10px; width: 18px; margin: 0 -7px; border-radius: 3px; background: {c['text']}; }}
QProgressBar {{ background: {c['groove']}; border: none; border-radius: {r}px; text-align: center; color: {c['text']}; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: {r}px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['groove']}; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['groove']}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ color: {c['muted']}; }}
QSplitter::handle {{ background: {c['border']}; }}
"""
