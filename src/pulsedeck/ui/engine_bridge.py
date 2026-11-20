# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Marshal engine callbacks (worker thread) onto the Qt GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from pulsedeck.audio.backend import AudioParams
from pulsedeck.audio.playback_engine import EngineListener, PlaybackState


class EngineBridge(QObject, EngineListener):
    # Signals emitted from the engine thread are delivered through queued
    # connections, so slots always run on the GUI thread.
    state_changed = Signal(str)
    track_started = Signal(str, bool)
    track_finished = Signal()
    position_changed = Signal(float, float)
    audio_params_changed = Signal(object)
    error = Signal(str, str)

    def on_state_changed(self, state: PlaybackState) -> None:
        self.state_changed.emit(state.value)

    def on_track_started(self, path: str, auto: bool) -> None:
        self.track_started.emit(path, auto)

    def on_track_finished(self) -> None:
        self.track_finished.emit()

    def on_position(self, position: float, duration: float) -> None:
        self.position_changed.emit(position, duration)

    def on_audio_params(self, params: AudioParams) -> None:
        self.audio_params_changed.emit(params)

    def on_error(self, path: str, message: str) -> None:
        self.error.emit(path, message)
