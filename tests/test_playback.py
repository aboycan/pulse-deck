# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Playback queue and engine tests (simulated backend + optional real libmpv)."""

from __future__ import annotations

import random
import time

import pytest

from pulsedeck.audio import playback_engine as pe
from pulsedeck.audio.backend import BackendCallbacks, SimulatedBackend
from pulsedeck.audio.equalizer import EqualizerState
from pulsedeck.audio.playback_engine import EngineListener, PlaybackEngine, PlaybackState
from pulsedeck.audio.playback_queue import PlaybackQueue, RepeatMode


# -- queue -------------------------------------------------------------------
def _queue(n: int = 5, **kw) -> PlaybackQueue:  # noqa: ANN003
    q = PlaybackQueue(rng=random.Random(1))
    q.set_tracks([f"/m/{i}.mp3" for i in range(n)], **kw)
    return q


def test_next_previous_in_order():
    q = _queue(current=0)
    assert q.advance(auto=False) == "/m/1.mp3"
    assert q.advance(auto=False) == "/m/2.mp3"
    assert q.previous() == "/m/1.mp3"
    assert q.current_index == 1


def test_repeat_off_stops_at_end():
    q = _queue(3, current=2)
    assert q.peek_next() is None
    assert q.advance() is None


def test_repeat_all_wraps():
    q = _queue(3, current=2)
    q.repeat = RepeatMode.ALL
    assert q.peek_next() == 0
    assert q.advance() == "/m/0.mp3"


def test_repeat_one_only_on_auto_advance():
    q = _queue(3, current=1)
    q.repeat = RepeatMode.ONE
    assert q.advance(auto=True) == "/m/1.mp3"
    assert q.advance(auto=False) == "/m/2.mp3"


def test_repeat_mode_cycle_and_parse():
    assert RepeatMode.OFF.cycled() is RepeatMode.ALL
    assert RepeatMode.ALL.cycled() is RepeatMode.ONE
    assert RepeatMode.ONE.cycled() is RepeatMode.OFF
    assert RepeatMode.parse("bogus") is RepeatMode.OFF


def test_shuffle_plays_every_track_once_and_starts_with_current():
    q = _queue(20, current=7)
    q.set_shuffle(True)
    assert q.current_index == 7
    seen = [q.current_index]
    while (path := q.advance()) is not None:
        seen.append(q.current_index)
        assert path == f"/m/{q.current_index}.mp3"
    assert sorted(seen) == list(range(20))


def test_shuffle_previous_returns_history():
    q = _queue(10, current=0)
    q.set_shuffle(True)
    first = q.current_index
    q.advance(auto=False)
    second = q.current_index
    q.advance(auto=False)
    assert q.previous() == f"/m/{second}.mp3"
    assert q.previous() == f"/m/{first}.mp3"


def test_play_next_takes_priority():
    q = _queue(5, current=0)
    q.play_next(3)
    assert q.peek_next() == 3
    assert q.advance() == "/m/3.mp3"
    assert q.advance() == "/m/4.mp3"


def test_sync_keeps_current_after_edit():
    q = _queue(4, current=2)
    paths = q.paths
    paths.insert(0, "/m/new.mp3")
    q.sync(paths, 3)
    assert q.current_path == "/m/2.mp3"
    assert q.advance() == "/m/3.mp3"


def test_empty_queue_is_safe():
    q = PlaybackQueue()
    assert q.advance() is None
    assert q.previous() is None
    assert q.current_path is None


# -- engine (simulated backend) ---------------------------------------------
class Recorder(EngineListener):
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_state_changed(self, state):  # noqa: ANN001
        self.events.append(("state", state))

    def on_track_started(self, path, auto):  # noqa: ANN001
        self.events.append(("started", path, auto))

    def on_track_finished(self):
        self.events.append(("finished",))

    def on_error(self, path, message):  # noqa: ANN001
        self.events.append(("error", path))

    def names(self) -> list[str]:
        return [e[0] for e in self.events]


@pytest.fixture
def tracks(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"t{i}.mp3"
        p.write_bytes(b"\0")
        paths.append(str(p))
    return paths


def make_engine(durations=None):  # noqa: ANN001,ANN201
    backends: list[SimulatedBackend] = []

    def factory(callbacks: BackendCallbacks) -> SimulatedBackend:
        backend = SimulatedBackend(durations=dict(durations or {}), default_duration=10.0, callbacks=callbacks)
        backends.append(backend)
        return backend

    recorder = Recorder()
    engine = PlaybackEngine(factory, recorder, threaded=False)
    return engine, recorder, backends


def test_play_pause_stop(tracks):
    engine, rec, backends = make_engine()
    engine.play_file(tracks[0])
    assert engine.state is PlaybackState.PLAYING
    assert ("started", tracks[0], False) in rec.events
    engine.pause()
    assert engine.state is PlaybackState.PAUSED and backends[0].paused
    engine.play()
    assert engine.state is PlaybackState.PLAYING and not backends[0].paused
    engine.stop()
    assert engine.state is PlaybackState.STOPPED and engine.current_path is None


def test_seek_absolute_relative_and_clamped(tracks):
    engine, _rec, backends = make_engine()
    engine.play_file(tracks[0])
    engine.seek(4.0)
    assert backends[0].position == pytest.approx(4.0)
    engine.seek(2.5, relative=True)
    assert backends[0].position == pytest.approx(6.5)
    engine.seek(-100, relative=True)
    assert backends[0].position == 0.0
    engine.seek(1000)
    assert backends[0].position < 10.0


def test_start_position_resume(tracks):
    engine, _rec, backends = make_engine()
    engine.play_file(tracks[0], start=3.0, paused=True)
    assert engine.state is PlaybackState.PAUSED
    assert backends[0].position == pytest.approx(3.0)


def test_volume_mute_speed(tracks):
    engine, _rec, backends = make_engine()
    engine.set_volume(35)
    engine.play_file(tracks[0])
    assert backends[0].volume == 35
    engine.set_volume(150)
    assert backends[0].volume == 100
    engine.set_muted(True)
    assert backends[0].muted
    engine.set_speed(1.5)
    assert backends[0].speed == 1.5


def test_gapless_auto_advance_uses_next_provider(tracks):
    engine, rec, backends = make_engine()
    upcoming = [tracks[1], tracks[2], None]
    engine.next_provider = lambda: upcoming[0]
    engine.play_file(tracks[0])
    backends[0].advance(10.0)
    assert ("started", tracks[1], True) in rec.events
    upcoming.pop(0)
    engine.refresh_next()
    backends[0].advance(10.0)
    assert ("started", tracks[2], True) in rec.events
    upcoming.pop(0)
    engine.refresh_next()
    backends[0].advance(10.0)
    assert rec.names()[-1] == "finished"
    assert engine.state is PlaybackState.STOPPED


def test_missing_file_reports_error(tmp_path):
    engine, rec, _ = make_engine()
    engine.play_file(str(tmp_path / "nope.mp3"))
    assert ("error", str(tmp_path / "nope.mp3")) in rec.events
    assert engine.state is PlaybackState.STOPPED


def test_crossfade_swaps_backends(tracks, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(pe.time, "monotonic", lambda: clock[0])
    engine, rec, backends = make_engine()
    engine.set_crossfade(2.0)
    engine.next_provider = lambda: tracks[1]
    engine.play_file(tracks[0])
    backends[0].advance(8.5)       # 1.5 s left -> inside the crossfade window
    engine.tick()
    assert len(backends) == 2 and backends[1].current_path == tracks[1]
    clock[0] += 0.75
    engine.tick()
    assert 0 < backends[1].volume < engine._volume  # noqa: SLF001 - fading in
    clock[0] += 1.0
    engine.tick()
    assert engine.current_path == tracks[1]
    assert ("started", tracks[1], True) in rec.events


def test_equalizer_changes_are_ramped_in_place(tracks):
    engine, _rec, backends = make_engine()
    engine.play_file(tracks[0])
    state = EqualizerState()
    state.set_band(1, 6.0)
    engine.set_equalizer(state)
    for _ in range(10):
        engine.tick()
    gains = [float(arg) for label, cmd, arg in backends[0].commands if label == "eq1"]
    assert gains[-1] == pytest.approx(6.0)
    steps = [b - a for a, b in zip([0.0, *gains], gains, strict=False)]
    assert all(abs(s) <= pe.EQ_RAMP_STEP_DB + 1e-9 for s in steps)
    assert engine.equalizer_applied.gains[1] == pytest.approx(6.0)


def test_equalizer_bypass_rebuilds_chain_without_filters(tracks):
    engine, _rec, backends = make_engine()
    engine.play_file(tracks[0])
    state = EqualizerState(gains=[3.0] * 10)
    engine.set_equalizer(state)
    assert "equalizer=" in backends[0].af
    state.bypass = True
    engine.set_equalizer(state)
    assert "equalizer=" not in backends[0].af


def test_threaded_engine_processes_commands(tracks):
    def factory(callbacks):  # noqa: ANN001,ANN202
        return SimulatedBackend(default_duration=5.0, callbacks=callbacks)

    engine = PlaybackEngine(factory, Recorder(), threaded=True)
    try:
        engine.play_file(tracks[0])
        engine.wait_idle()
        assert engine.state is PlaybackState.PLAYING
    finally:
        engine.shutdown()


# -- real libmpv playback (runs in CI where libmpv is installed) -------------
def _mpv_or_skip():  # noqa: ANN202
    try:
        from pulsedeck.audio.mpv_backend import MpvBackend, import_mpv

        import_mpv()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"libmpv not available: {exc}")
    return MpvBackend


@pytest.mark.parametrize("fixture_name", ["mp3_file", "flac_file"])
def test_real_playback_mp3_flac(fixture_name, request):
    backend_cls = _mpv_or_skip()
    path = str(request.getfixturevalue(fixture_name))
    ended = []
    errors = []
    backend = backend_cls(BackendCallbacks(on_end=lambda: ended.append(True),
                                           on_error=lambda p, m: errors.append(m)), audio_output="null")
    try:
        backend.load(path)
        deadline = time.time() + 5
        while backend.duration <= 0 and time.time() < deadline:
            time.sleep(0.05)
        assert backend.duration == pytest.approx(2.0, abs=0.2)
        backend.seek(1.0)
        time.sleep(0.2)
        assert backend.position >= 0.9
        params = backend.audio_params()
        assert params.sample_rate == 44100
        deadline = time.time() + 6
        while not ended and time.time() < deadline:
            time.sleep(0.05)
        assert ended and not errors
    finally:
        backend.shutdown()


def test_real_playback_corrupt_file_reports_error(tmp_path):
    backend_cls = _mpv_or_skip()
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"this is not audio" * 100)
    errors = []
    backend = backend_cls(BackendCallbacks(on_error=lambda p, m: errors.append(p)), audio_output="null")
    try:
        backend.load(str(bad))
        deadline = time.time() + 5
        while not errors and time.time() < deadline:
            time.sleep(0.05)
        assert errors
    finally:
        backend.shutdown()


# -- MpvBackend against a fake python-mpv (runs everywhere) --------------------
class _FakeMPV:
    """Mimics python-mpv: attributes are live properties, ``[]`` is options/ only."""

    OPTIONS = {"start", "af", "replaygain", "replaygain-preamp", "replaygain-clip", "audio-device", "gapless-audio"}

    def __init__(self, **kwargs):
        object.__setattr__(self, "props", {"time-pos": None, "duration": None, "idle-active": True,
                                           "playlist-count": 0, "playlist-pos": -1, "pause": False})
        object.__setattr__(self, "commands", [])

    def __getattr__(self, name):
        return self.props.get(name.replace("_", "-"))

    def __setattr__(self, name, value):
        self.props[name.replace("_", "-")] = value

    def __getitem__(self, name):  # python-mpv reads options/<name>
        if name not in self.OPTIONS:
            raise AttributeError(f"options/{name} does not exist")
        return self.props.get(name)

    def __setitem__(self, name, value):
        if name not in self.OPTIONS:
            raise AttributeError(f"options/{name} does not exist")
        self.props[name] = value

    def observe_property(self, name, callback):
        pass

    def register_event_callback(self, callback):
        pass

    def command(self, *args):
        self.commands.append(args)
        if args[0] == "loadfile" and args[2] == "append":
            self.props["playlist-count"] += 1
        elif args[0] == "loadfile":
            self.props.update({"playlist-count": 1, "playlist-pos": 0, "idle-active": False})
        elif args[0] == "playlist-remove":
            self.props["playlist-count"] -= 1

    def terminate(self):
        pass


@pytest.fixture
def fake_mpv_backend(monkeypatch):
    import types

    from pulsedeck.audio import mpv_backend

    module = types.SimpleNamespace(MPV=_FakeMPV)
    monkeypatch.setattr(mpv_backend, "import_mpv", lambda: module)
    return mpv_backend.MpvBackend(BackendCallbacks())


def test_mpv_backend_reads_live_position_and_duration(fake_mpv_backend):
    b = fake_mpv_backend
    b.load("/music/song.mp3")
    b._mpv.props.update({"time-pos": 12.5, "duration": 47.0})  # noqa: SLF001
    assert b.position == pytest.approx(12.5)
    assert b.duration == pytest.approx(47.0)
    assert b.is_idle is False


def test_mpv_backend_reads_audio_params(fake_mpv_backend):
    b = fake_mpv_backend
    b._mpv.props.update({"audio-params": {"samplerate": 48000, "channel-count": 2},  # noqa: SLF001
                         "audio-bitrate": 320000, "audio-codec-name": "mp3"})
    params = b.audio_params()
    assert (params.sample_rate, params.channels, params.bitrate, params.codec) == (48000, 2, 320000, "mp3")


def test_mpv_backend_gapless_queue_does_not_pile_up(fake_mpv_backend):
    b = fake_mpv_backend
    b.load("/music/a.mp3")
    for _ in range(3):  # refresh_next() runs often; the queue must hold one entry
        b.set_next("/music/b.mp3")
    assert b._mpv.props["playlist-count"] == 2  # noqa: SLF001


def test_mpv_backend_settings_reach_mpv(fake_mpv_backend):
    b = fake_mpv_backend
    b.set_filters("@eq0:lavfi=[equalizer=f=31:t=o:w=1:g=3]")
    b.set_replaygain("album", 2.0)
    b.set_device("auto")
    assert b._mpv.props["af"].startswith("@eq0")  # noqa: SLF001
    assert b._mpv.props["replaygain"] == "album"  # noqa: SLF001
