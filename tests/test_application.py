# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Controller and GUI smoke tests (need PySide6; run offscreen in CI)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pulsedeck.audio.backend import SimulatedBackend  # noqa: E402
from pulsedeck.audio.playback_engine import PlaybackState  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(controller, rounds: int = 5) -> None:  # noqa: ANN001
    for _ in range(rounds):
        controller.engine.wait_idle()
        QCoreApplication.processEvents()


@pytest.fixture
def controller(qapp, tmp_path):
    from pulsedeck.application import AppController
    from pulsedeck.core.configuration import Configuration

    backends: list[SimulatedBackend] = []

    def factory(callbacks):  # noqa: ANN001,ANN202
        backend = SimulatedBackend(default_duration=10.0, callbacks=callbacks)
        backends.append(backend)
        return backend

    config = Configuration(tmp_path / "settings.json")
    c = AppController(config=config, backend_factory=factory)
    c.test_backends = backends
    yield c
    c.shutdown()


@pytest.fixture
def songs(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / "music" / f"{i:02d}.mp3"
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(b"\0")
        paths.append(str(p))
    return paths


def test_open_play_next_previous(controller, songs):
    controller.open_paths(songs, play=True)
    pump(controller)
    assert controller.state is PlaybackState.PLAYING
    assert controller.current_index == 0
    controller.next_track()
    pump(controller)
    assert controller.current_index == 1
    controller.previous_track()
    pump(controller)
    assert controller.current_index == 0
    controller.toggle_play_pause()
    pump(controller)
    assert controller.state is PlaybackState.PAUSED
    controller.stop()
    pump(controller)
    assert controller.state is PlaybackState.STOPPED


def test_volume_and_modes_persist_in_config(controller):
    controller.set_volume(42)
    controller.set_shuffle(True)
    controller.cycle_repeat()
    assert controller.config.get("audio.volume") == 42
    assert controller.config.get("playback.shuffle") is True
    assert controller.config.get("playback.repeat") == "all"


def test_auto_advance_through_playlist(controller, songs):
    controller.open_paths(songs, play=True)
    pump(controller)
    controller.test_backends[0].advance(10.0)
    pump(controller)
    assert controller.current_index == 1


def test_missing_file_is_skipped(controller, songs):
    os.remove(songs[0])
    controller.open_paths([os.path.dirname(songs[1])], play=False)
    controller.active_playlist.add(controller._entries_for([songs[0]]), 0)  # noqa: SLF001
    controller.playlist_edited(controller.active_playlist.id)
    controller.play_index(0)
    pump(controller, 10)
    assert controller.current_index == 1


def test_session_restore(controller, songs, qapp, tmp_path):
    from pulsedeck.application import AppController

    controller.open_paths(songs, play=True)
    pump(controller)
    controller.next_track()
    pump(controller)
    controller.seek(4.0)
    pump(controller)
    controller.save_session()
    restored = AppController(config=controller.config, backend_factory=lambda cb: SimulatedBackend(
        default_duration=10.0, callbacks=cb), playlist_manager=controller.playlists,
        session_store=controller.session_store)
    try:
        restored.restore_session()
        pump(restored)
        assert restored.current_index == 1
        assert restored.position == pytest.approx(4.0)
        assert restored.state is PlaybackState.PAUSED
    finally:
        restored.engine.shutdown()


def test_all_windows_construct_offscreen(controller, songs):
    from pulsedeck.ui.equalizer_window import EqualizerWindow
    from pulsedeck.ui.info_window import InfoWindow
    from pulsedeck.ui.library_window import LibraryWindow
    from pulsedeck.ui.main_window import MainWindow
    from pulsedeck.ui.playlist_window import PlaylistWindow
    from pulsedeck.ui.settings_window import SettingsWindow
    from pulsedeck.ui.system_integration import SystemIntegration
    from pulsedeck.ui.theme import available_themes

    window = MainWindow(controller)
    panels = {
        "playlist": PlaylistWindow(controller, window),
        "equalizer": EqualizerWindow(controller, window),
        "library": LibraryWindow(controller, window),
        "info": InfoWindow(controller, window),
        "settings": SettingsWindow(controller, lambda: None, window),
    }
    for name, panel in panels.items():
        window.register_panel(name, panel)
    for theme in available_themes().values():
        window.apply_theme(theme)
        panels["playlist"].apply_theme(theme)
    SystemIntegration(controller, window, window.windowIcon())
    window.show()
    for panel in panels.values():
        panel.show()
    controller.open_paths(songs, play=True)
    pump(controller)
    QCoreApplication.processEvents()
    assert panels["playlist"].model.rowCount() == 3
    # Equalizer slider -> controller state
    panels["equalizer"].bands[1].slider.setValue(60)
    assert controller.eq.gains[1] == pytest.approx(6.0)
    window.set_compact(True)
    window.set_always_on_top(True)
    for panel in panels.values():
        panel.close()
    window.quit()
