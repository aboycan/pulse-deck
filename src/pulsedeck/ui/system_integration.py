# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""System tray, desktop notifications and global media keys.

* Tray icon (Windows notification area, macOS menu bar, Linux StatusNotifier/
  XEmbed tray where available) with playback controls.
* Track-change notifications through the tray.
* Media keys:
    - in-app on every platform (Qt delivers media keys to the focused app);
    - Windows: system-wide via ``RegisterHotKey``;
    - Linux: system-wide via an MPRIS D-Bus service, which desktop
      environments use to route media keys;
    - macOS: system-wide via MPRemoteCommandCenter when ``pyobjc`` MediaPlayer
      bindings are present.
Each integration is optional; failures are logged and never fatal.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QAbstractNativeEventFilter, QKeyCombination, QObject, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from pulsedeck import APP_NAME
from pulsedeck.audio.playback_engine import PlaybackState
from pulsedeck.core import platform
from pulsedeck.library.models import TrackInfo

log = logging.getLogger(__name__)


# -- Windows ------------------------------------------------------------------
class _WindowsMediaKeys(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312
    KEYS = {1: 0xB3, 2: 0xB0, 3: 0xB1, 4: 0xB2}  # play/pause, next, prev, stop

    def __init__(self, controller) -> None:  # noqa: ANN001
        super().__init__()
        import ctypes  # noqa: PLC0415

        self.controller = controller
        self.user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self.registered: list[int] = []
        for hotkey_id, vk in self.KEYS.items():
            if self.user32.RegisterHotKey(None, hotkey_id, 0x4000, vk):  # MOD_NOREPEAT
                self.registered.append(hotkey_id)
            else:
                log.info("Media key 0x%X is owned by another application", vk)

    def nativeEventFilter(self, event_type, message):  # noqa: N802,ANN001,ANN201
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            from ctypes import wintypes  # noqa: PLC0415

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam in self.KEYS:
                action = {1: self.controller.toggle_play_pause, 2: self.controller.next_track,
                          3: self.controller.previous_track, 4: self.controller.stop}[msg.wParam]
                action()
                return True, 0
        return False, 0

    def unregister(self) -> None:
        for hotkey_id in self.registered:
            self.user32.UnregisterHotKey(None, hotkey_id)
        self.registered.clear()


# -- Linux (MPRIS) -----------------------------------------------------------
def _start_mpris(controller, window):  # noqa: ANN001,ANN202,C901
    from PySide6.QtCore import ClassInfo, Property, Slot  # noqa: PLC0415
    from PySide6.QtDBus import QDBusAbstractAdaptor, QDBusConnection  # noqa: PLC0415

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None

    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2"})
    class RootAdaptor(QDBusAbstractAdaptor):
        def __init__(self, parent: QObject) -> None:
            super().__init__(parent)
            self.setAutoRelaySignals(True)

        @Slot()
        def Raise(self) -> None:  # noqa: N802
            window.restore_from_tray()

        @Slot()
        def Quit(self) -> None:  # noqa: N802
            window.quit()

        def _identity(self) -> str:
            return APP_NAME

        def _true(self) -> bool:
            return True

        def _false(self) -> bool:
            return False

        def _desktop(self) -> str:
            return "pulsedeck"

        Identity = Property(str, _identity)
        DesktopEntry = Property(str, _desktop)
        CanQuit = Property(bool, _true)
        CanRaise = Property(bool, _true)
        HasTrackList = Property(bool, _false)

    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2.Player"})
    class PlayerAdaptor(QDBusAbstractAdaptor):
        def __init__(self, parent: QObject) -> None:
            super().__init__(parent)
            self.setAutoRelaySignals(True)

        @Slot()
        def PlayPause(self) -> None:  # noqa: N802
            controller.toggle_play_pause()

        @Slot()
        def Play(self) -> None:  # noqa: N802
            controller.play()

        @Slot()
        def Pause(self) -> None:  # noqa: N802
            controller.pause()

        @Slot()
        def Stop(self) -> None:  # noqa: N802
            controller.stop()

        @Slot()
        def Next(self) -> None:  # noqa: N802
            controller.next_track()

        @Slot()
        def Previous(self) -> None:  # noqa: N802
            controller.previous_track()

        def _status(self) -> str:
            return {PlaybackState.PLAYING: "Playing", PlaybackState.PAUSED: "Paused"}.get(controller.state, "Stopped")

        def _true(self) -> bool:
            return True

        PlaybackStatus = Property(str, _status)
        CanPlay = Property(bool, _true)
        CanPause = Property(bool, _true)
        CanGoNext = Property(bool, _true)
        CanGoPrevious = Property(bool, _true)
        CanControl = Property(bool, _true)
        CanSeek = Property(bool, _true)

    holder = QObject()
    RootAdaptor(holder)
    PlayerAdaptor(holder)
    if not bus.registerObject("/org/mpris/MediaPlayer2", holder):
        log.info("MPRIS object registration failed: %s", bus.lastError().message())
        return None
    if not bus.registerService("org.mpris.MediaPlayer2.pulsedeck"):
        log.info("MPRIS service name unavailable: %s", bus.lastError().message())
        return None
    log.info("MPRIS media-key integration active")
    return holder


# -- macOS ----------------------------------------------------------------------
def _start_macos_remote_commands(controller):  # noqa: ANN001,ANN202
    try:
        from MediaPlayer import MPRemoteCommandCenter  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        log.info("pyobjc MediaPlayer bindings not present; media keys work while PulseDeck is focused")
        return None
    center = MPRemoteCommandCenter.sharedCommandCenter()
    handlers = []

    def bind(command, action):  # noqa: ANN001,ANN202
        def handler(_event):  # noqa: ANN001,ANN202
            action()
            return 0  # MPRemoteCommandHandlerStatusSuccess

        command.setEnabled_(True)
        command.addTargetWithHandler_(handler)
        handlers.append(handler)

    bind(center.togglePlayPauseCommand(), controller.toggle_play_pause)
    bind(center.playCommand(), controller.play)
    bind(center.pauseCommand(), controller.pause)
    bind(center.nextTrackCommand(), controller.next_track)
    bind(center.previousTrackCommand(), controller.previous_track)
    bind(center.stopCommand(), controller.stop)
    return handlers


class SystemIntegration(QObject):
    def __init__(self, controller, window, app_icon: QIcon) -> None:  # noqa: ANN001
        super().__init__(window)
        self.controller = controller
        self.window = window
        self.tray: QSystemTrayIcon | None = None
        self.app_icon = app_icon
        self._win_keys: _WindowsMediaKeys | None = None
        self._mpris = None
        self._mac = None

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._create_tray(app_icon)
        else:
            log.info("No system tray available on this desktop")
        window.tray = self.tray
        self._install_in_app_media_keys()
        self._install_global_media_keys()
        controller.track_changed.connect(self._on_track_changed)
        controller.state_changed.connect(lambda _s: self._update_tray_actions())

    def _create_tray(self, app_icon: QIcon) -> None:
        self.tray = QSystemTrayIcon(app_icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        self.show_action = QAction("Show PulseDeck", menu)
        self.show_action.triggered.connect(self.window.restore_from_tray)
        self.play_action = QAction("Play", menu)
        self.play_action.triggered.connect(self.controller.toggle_play_pause)
        prev_action = QAction("Previous", menu)
        prev_action.triggered.connect(self.controller.previous_track)
        next_action = QAction("Next", menu)
        next_action.triggered.connect(self.controller.next_track)
        stop_action = QAction("Stop", menu)
        stop_action.triggered.connect(self.controller.stop)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.window.quit)
        for action in (self.show_action, None, self.play_action, prev_action, next_action, stop_action, None,
                       quit_action):
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if platform.IS_MACOS:
                return  # the menu opens on click in the macOS menu bar
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide_to_tray()
            else:
                self.window.restore_from_tray()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.controller.toggle_play_pause()

    def _update_tray_actions(self) -> None:
        if self.tray is None:
            return
        playing = self.controller.state is PlaybackState.PLAYING
        self.play_action.setText("Pause" if playing else "Play")

    def _on_track_changed(self, info: TrackInfo | None) -> None:
        if self.tray is None:
            return
        if info is None:
            self.tray.setToolTip(APP_NAME)
            return
        text = f"{info.display_title}\n{info.display_artist}"
        self.tray.setToolTip(f"{APP_NAME}\n{text}")
        app = QApplication.instance()
        focused = app is not None and app.activeWindow() is not None
        if self.controller.config.get("general.notifications") and not focused:
            body = info.display_artist + (f" — {info.album}" if info.album else "")
            self.tray.showMessage(info.display_title, body, self._notification_icon(info), 4000)

    def _notification_icon(self, info: TrackInfo) -> QIcon:
        """Album artwork when the file has some, otherwise the PulseDeck icon (never the generic info icon)."""
        try:
            thumb = self.controller.artwork.thumbnail(info.path, 128)
        except Exception:
            thumb = None
        if thumb is not None:
            icon = QIcon(str(thumb))
            if not icon.isNull():
                return icon
        return self.app_icon

    def _install_in_app_media_keys(self) -> None:
        c = self.controller
        for key, action in ((Qt.Key.Key_MediaPlay, c.toggle_play_pause), (Qt.Key.Key_MediaTogglePlayPause,
                            c.toggle_play_pause), (Qt.Key.Key_MediaPause, c.pause), (Qt.Key.Key_MediaStop, c.stop),
                            (Qt.Key.Key_MediaNext, c.next_track), (Qt.Key.Key_MediaPrevious, c.previous_track)):
            shortcut = QShortcut(QKeySequence(QKeyCombination(key)), self.window)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(action)

    def _install_global_media_keys(self) -> None:
        try:
            if platform.IS_WINDOWS:
                self._win_keys = _WindowsMediaKeys(self.controller)
                QApplication.instance().installNativeEventFilter(self._win_keys)
            elif platform.IS_LINUX:
                self._mpris = _start_mpris(self.controller, self.window)
            elif platform.IS_MACOS:
                self._mac = _start_macos_remote_commands(self.controller)
        except Exception:
            log.warning("Global media keys unavailable", exc_info=True)

    def shutdown(self) -> None:
        if self._win_keys is not None:
            self._win_keys.unregister()
        if self.tray is not None:
            self.tray.hide()
