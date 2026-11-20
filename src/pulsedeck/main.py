# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""PulseDeck entry point."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys

from pulsedeck import APP_ID, APP_NAME, ORG_NAME, __version__
from pulsedeck.core import platform
from pulsedeck.core.logging_setup import setup_logging

log = logging.getLogger("pulsedeck")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pulsedeck", description=f"{APP_NAME} music player")
    parser.add_argument("paths", nargs="*", help="audio files, folders or playlists to open")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--new-instance", action="store_true", help="do not hand files to a running instance")
    parser.add_argument("--reset-settings", action="store_true", help="start with default settings")
    parser.add_argument("--self-test", action="store_true",
                        help="check that the bundled Qt, libmpv, Mutagen and Pillow load, then exit")
    # PyInstaller/macOS may pass -psn_... arguments; ignore unknown ones.
    args, _unknown = parser.parse_known_args(argv)
    return args


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"pulsedeck-{user}"


def _send_to_running_instance(paths: list[str]) -> bool:
    from PySide6.QtNetwork import QLocalSocket  # noqa: PLC0415

    socket = QLocalSocket()
    socket.connectToServer(_server_name())
    if not socket.waitForConnected(300):
        return False
    payload = json.dumps({"paths": [os.path.abspath(p) for p in paths]}).encode("utf-8")
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def _start_instance_server(on_paths):  # noqa: ANN001,ANN202
    from PySide6.QtNetwork import QLocalServer  # noqa: PLC0415

    server = QLocalServer()
    QLocalServer.removeServer(_server_name())  # clean up after a crash
    if not server.listen(_server_name()):
        log.info("Single-instance server unavailable: %s", server.errorString())
        return None

    def on_connection() -> None:
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read() -> None:
            try:
                data = json.loads(bytes(sock.readAll()).decode("utf-8") or "{}")
            except ValueError:
                data = {}
            on_paths(data.get("paths", []))

        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(on_connection)
    return server


def _app_icon():  # noqa: ANN202
    from PySide6.QtGui import QIcon  # noqa: PLC0415

    icon = QIcon()
    icon_dir = platform.assets_dir() / "icons"
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        path = icon_dir / f"pulsedeck-{size}.png"
        if path.exists():
            icon.addFile(str(path))
    return icon


def self_test() -> int:
    """Used by the build scripts to verify a frozen bundle is complete."""
    problems: list[str] = []
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401,PLC0415
    except Exception as exc:
        problems.append(f"Qt: {exc}")
    try:
        import mutagen  # noqa: F401,PLC0415
        import PIL.Image  # noqa: F401,PLC0415
    except Exception as exc:
        problems.append(f"Python libraries: {exc}")
    try:
        from pulsedeck.audio.mpv_backend import MpvBackend  # noqa: PLC0415

        MpvBackend(audio_output="null").shutdown()
    except Exception as exc:
        problems.append(f"libmpv: {exc}")
    for problem in problems:
        log.error("self-test: %s", problem)
    log.info("self-test %s", "FAILED" if problems else "passed")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging(logging.DEBUG if args.debug else logging.INFO)
    if args.self_test:
        return self_test()
    log.info("%s %s starting on %s (Python %s)", APP_NAME, __version__, platform.platform_name(),
             sys.version.split()[0])

    try:
        from PySide6.QtCore import QEvent, QTimer  # noqa: PLC0415
        from PySide6.QtGui import QFileOpenEvent  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        print(f"PySide6 is required: {exc}", file=sys.stderr)
        return 1

    pending_open: list[str] = []

    class PulseDeckApplication(QApplication):
        def event(self, e: QEvent) -> bool:
            if e.type() == QEvent.Type.FileOpen:  # macOS: Finder "Open With" / dock drops
                path = e.file() if isinstance(e, QFileOpenEvent) else ""
                if path:
                    pending_open.append(path)
                QTimer.singleShot(0, flush_pending)
                return True
            return super().event(e)

    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setDesktopFileName("pulsedeck")
    if platform.IS_WINDOWS:
        try:
            import ctypes  # noqa: PLC0415

            # Register "PulseDeck" as the display name first so notifications are
            # titled "PulseDeck" rather than the raw app ID.
            platform.register_windows_app_identity(APP_ID, APP_NAME,
                                                   platform.assets_dir() / "icons" / "pulsedeck-256.png")
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # type: ignore[attr-defined]
        except Exception:
            pass

    app = PulseDeckApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    from pulsedeck.core.configuration import Configuration  # noqa: PLC0415

    config = Configuration()
    if args.reset_settings:
        config.save()
    config.load()

    if config.get("general.single_instance", True) and not args.new_instance and _send_to_running_instance(args.paths):
        log.info("Handed over to the running instance")
        return 0

    from pulsedeck.application import AppController  # noqa: PLC0415
    from pulsedeck.ui import icons  # noqa: PLC0415
    from pulsedeck.ui.equalizer_window import EqualizerWindow  # noqa: PLC0415
    from pulsedeck.ui.info_window import InfoWindow  # noqa: PLC0415
    from pulsedeck.ui.library_window import LibraryWindow  # noqa: PLC0415
    from pulsedeck.ui.main_window import MainWindow  # noqa: PLC0415
    from pulsedeck.ui.playlist_window import PlaylistWindow  # noqa: PLC0415
    from pulsedeck.ui.settings_window import SettingsWindow  # noqa: PLC0415
    from pulsedeck.ui.system_integration import SystemIntegration  # noqa: PLC0415
    from pulsedeck.ui.theme import ThemeError, build_stylesheet, get_theme, with_accent  # noqa: PLC0415

    try:
        controller = AppController(config=config)
    except Exception as exc:
        log.exception("Startup failed")
        QMessageBox.critical(None, APP_NAME, f"{APP_NAME} could not start:\n\n{exc}")
        return 1

    app_icon = _app_icon()
    app.setWindowIcon(app_icon)
    window = MainWindow(controller)
    playlist_window = PlaylistWindow(controller, window)
    eq_window = EqualizerWindow(controller, window)
    library_window = LibraryWindow(controller, window)
    info_window = InfoWindow(controller, window)

    def apply_theme() -> None:
        try:
            theme = get_theme(config.get("interface.theme", "classic_dark"))
        except ThemeError as exc:
            log.error("%s", exc)
            return
        theme = with_accent(theme, config.get("interface.accent_color"))
        icons.clear_cache()
        app.setStyleSheet(build_stylesheet(theme, int(config.get("interface.font_size", 10))))
        window.apply_theme(theme)
        playlist_window.apply_theme(theme)

    settings_window = SettingsWindow(controller, apply_theme, window)
    for name, panel in (("playlist", playlist_window), ("equalizer", eq_window), ("library", library_window),
                        ("info", info_window), ("settings", settings_window)):
        window.register_panel(name, panel)
    apply_theme()
    integration = SystemIntegration(controller, window, app_icon)

    def flush_pending() -> None:
        if pending_open:
            paths = list(pending_open)
            pending_open.clear()
            controller.open_paths(paths, play=True)

    def open_from_other_instance(paths: list[str]) -> None:
        window.restore_from_tray()
        if paths:
            controller.open_paths(paths, play=True)

    server = _start_instance_server(open_from_other_instance) if config.get("general.single_instance", True) else None

    restoring = config.get("general.startup") != "empty" and config.get("general.restore_session", True)
    if restoring:
        controller.restore_session()
    else:
        # Without session restore, start from the user's default equalizer preset.
        preset = controller.presets.get(config.get("equalizer.default_preset", "Flat"))
        if preset:
            controller.eq.apply_preset(preset)
            controller.apply_equalizer()
    window.show()
    window.restore_panels()
    if args.paths:
        controller.open_paths(args.paths, play=True)
    controller.startup_tasks()
    if controller.audio_error:
        QTimer.singleShot(300, lambda: QMessageBox.warning(window, APP_NAME, controller.audio_error))

    def on_quit() -> None:
        integration.shutdown()
        if server is not None:
            server.close()
        controller.shutdown()

    app.aboutToQuit.connect(on_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
