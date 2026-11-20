# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Main player window."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pulsedeck import APP_NAME, __version__
from pulsedeck.audio.backend import AudioParams
from pulsedeck.audio.playback_engine import PlaybackState
from pulsedeck.audio.playback_queue import RepeatMode
from pulsedeck.core import platform
from pulsedeck.library.models import AUDIO_EXTENSIONS, TrackInfo, format_duration
from pulsedeck.playlists.manager import save_playlist_file
from pulsedeck.ui import icons, shortcuts
from pulsedeck.ui.panels import restore_geometry, save_geometry
from pulsedeck.ui.player_controls import SeekBar, TransportBar
from pulsedeck.ui.theme import Theme
from pulsedeck.ui.widgets import ArtworkDialog, ClickableLabel

log = logging.getLogger(__name__)

AUDIO_FILTER = "Audio files ({});;All files (*)".format(" ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS)))
PLAYLIST_FILTER = "Playlists (*.m3u *.m3u8 *.json);;M3U8 playlist (*.m3u8);;M3U playlist (*.m3u);;" \
                  "PulseDeck playlist (*.json)"
ART_SIZE = 96


class DisplayPanel(QFrame):
    """The 'screen' of the player: artwork, track text, time and format."""

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("Display")
        self.controller = controller
        self.show_remaining = False
        self.theme: Theme | None = None

        self.art = ClickableLabel()
        self.art.setFixedSize(ART_SIZE, ART_SIZE)
        self.art.setScaledContents(False)
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art.setToolTip("Click to view artwork")
        self.art.setCursor(Qt.CursorShape.PointingHandCursor)
        self.art.clicked.connect(self.view_artwork)

        self.time = ClickableLabel("0:00")
        self.time.setObjectName("TimeLabel")
        self.time.setToolTip("Click to toggle elapsed / remaining time")
        self.time.clicked.connect(self._toggle_time_mode)
        self.status = QLabel("Stopped")
        self.status.setProperty("role", "dim")
        self.title = QLabel(f"{APP_NAME}")
        self.title.setObjectName("TitleLabel")
        self.subtitle = QLabel("Open some music to get started")
        self.subtitle.setProperty("role", "dim")
        self.format = QLabel("")
        self.format.setProperty("role", "dim")
        for label in (self.title, self.subtitle, self.format):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        right = QVBoxLayout()
        right.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(self.time)
        top.addStretch(1)
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignTop)
        right.addLayout(top)
        right.addWidget(self.title)
        right.addWidget(self.subtitle)
        right.addWidget(self.format)
        right.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(self.art, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(right, 1)

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._restore_status)

        controller.track_changed.connect(self.set_track)
        controller.position_changed.connect(self.set_position)
        controller.state_changed.connect(lambda _s: self._restore_status())
        controller.audio_params_changed.connect(self.set_params)
        controller.message.connect(self.flash)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.set_track(self.controller.current_track)

    def set_track(self, info: TrackInfo | None) -> None:
        if info is None:
            self.title.setText(APP_NAME)
            self.subtitle.setText("Open some music to get started")
            self.format.setText("")
            self._set_art(None)
            return
        self.title.setText(info.display_title)
        self.title.setToolTip(info.path)
        parts = [info.display_artist]
        if info.album:
            parts.append(info.album)
        self.subtitle.setText("  ·  ".join(parts))
        self.set_params(AudioParams(codec=info.codec, bitrate=info.bitrate, sample_rate=info.sample_rate,
                                    channels=info.channels))
        thumb = self.controller.artwork.thumbnail(info.path, ART_SIZE * 2)
        self._set_art(str(thumb) if thumb else None)

    def _set_art(self, path: str | None) -> None:
        dpr = self.devicePixelRatioF()
        if path:
            pixmap = QPixmap(path)
            pixmap = pixmap.scaled(int(ART_SIZE * dpr), int(ART_SIZE * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(dpr)
        else:
            bg = self.theme.color("display_bg") if self.theme else "#07110d"
            fg = self.theme.color("display_dim") if self.theme else "#2b7a5d"
            pixmap = icons.placeholder_artwork(int(ART_SIZE * dpr), bg, fg)
            pixmap.setDevicePixelRatio(dpr)
        self.art.setPixmap(pixmap)

    def set_params(self, params: AudioParams) -> None:
        info = self.controller.current_track
        bits = []
        codec = (params.codec or (info.codec if info else "")).upper()
        if codec:
            bits.append(codec)
        rate = params.sample_rate or (info.sample_rate if info else 0)
        if rate:
            bits.append(f"{rate / 1000:g} kHz")
        bitrate = params.bitrate or (info.bitrate if info else 0)
        if bitrate:
            bits.append(f"{round(bitrate / 1000)} kbps")
        channels = params.channels or (info.channels if info else 0)
        if channels:
            bits.append({1: "Mono", 2: "Stereo"}.get(channels, f"{channels} ch"))
        self.format.setText("  ·  ".join(bits))

    def set_position(self, position: float, duration: float) -> None:
        if self.show_remaining and duration:
            self.time.setText("-" + format_duration(max(0.0, duration - position)))
        else:
            self.time.setText(format_duration(position))

    def _toggle_time_mode(self) -> None:
        self.show_remaining = not self.show_remaining
        self.set_position(self.controller.position, self.controller.duration)

    def _restore_status(self) -> None:
        if self._message_timer.isActive():
            return
        c = self.controller
        text = {PlaybackState.PLAYING: "Playing", PlaybackState.PAUSED: "Paused",
                PlaybackState.STOPPED: "Stopped"}[c.state]
        flags = []
        if c.shuffle:
            flags.append("SHUF")
        if c.repeat is not RepeatMode.OFF:
            flags.append("REP-1" if c.repeat is RepeatMode.ONE else "REP")
        self.status.setText("  ".join([text, *flags]))

    def flash(self, text: str) -> None:
        self.status.setText(text if len(text) < 60 else text[:57] + "…")
        self.status.setToolTip(text)
        self._message_timer.start(4000)

    def view_artwork(self) -> None:
        info = self.controller.current_track
        if info is None:
            return
        data = self.controller.artwork.load_original(info.path)
        if not data:
            self.flash("No artwork for this track")
            return
        ArtworkDialog(data, f"{info.display_title} - artwork", self.window()).exec()


class MainWindow(QMainWindow):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.panels: dict = {}
        self.tray = None   # set by SystemIntegration
        self.action_map: dict[str, QAction] = {}
        self._quitting = False
        self.theme: Theme | None = None
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setMinimumWidth(420)

        central = QWidget()
        self.setCentralWidget(central)
        self.display = DisplayPanel(controller)
        self.seek_bar = SeekBar(controller)
        self.transport = TransportBar(controller)

        self.panel_buttons: dict[str, QToolButton] = {}
        panel_row = QHBoxLayout()
        panel_row.setSpacing(4)
        for name, icon_name, tip in (("playlist", "playlist", "Playlist editor"), ("equalizer", "equalizer", "Equalizer"),
                                     ("library", "library", "Music library"), ("info", "info", "Audio information")):
            button = QToolButton()
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setIconSize(QSize(18, 18))
            button.setProperty("icon_name", icon_name)
            button.clicked.connect(lambda _c=False, n=name: self.toggle_panel(n))
            self.panel_buttons[name] = button
            panel_row.addWidget(button)
        panel_row.addStretch(1)
        self.pin_btn = QToolButton()
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Always on top")
        self.pin_btn.setIconSize(QSize(18, 18))
        self.pin_btn.clicked.connect(lambda checked: self.set_always_on_top(checked))
        self.compact_btn = QToolButton()
        self.compact_btn.setCheckable(True)
        self.compact_btn.setToolTip("Compact mode")
        self.compact_btn.setIconSize(QSize(18, 18))
        self.compact_btn.clicked.connect(lambda checked: self.set_compact(checked))
        self.settings_btn = QToolButton()
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.clicked.connect(lambda: self.show_panel("settings"))
        for b in (self.pin_btn, self.compact_btn, self.settings_btn):
            panel_row.addWidget(b)
        self.panel_row_widget = QWidget()
        self.panel_row_widget.setLayout(panel_row)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.display)
        layout.addWidget(self.seek_bar)
        layout.addWidget(self.transport)
        layout.addWidget(self.panel_row_widget)

        self._build_actions()
        self._build_menus()
        controller.error.connect(self.show_error)
        controller.track_changed.connect(self._update_title)
        controller.state_changed.connect(lambda _s: self._update_title(controller.current_track))
        controller.options_changed.connect(self._sync_option_actions)
        controller.settings_changed.connect(self._on_setting_changed)

        if not restore_geometry(controller.config, "main", self):
            self.resize(520, 250)
        self.set_always_on_top(bool(controller.config.get("interface.always_on_top")), save=False)
        self.set_compact(bool(controller.config.get("interface.compact_mode")), save=False)

    # -- actions and menus ----------------------------------------------
    def _build_actions(self) -> None:
        c = self.controller
        handlers = {
            "play_pause": c.toggle_play_pause, "stop": c.stop, "open_files": self.open_files,
            "open_folder": self.open_folder, "save_playlist": self.save_playlist,
            "new_playlist": self.new_playlist, "search": self.focus_search, "next": c.next_track,
            "previous": c.previous_track, "volume_up": lambda: c.change_volume(5),
            "volume_down": lambda: c.change_volume(-5), "mute": c.toggle_mute, "forward": c.fast_forward,
            "rewind": c.rewind, "shuffle": lambda: c.set_shuffle(not c.shuffle), "repeat": c.cycle_repeat,
            "toggle_playlist": lambda: self.toggle_panel("playlist"),
            "toggle_equalizer": lambda: self.toggle_panel("equalizer"),
            "toggle_library": lambda: self.toggle_panel("library"),
            "toggle_info": lambda: self.toggle_panel("info"),
            "settings": lambda: self.show_panel("settings"), "quit": self.quit,
        }
        for spec in shortcuts.ACTIONS:
            action = QAction(spec.label, self)
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(handlers[spec.id])
            self.action_map[spec.id] = action
            self.addAction(action)
        self.action_map["shuffle"].setCheckable(True)
        self.action_map["mute"].setCheckable(True)
        self.action_map["quit"].setMenuRole(QAction.MenuRole.QuitRole)
        self.action_map["settings"].setMenuRole(QAction.MenuRole.PreferencesRole)
        self.apply_shortcuts()

    def apply_shortcuts(self) -> None:
        mapping = shortcuts.effective(self.controller.config.get("shortcuts", {}))
        for action_id, sequence in mapping.items():
            if action_id in self.action_map:
                self.action_map[action_id].setShortcut(QKeySequence(sequence))

    def _build_menus(self) -> None:
        bar = self.menuBar()
        a = self.action_map
        file_menu = bar.addMenu("&File")
        for key in ("open_files", "open_folder"):
            file_menu.addAction(a[key])
        open_pl = file_menu.addAction("Open Playlist…")
        open_pl.triggered.connect(self.open_playlist_file)
        file_menu.addSeparator()
        file_menu.addAction(a["new_playlist"])
        file_menu.addAction(a["save_playlist"])
        file_menu.addSeparator()
        file_menu.addAction(a["settings"])
        file_menu.addSeparator()
        file_menu.addAction(a["quit"])

        play_menu = bar.addMenu("&Playback")
        for key in ("play_pause", "stop", "previous", "next", "rewind", "forward"):
            play_menu.addAction(a[key])
        play_menu.addSeparator()
        play_menu.addAction(a["shuffle"])
        repeat_menu = play_menu.addMenu("Repeat")
        self.repeat_group = QActionGroup(self)
        self.repeat_actions: dict[RepeatMode, QAction] = {}
        for mode, label in ((RepeatMode.OFF, "Off"), (RepeatMode.ALL, "Repeat all"), (RepeatMode.ONE, "Repeat one")):
            act = repeat_menu.addAction(label)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, m=mode: self.controller.set_repeat(m))
            self.repeat_group.addAction(act)
            self.repeat_actions[mode] = act
        repeat_menu.addSeparator()
        repeat_menu.addAction(a["repeat"])
        speed_menu = play_menu.addMenu("Playback speed")
        self.speed_group = QActionGroup(self)
        self.speed_actions: dict[float, QAction] = {}
        for speed in (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0):
            act = speed_menu.addAction(f"{speed:g}×")
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, s=speed: self.controller.set_setting("audio.speed", s))
            self.speed_group.addAction(act)
            self.speed_actions[speed] = act
        play_menu.addSeparator()
        for key in ("volume_up", "volume_down", "mute"):
            play_menu.addAction(a[key])

        view_menu = bar.addMenu("&View")
        for key in ("toggle_playlist", "toggle_equalizer", "toggle_library", "toggle_info"):
            view_menu.addAction(a[key])
        view_menu.addSeparator()
        self.on_top_action = view_menu.addAction("Always on Top")
        self.on_top_action.setCheckable(True)
        self.on_top_action.triggered.connect(lambda checked: self.set_always_on_top(checked))
        self.compact_action = view_menu.addAction("Compact Mode")
        self.compact_action.setCheckable(True)
        self.compact_action.triggered.connect(lambda checked: self.set_compact(checked))
        view_menu.addAction(a["search"])

        help_menu = bar.addMenu("&Help")
        about = help_menu.addAction(f"About {APP_NAME}")
        about.setMenuRole(QAction.MenuRole.AboutRole)
        about.triggered.connect(self.show_about)
        licenses = help_menu.addAction("Open-Source Licenses")
        licenses.triggered.connect(self.show_licenses)
        logs = help_menu.addAction("Open Log Folder")
        logs.triggered.connect(lambda: platform.open_folder(platform.log_dir()))
        self._sync_option_actions()

    def _sync_option_actions(self) -> None:
        c = self.controller
        self.action_map["shuffle"].setChecked(c.shuffle)
        self.action_map["mute"].setChecked(c.muted)
        self.repeat_actions[c.repeat].setChecked(True)
        speed = float(c.config.get("audio.speed", 1.0))
        if speed in self.speed_actions:
            self.speed_actions[speed].setChecked(True)
        self.display._restore_status()  # noqa: SLF001

    def _on_setting_changed(self, key: str) -> None:
        config = self.controller.config
        if key == "shortcuts":
            self.apply_shortcuts()
        elif key == "interface.compact_mode":
            self.set_compact(bool(config.get(key)), save=False)
        elif key == "interface.always_on_top":
            self.set_always_on_top(bool(config.get(key)), save=False)
        elif key == "library.show_bitrate":
            self.display.format.setVisible(bool(config.get(key)) and not config.get("interface.compact_mode"))

    # -- theme -----------------------------------------------------------
    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        text, accent = theme.color("text"), theme.color("accent")
        self.transport.set_colors(text, accent)
        for button in self.panel_buttons.values():
            button.setIcon(icons.icon(button.property("icon_name"), text))
        self.pin_btn.setIcon(icons.icon("pin", text))
        self.compact_btn.setIcon(icons.icon("compact", text))
        self.settings_btn.setIcon(icons.icon("settings", text))
        self.display.apply_theme(theme)

    # -- panels ----------------------------------------------------------
    def register_panel(self, name: str, panel) -> None:  # noqa: ANN001
        self.panels[name] = panel
        if hasattr(panel, "visibility_changed"):
            panel.visibility_changed.connect(self._on_panel_visibility)

    def _on_panel_visibility(self, name: str, visible: bool) -> None:
        if name in self.panel_buttons:
            self.panel_buttons[name].setChecked(visible)

    def toggle_panel(self, name: str) -> None:
        panel = self.panels.get(name)
        if panel is not None:
            panel.toggle()

    def show_panel(self, name: str) -> None:
        panel = self.panels.get(name)
        if panel is None:
            return
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def restore_panels(self) -> None:
        visible = self.controller.config.get("interface.panels", {}) or {}
        for name, panel in self.panels.items():
            if name != "settings" and visible.get(name):
                panel.show()

    # -- window behaviour -----------------------------------------------
    def set_always_on_top(self, enabled: bool, save: bool = True) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()
        self.pin_btn.setChecked(enabled)
        self.on_top_action.setChecked(enabled)
        if save:
            self.controller.config.set("interface.always_on_top", enabled)

    def set_compact(self, enabled: bool, save: bool = True) -> None:
        self.display.art.setVisible(not enabled)
        self.display.subtitle.setVisible(not enabled)
        self.display.format.setVisible(not enabled)
        self.panel_row_widget.setVisible(True)
        self.menuBar().setVisible(not enabled or platform.IS_MACOS)
        self.compact_btn.setChecked(enabled)
        self.compact_action.setChecked(enabled)
        if enabled:
            QTimer.singleShot(0, lambda: self.resize(self.width(), self.minimumSizeHint().height()))
        if save:
            self.controller.config.set("interface.compact_mode", enabled)

    def _update_title(self, info: TrackInfo | None) -> None:
        if info is None:
            self.setWindowTitle(APP_NAME)
            return
        prefix = "" if self.controller.state is PlaybackState.PLAYING else "⏸ "
        self.setWindowTitle(f"{prefix}{info.display_artist} - {info.display_title} | {APP_NAME}")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and self.tray is not None
                and self.tray.isVisible() and self.controller.config.get("general.minimize_to_tray")):
            QTimer.singleShot(0, self.hide_to_tray)
        super().changeEvent(event)

    def hide_to_tray(self) -> None:
        self._hidden_panels = [n for n, p in self.panels.items() if p.isVisible()]
        for name in self._hidden_panels:
            self.panels[name].hide()
        self.hide()

    def restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        for name in getattr(self, "_hidden_panels", []):
            self.panels[name].show()
        self._hidden_panels = []

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if (not self._quitting and self.tray is not None and self.tray.isVisible()
                and self.controller.config.get("general.close_to_tray")):
            event.ignore()
            self.hide_to_tray()
            return
        save_geometry(self.controller.config, "main", self)
        self._quitting = True
        for panel in self.panels.values():
            if panel.isVisible():
                save_geometry(self.controller.config, panel.panel_name, panel)
        event.accept()
        QApplication.instance().quit()

    def quit(self) -> None:
        self._quitting = True
        self.close()

    # -- drag and drop ---------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.controller.open_paths(paths, play=True)
            event.acceptProposedAction()

    # -- commands --------------------------------------------------------
    def _start_dir(self) -> str:
        return self.controller.config.get("library.default_music_dir") or str(platform.default_music_dir())

    def open_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open audio files", self._start_dir(), AUDIO_FILTER)
        if files:
            self.controller.open_paths(files, play=True)

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open folder", self._start_dir())
        if folder:
            self.controller.open_paths([folder], play=True)

    def open_playlist_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open playlist", self._start_dir(), PLAYLIST_FILTER)
        if path:
            self.controller.open_paths([path], play=False)

    def save_playlist(self) -> None:
        playlist_panel = self.panels.get("playlist")
        playlist = playlist_panel.selected_playlist() if playlist_panel else self.controller.active_playlist
        suggested = os.path.join(self._start_dir(), f"{playlist.name}.m3u8")
        path, _ = QFileDialog.getSaveFileName(self, "Save playlist", suggested, PLAYLIST_FILTER)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".m3u8"
        try:
            save_playlist_file(playlist, path)
            self.display.flash(f"Saved {os.path.basename(path)}")
        except Exception as exc:
            self.show_error(f"Could not save the playlist:\n{exc}")

    def new_playlist(self) -> None:
        panel = self.panels.get("playlist")
        if panel is not None:
            self.show_panel("playlist")
            panel.create_playlist()

    def focus_search(self) -> None:
        active = QApplication.activeWindow()
        for name in ("library", "playlist"):
            panel = self.panels.get(name)
            if panel is not None and panel is active:
                panel.focus_search()
                return
        target = "library" if self.panels.get("library") and self.panels["library"].isVisible() else "playlist"
        self.show_panel(target)
        self.panels[target].focus_search()

    def show_error(self, text: str) -> None:
        QMessageBox.warning(self, APP_NAME, text)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>A free, open-source, classic-style desktop music player.<br>"
            "No ads, no accounts, no tracking.</p>"
            "<p>Copyright &copy; 2026 Madhu Kumar and PulseDeck contributors.<br>"
            "PulseDeck's source code is released under the MIT License.</p>"
            "<p>Built with Qt for Python (PySide6, LGPL-3.0), libmpv/FFmpeg (GPL-2.0+), "
            "Mutagen (GPL-2.0+), python-mpv (LGPL-2.1+) and Pillow (MIT-CMU). "
            "See <i>Help &gt; Open-Source Licenses</i> for details.</p>"
            '<p><a href="https://github.com/aboycan/pulse-deck">github.com/aboycan/pulse-deck</a></p>'
            f"<p>Audio engine: {self.controller.engine.backend_name}</p>",
        )

    def show_licenses(self) -> None:
        # Installed builds: the bundled licenses/ folder; source setups: the repository files.
        candidates = [platform.bundle_dir() / "licenses", platform.bundle_dir() / "THIRD_PARTY_LICENSES.md",
                      platform.bundle_dir().parent.parent / "licenses",
                      platform.bundle_dir().parent.parent / "THIRD_PARTY_LICENSES.md"]
        for path in candidates:
            if path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
        QDesktopServices.openUrl(QUrl("https://github.com/aboycan/pulse-deck/blob/main/THIRD_PARTY_LICENSES.md"))
