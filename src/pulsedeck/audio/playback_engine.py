# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""High-level playback engine.

The engine owns one or two :class:`AudioBackend` instances (two only while a
crossfade is running) and a single worker thread. Every public method just
posts work to that thread, so callers - the Qt UI in particular - never block
on audio I/O and all backend access is serialised.

Listeners receive callbacks on the worker thread; the UI layer marshals them
to the GUI thread (see :mod:`pulsedeck.ui.engine_bridge`).
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Callable
from enum import Enum

from pulsedeck.audio.audio_filters import (
    DspSettings,
    build_chain,
    chain_structure,
    live_update_commands,
    mpv_af_string,
)
from pulsedeck.audio.backend import AudioBackend, AudioParams, BackendCallbacks
from pulsedeck.audio.equalizer import EqualizerState

log = logging.getLogger(__name__)

TICK_SECONDS = 0.025
#: Largest per-tick EQ gain change; larger moves are ramped over several
#: ticks to avoid zipper noise and clicks.
EQ_RAMP_STEP_DB = 1.0


class PlaybackState(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class EngineListener:
    """Override the hooks you need. All are called from the engine thread."""

    def on_state_changed(self, state: PlaybackState) -> None: ...
    def on_track_started(self, path: str, auto: bool) -> None: ...
    def on_track_finished(self) -> None: ...
    def on_position(self, position: float, duration: float) -> None: ...
    def on_audio_params(self, params: AudioParams) -> None: ...
    def on_error(self, path: str, message: str) -> None: ...


BackendFactory = Callable[[BackendCallbacks], AudioBackend]


class PlaybackEngine:
    def __init__(self, backend_factory: BackendFactory, listener: EngineListener | None = None,
                 threaded: bool = True) -> None:
        self._factory = backend_factory
        self.listener = listener or EngineListener()
        self.next_provider: Callable[[], str | None] = lambda: None

        self._primary = self._make_backend()
        self._secondary: AudioBackend | None = None

        self.state = PlaybackState.STOPPED
        self.current_path: str | None = None
        self._volume = 80.0
        self._muted = False
        self._speed = 1.0
        self._crossfade = 0.0
        self._gapless = True
        self._balance = 0.0
        self._normalization = False
        self._clip_protection = True
        self._replaygain = ("off", 0.0)
        self._device = "auto"

        self._eq_target = EqualizerState()
        self._eq_applied = EqualizerState()
        self._chain_labels: tuple[str, ...] = ()
        self._af = ""

        self._fade: dict | None = None
        self._last_params = AudioParams()
        self._tick_count = 0

        self._threaded = threaded
        self._tasks: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._running = True
        self._worker: threading.Thread | None = None
        if threaded:
            self._worker = threading.Thread(target=self._run, name="pulsedeck-engine", daemon=True)
            self._worker.start()
        self._apply_filters(force=True)

    # -- threading -------------------------------------------------------
    def _make_backend(self) -> AudioBackend:
        callbacks = BackendCallbacks(
            on_end=lambda: self._post(self._handle_end),
            on_auto_advance=lambda path: self._post(lambda: self._handle_auto_advance(path)),
            on_error=lambda path, msg: self._post(lambda: self._handle_error(path, msg)),
            on_loaded=lambda path: None,
        )
        return self._factory(callbacks)

    def _post(self, task: Callable[[], None]) -> None:
        if not self._running:
            return
        if self._threaded:
            self._tasks.put(task)
        else:
            self._safe(task)

    def _safe(self, task: Callable[[], None]) -> None:
        try:
            task()
        except Exception:
            log.exception("Engine task failed")

    def _run(self) -> None:
        next_tick = time.monotonic()
        while self._running:
            timeout = max(0.0, next_tick - time.monotonic())
            try:
                task = self._tasks.get(timeout=timeout)
            except queue.Empty:
                task = None
                next_tick = time.monotonic() + TICK_SECONDS
                self._safe(self.tick)
                continue
            if task is None:
                break
            self._safe(task)
            self._tasks.task_done()

    def wait_idle(self, timeout: float = 5.0) -> None:
        """Block until queued commands have run (tests and shutdown)."""
        if not self._threaded:
            return
        done = threading.Event()
        self._tasks.put(done.set)
        done.wait(timeout)

    def shutdown(self) -> None:
        if not self._running:
            return
        if self._threaded:
            self.wait_idle(2.0)
        self._running = False
        if self._threaded:
            self._tasks.put(None)
            if self._worker:
                self._worker.join(2.0)
        for backend in (self._primary, self._secondary):
            if backend is not None:
                try:
                    backend.stop()
                    backend.shutdown()
                except Exception:
                    log.debug("backend shutdown failed", exc_info=True)

    # -- public API (thread-safe, asynchronous) --------------------------
    def play_file(self, path: str, start: float = 0.0, paused: bool = False) -> None:
        self._post(lambda: self._do_play_file(path, start, paused))

    def play(self) -> None:
        self._post(self._do_play)

    def pause(self) -> None:
        self._post(self._do_pause)

    def toggle_pause(self) -> None:
        self._post(lambda: self._do_pause() if self.state is PlaybackState.PLAYING else self._do_play())

    def stop(self) -> None:
        self._post(self._do_stop)

    def seek(self, seconds: float, relative: bool = False) -> None:
        def task() -> None:
            if self.current_path is None:
                return
            self._cancel_fade(finish=True)
            target = self._primary.position + seconds if relative else seconds
            duration = self._primary.duration
            if duration > 0:
                target = min(target, max(0.0, duration - 0.05))
            self._primary.seek(max(0.0, target))
            self._emit_position()
        self._post(task)

    def set_volume(self, volume: float) -> None:
        def task() -> None:
            self._volume = max(0.0, min(100.0, float(volume)))
            if self._fade is None:
                self._primary.set_volume(self._volume)
        self._post(task)

    def set_muted(self, muted: bool) -> None:
        def task() -> None:
            self._muted = bool(muted)
            for backend in self._backends():
                backend.set_muted(self._muted)
        self._post(task)

    def set_speed(self, speed: float) -> None:
        def task() -> None:
            self._speed = max(0.25, min(4.0, float(speed)))
            for backend in self._backends():
                backend.set_speed(self._speed)
        self._post(task)

    def set_balance(self, balance: float) -> None:
        def task() -> None:
            self._balance = max(-1.0, min(1.0, float(balance)))
            self._apply_filters()
        self._post(task)

    def set_normalization(self, enabled: bool) -> None:
        def task() -> None:
            self._normalization = bool(enabled)
            self._apply_filters()
        self._post(task)

    def set_clip_protection(self, enabled: bool) -> None:
        def task() -> None:
            self._clip_protection = bool(enabled)
            self._apply_filters()
        self._post(task)

    def set_replaygain(self, mode: str, preamp: float = 0.0) -> None:
        def task() -> None:
            self._replaygain = (mode, float(preamp))
            for backend in self._backends():
                backend.set_replaygain(mode, float(preamp))
        self._post(task)

    def set_equalizer(self, state: EqualizerState) -> None:
        snapshot = EqualizerState.from_config(state.to_config())

        def task() -> None:
            self._eq_target = snapshot
            self._apply_filters()
        self._post(task)

    def set_crossfade(self, seconds: float) -> None:
        def task() -> None:
            self._crossfade = max(0.0, min(12.0, float(seconds)))
            self._refresh_next()
        self._post(task)

    def set_gapless(self, enabled: bool) -> None:
        def task() -> None:
            self._gapless = bool(enabled)
            for backend in self._backends():
                backend.set_gapless(self._gapless)
            self._refresh_next()
        self._post(task)

    def set_device(self, name: str) -> None:
        def task() -> None:
            self._device = name or "auto"
            for backend in self._backends():
                backend.set_device(self._device)
        self._post(task)

    def refresh_next(self) -> None:
        """Call after the play queue changed so the gapless pre-load is updated."""
        self._post(self._refresh_next)

    def devices(self) -> list[tuple[str, str]]:
        try:
            return self._primary.devices()
        except Exception:
            return [("auto", "System default")]

    @property
    def position(self) -> float:
        return self._primary.position if self.current_path else 0.0

    @property
    def duration(self) -> float:
        return self._primary.duration if self.current_path else 0.0

    @property
    def backend_name(self) -> str:
        return self._primary.name

    # -- implementation (engine thread) ----------------------------------
    def _backends(self) -> list[AudioBackend]:
        return [b for b in (self._primary, self._secondary) if b is not None]

    def _set_state(self, state: PlaybackState) -> None:
        if state is not self.state:
            self.state = state
            self.listener.on_state_changed(state)

    def _configure(self, backend: AudioBackend) -> None:
        backend.set_muted(self._muted)
        backend.set_speed(self._speed)
        backend.set_replaygain(*self._replaygain)
        backend.set_device(self._device)
        backend.set_gapless(self._gapless)
        backend.set_filters(self._af)

    def _do_play_file(self, path: str, start: float, paused: bool) -> None:
        self._cancel_fade(finish=False)
        self.current_path = path
        self._primary.set_volume(self._volume)
        self._primary.load(path, start=start, paused=paused)
        if self.current_path is None:  # load failed synchronously (error handler ran)
            return
        self._set_state(PlaybackState.PAUSED if paused else PlaybackState.PLAYING)
        self.listener.on_track_started(path, False)
        self._refresh_next()

    def _do_play(self) -> None:
        if self.current_path is None:
            return
        self._primary.play()
        if self._fade and self._secondary:
            self._secondary.play()
        self._set_state(PlaybackState.PLAYING)

    def _do_pause(self) -> None:
        if self.current_path is None:
            return
        self._primary.pause()
        if self._secondary:
            self._secondary.pause()
        self._set_state(PlaybackState.PAUSED)

    def _do_stop(self) -> None:
        self._cancel_fade(finish=False)
        self._primary.stop()
        self.current_path = None
        self._set_state(PlaybackState.STOPPED)
        self.listener.on_position(0.0, 0.0)

    def _refresh_next(self) -> None:
        if self.current_path is None:
            return
        use_gapless = self._gapless and self._crossfade <= 0
        nxt = self.next_provider() if use_gapless else None
        self._primary.set_next(nxt)

    def _handle_auto_advance(self, path: str) -> None:
        self.current_path = path
        self.listener.on_track_started(path, True)
        self._refresh_next()

    def _handle_end(self) -> None:
        if self._fade is not None:
            return  # the outgoing track of a crossfade ended; tick() swaps
        self.current_path = None
        self._set_state(PlaybackState.STOPPED)
        self.listener.on_track_finished()

    def _handle_error(self, path: str, message: str) -> None:
        log.warning("Playback error for %s: %s", path, message)
        if self._fade is not None and self._secondary is not None:
            self._cancel_fade(finish=False)
        if path == self.current_path or self.current_path is None:
            self.current_path = None
            self._set_state(PlaybackState.STOPPED)
        self.listener.on_error(path, message)

    # -- filters ---------------------------------------------------------
    def _apply_filters(self, force: bool = False) -> None:
        settings = DspSettings(self._eq_target, self._balance, self._normalization, self._clip_protection)
        chain = build_chain(settings)
        labels = chain_structure(chain)
        if force or labels != self._chain_labels or not self._eq_target.active:
            self._chain_labels = labels
            self._eq_applied = EqualizerState.from_config(self._eq_target.to_config())
            self._af = mpv_af_string(chain)
            for backend in self._backends():
                backend.set_filters(self._af)
            return
        # Same structure: ramp values in place on subsequent ticks.
        settings_now = DspSettings(self._eq_applied, self._balance, self._normalization, self._clip_protection)
        self._af = mpv_af_string(build_chain(settings_now))
        self._step_eq_ramp()

    def _step_eq_ramp(self) -> None:
        current = self._eq_applied
        target = self._eq_target
        if current.gains == target.gains and current.effective_preamp == target.effective_preamp:
            return
        stepped = EqualizerState.from_config(target.to_config())
        stepped.gains = [
            c + max(-EQ_RAMP_STEP_DB, min(EQ_RAMP_STEP_DB, t - c))
            for c, t in zip(current.gains, target.gains, strict=True)
        ]
        stepped.gains = [round(g, 2) for g in stepped.gains]
        # Move preamp proportionally (it compensates for the boosts).
        delta_pre = target.preamp - current.preamp
        stepped.preamp = round(current.preamp + max(-EQ_RAMP_STEP_DB, min(EQ_RAMP_STEP_DB, delta_pre)), 2)
        for label, command, argument in live_update_commands(current, stepped):
            for backend in self._backends():
                if not backend.filter_command(label, command, argument):
                    # Fall back to rebuilding the chain if commands are unsupported.
                    self._apply_filters(force=True)
                    return
        self._eq_applied = stepped
        self._af = mpv_af_string(build_chain(DspSettings(stepped, self._balance, self._normalization,
                                                         self._clip_protection)))

    @property
    def equalizer_applied(self) -> EqualizerState:
        return self._eq_applied

    @property
    def filter_string(self) -> str:
        return self._af

    # -- periodic work ---------------------------------------------------
    def tick(self) -> None:
        self._tick_count += 1
        self._step_eq_ramp()
        if self.current_path is None:
            return
        self._update_crossfade()
        if self._tick_count % 4 == 0:  # ~10 Hz is plenty for the UI
            self._emit_position()
        if self._tick_count % 40 == 0:
            params = self._primary.audio_params()
            if params != self._last_params:
                self._last_params = params
                self.listener.on_audio_params(params)

    def _emit_position(self) -> None:
        self.listener.on_position(self._primary.position, self._primary.duration)

    # -- crossfade -------------------------------------------------------
    def _update_crossfade(self) -> None:
        if self._fade is not None:
            self._advance_fade()
            return
        if self._crossfade <= 0 or self.state is not PlaybackState.PLAYING:
            return
        duration = self._primary.duration
        position = self._primary.position
        if duration <= 2 * self._crossfade or duration - position > self._crossfade:
            return
        nxt = self.next_provider()
        if not nxt:
            return
        if self._secondary is None:
            self._secondary = self._make_backend()
        self._configure(self._secondary)
        self._secondary.set_volume(0.0)
        self._secondary.load(nxt, start=0.0, paused=False)
        self._fade = {"start": time.monotonic(), "length": max(0.1, duration - position), "path": nxt}

    def _advance_fade(self) -> None:
        fade = self._fade
        assert fade is not None and self._secondary is not None
        if self.state is PlaybackState.PAUSED:
            fade["start"] += TICK_SECONDS
            return
        progress = min(1.0, (time.monotonic() - fade["start"]) / fade["length"])
        # Equal-power curve; backend volume is cubic, so take cube roots.
        out_gain = math.cos(progress * math.pi / 2)
        in_gain = math.sin(progress * math.pi / 2)
        self._primary.set_volume(self._volume * out_gain ** (1 / 3))
        self._secondary.set_volume(self._volume * in_gain ** (1 / 3))
        if progress >= 1.0 or self._primary.is_idle:
            self._cancel_fade(finish=True)

    def _cancel_fade(self, finish: bool) -> None:
        fade = self._fade
        if fade is None or self._secondary is None:
            return
        self._fade = None
        if finish:
            old = self._primary
            self._primary, self._secondary = self._secondary, old
            old.stop()
            self._primary.set_volume(self._volume)
            self.current_path = fade["path"]
            self.listener.on_track_started(fade["path"], True)
            self._refresh_next()
        else:
            self._secondary.stop()
            self._primary.set_volume(self._volume)
