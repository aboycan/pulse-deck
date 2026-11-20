# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Audio backend interface and a dependency-free fallback backend.

:class:`AudioBackend` is what the :class:`~pulsedeck.audio.playback_engine.PlaybackEngine`
drives. The production implementation is
:class:`~pulsedeck.audio.mpv_backend.MpvBackend`. :class:`SimulatedBackend`
models playback with a virtual clock; it is used by the test-suite and as a
silent fallback so the UI still opens if libmpv cannot be loaded.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class AudioParams:
    codec: str = ""
    bitrate: int = 0
    sample_rate: int = 0
    channels: int = 0
    output_sample_rate: int = 0


@dataclass
class BackendCallbacks:
    #: Playback reached the end of the file and nothing was queued.
    on_end: Callable[[], None] = lambda: None
    #: The backend moved on to the pre-queued (gapless) file by itself.
    on_auto_advance: Callable[[str], None] = lambda path: None
    #: A file failed to open or decode.
    on_error: Callable[[str, str], None] = lambda path, message: None
    #: A file was opened and is about to produce audio.
    on_loaded: Callable[[str], None] = lambda path: None


class AudioBackend:
    """Interface for a single audio player instance."""

    name = "abstract"
    callbacks: BackendCallbacks

    def load(self, path: str, start: float = 0.0, paused: bool = False) -> None:
        raise NotImplementedError

    def set_next(self, path: str | None) -> None:
        """Queue ``path`` for gapless playback after the current file."""
        raise NotImplementedError

    def play(self) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def seek(self, seconds: float) -> None:
        raise NotImplementedError

    @property
    def position(self) -> float:
        raise NotImplementedError

    @property
    def duration(self) -> float:
        raise NotImplementedError

    @property
    def is_idle(self) -> bool:
        raise NotImplementedError

    def set_volume(self, volume: float) -> None:
        """Volume on the 0-100 scale (cubic, like libmpv)."""
        raise NotImplementedError

    def set_muted(self, muted: bool) -> None:
        raise NotImplementedError

    def set_speed(self, speed: float) -> None:
        raise NotImplementedError

    def set_filters(self, af: str) -> None:
        raise NotImplementedError

    def filter_command(self, label: str, command: str, argument: str) -> bool:
        raise NotImplementedError

    def set_replaygain(self, mode: str, preamp: float) -> None:
        raise NotImplementedError

    def audio_params(self) -> AudioParams:
        raise NotImplementedError

    def devices(self) -> list[tuple[str, str]]:
        return [("auto", "System default")]

    def set_device(self, name: str) -> None:
        pass

    def set_gapless(self, enabled: bool) -> None:
        pass

    def shutdown(self) -> None:
        pass


@dataclass
class _SimFile:
    path: str
    duration: float


@dataclass
class SimulatedBackend(AudioBackend):
    """Virtual-clock backend: deterministic and needs no audio hardware.

    Time only moves when :meth:`advance` is called, which makes playback
    logic testable without sleeping.
    """

    durations: dict[str, float] = field(default_factory=dict)
    default_duration: float = 180.0
    fail_paths: set[str] = field(default_factory=set)
    callbacks: BackendCallbacks = field(default_factory=BackendCallbacks)

    def __post_init__(self) -> None:
        self.name = "simulated"
        self._lock = threading.RLock()
        self._file: _SimFile | None = None
        self._next: str | None = None
        self._pos = 0.0
        self._paused = True
        self.volume = 100.0
        self.muted = False
        self.speed = 1.0
        self.af = ""
        self.commands: list[tuple[str, str, str]] = []
        self.replaygain = ("no", 0.0)
        self.device = "auto"
        self.gapless = True

    def _open(self, path: str) -> _SimFile | None:
        if path in self.fail_paths or not os.path.exists(path):
            self.callbacks.on_error(path, "File not found" if not os.path.exists(path) else "Cannot decode file")
            return None
        return _SimFile(path, self.durations.get(path, self.default_duration))

    def load(self, path: str, start: float = 0.0, paused: bool = False) -> None:
        with self._lock:
            self._next = None
            opened = self._open(path)
            self._file = opened
            if opened is None:
                self._paused = True
                self._pos = 0.0
                return
            self._pos = max(0.0, min(start, opened.duration))
            self._paused = paused
        self.callbacks.on_loaded(path)

    def set_next(self, path: str | None) -> None:
        with self._lock:
            self._next = path

    def play(self) -> None:
        with self._lock:
            if self._file:
                self._paused = False

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def stop(self) -> None:
        with self._lock:
            self._file = None
            self._next = None
            self._pos = 0.0
            self._paused = True

    def seek(self, seconds: float) -> None:
        with self._lock:
            if self._file:
                self._pos = max(0.0, min(seconds, self._file.duration))

    @property
    def position(self) -> float:
        return self._pos

    @property
    def duration(self) -> float:
        return self._file.duration if self._file else 0.0

    @property
    def is_idle(self) -> bool:
        return self._file is None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def current_path(self) -> str | None:
        return self._file.path if self._file else None

    def set_volume(self, volume: float) -> None:
        self.volume = float(volume)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def set_filters(self, af: str) -> None:
        self.af = af

    def filter_command(self, label: str, command: str, argument: str) -> bool:
        self.commands.append((label, command, argument))
        return True

    def set_replaygain(self, mode: str, preamp: float) -> None:
        self.replaygain = (mode, preamp)

    def audio_params(self) -> AudioParams:
        if not self._file:
            return AudioParams()
        return AudioParams(codec="sim", bitrate=320_000, sample_rate=44_100, channels=2, output_sample_rate=44_100)

    def set_device(self, name: str) -> None:
        self.device = name

    def set_gapless(self, enabled: bool) -> None:
        self.gapless = enabled

    # -- simulation ------------------------------------------------------
    def advance(self, seconds: float) -> None:
        """Move the virtual clock forward, firing end/advance callbacks."""
        remaining = seconds
        while remaining > 0:
            with self._lock:
                if self._file is None or self._paused:
                    return
                left = self._file.duration - self._pos
                step = min(remaining, left / max(self.speed, 1e-6))
                self._pos += step * self.speed
                remaining -= step
                finished = self._pos >= self._file.duration - 1e-9
                nxt = self._next
            if not finished:
                return
            if nxt is not None:
                with self._lock:
                    self._next = None
                    opened = self._open(nxt)
                    self._file = opened
                    self._pos = 0.0
                if opened is None:
                    self.callbacks.on_end()
                    return
                self.callbacks.on_auto_advance(nxt)
            else:
                with self._lock:
                    self._file = None
                    self._paused = True
                self.callbacks.on_end()
                return
