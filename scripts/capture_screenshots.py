# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Render README screenshots of every panel, offscreen, using synthetic demo data.

Usage:  QT_QPA_PLATFORM=offscreen python scripts/capture_screenshots.py docs/screenshots

The demo tracks are short sine tones generated with ffmpeg (if available) or
empty placeholder files, so every pixel in the screenshots is PulseDeck's own
artwork - no third-party album covers or music.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEMO = [
    ("Northern Lights", "Aurora Fields", "Polar Nights", 214),
    ("Glass Harbour", "Aurora Fields", "Polar Nights", 187),
    ("Midnight Transit", "The Lanterns", "City Loops", 241),
    ("Copper Sky", "The Lanterns", "City Loops", 199),
    ("Slow Tide", "Mira Okafor", "Shorelines", 263),
    ("Paper Planes", "Mira Okafor", "Shorelines", 176),
]


def make_demo_files(folder: Path) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    paths = []
    for i, (title, artist, album, _seconds) in enumerate(DEMO):
        path = folder / artist / album / f"{i + 1:02d} {title}.flac"
        path.parent.mkdir(parents=True, exist_ok=True)
        if ffmpeg:
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"sine=frequency={220 + i * 55}:duration=3", "-metadata", f"title={title}",
                            "-metadata", f"artist={artist}", "-metadata", f"album={album}",
                            "-metadata", "genre=Electronic", "-metadata", "date=2026", str(path)], check=True)
        else:
            path.write_bytes(b"\0")
        paths.append(str(path))
    return paths


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PULSEDECK_HOME"] = str(Path(tmp) / "home")
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication

        from pulsedeck.application import AppController
        from pulsedeck.audio.backend import SimulatedBackend
        from pulsedeck.audio.equalizer import BUILTIN_PRESETS
        from pulsedeck.core.configuration import Configuration
        from pulsedeck.library.models import TrackInfo
        from pulsedeck.ui.equalizer_window import EqualizerWindow
        from pulsedeck.ui.info_window import InfoWindow
        from pulsedeck.ui.library_window import LibraryWindow
        from pulsedeck.ui.main_window import MainWindow
        from pulsedeck.ui.playlist_window import PlaylistWindow
        from pulsedeck.ui.settings_window import SettingsWindow
        from pulsedeck.ui.theme import build_stylesheet, get_theme

        app = QApplication.instance() or QApplication([])
        paths = make_demo_files(Path(tmp) / "Music")
        durations = {p: float(d[3]) for p, d in zip(paths, DEMO, strict=True)}
        config = Configuration()
        controller = AppController(config=config, backend_factory=lambda cb: SimulatedBackend(
            durations=durations, callbacks=cb))
        for path, (title, artist, album, seconds) in zip(paths, DEMO, strict=True):
            info = TrackInfo(path=path, title=title, artist=artist, album=album, duration=seconds, genre="Electronic",
                             year="2026", bitrate=920_000, sample_rate=44_100, channels=2, codec="flac",
                             file_size=os.path.getsize(path))
            controller.db.upsert_track(info)
            controller._metadata_cache[path] = info  # noqa: SLF001

        for theme_id in ("classic_dark", "light"):
            theme = get_theme(theme_id)
            app.setStyleSheet(build_stylesheet(theme, 10))
            window = MainWindow(controller)
            panels = {"playlist": PlaylistWindow(controller, window), "equalizer": EqualizerWindow(controller, window),
                      "library": LibraryWindow(controller, window), "info": InfoWindow(controller, window),
                      "settings": SettingsWindow(controller, lambda: None, window)}
            for name, panel in panels.items():
                window.register_panel(name, panel)
            window.apply_theme(theme)
            panels["playlist"].apply_theme(theme)
            if not controller.active_playlist.entries:
                controller.open_paths(paths, play=True)
            controller.engine.wait_idle()
            controller.seek(83.0)
            controller.eq.apply_preset(next(p for p in BUILTIN_PRESETS if p.name == "Electronic"))
            controller.apply_equalizer()
            window.resize(540, 250)
            window.show()
            for panel in panels.values():
                panel.show()
            for _ in range(10):
                controller.engine.wait_idle()
                QCoreApplication.processEvents()
            suffix = "" if theme_id == "classic_dark" else f"-{theme_id}"
            window.grab().save(str(out / f"main{suffix}.png"))
            for name, panel in panels.items():
                panel.grab().save(str(out / f"{name}{suffix}.png"))
            for panel in panels.values():
                panel.hide()
            window.hide()
        controller.shutdown()
    print(f"Screenshots written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
