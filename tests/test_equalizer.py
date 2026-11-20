# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Equalizer model, presets, filter chain and audible effect."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from pulsedeck.audio.audio_filters import (
    DspSettings,
    build_chain,
    chain_structure,
    ffmpeg_af_string,
    live_update_commands,
    mpv_af_string,
)
from pulsedeck.audio.equalizer import (
    BANDS,
    BUILTIN_PRESETS,
    CUSTOM_PRESET_NAME,
    MAX_GAIN,
    MIN_GAIN,
    EqualizerState,
    Preset,
    PresetError,
    PresetStore,
)

REQUIRED_PRESETS = ["Flat", "Rock", "Pop", "Jazz", "Classical", "Dance", "Electronic", "Hip-Hop", "Bass Boost",
                    "Treble Boost", "Vocal", "Acoustic"]


def test_ten_bands_at_required_frequencies():
    assert BANDS == (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    assert (MIN_GAIN, MAX_GAIN) == (-12.0, 12.0)


def test_builtin_presets_complete_and_in_range():
    assert [p.name for p in BUILTIN_PRESETS] == REQUIRED_PRESETS
    for preset in BUILTIN_PRESETS:
        assert len(preset.gains) == 10
        assert all(MIN_GAIN <= g <= MAX_GAIN for g in preset.gains)
    assert all(g == 0 for g in BUILTIN_PRESETS[0].gains)


def test_band_adjustment_clamps_and_marks_custom():
    state = EqualizerState()
    state.set_band(0, 20)
    state.set_band(9, -30)
    state.set_band(4, "bad")  # type: ignore[arg-type]
    assert state.gains[0] == 12.0 and state.gains[9] == -12.0 and state.gains[4] == 0.0
    assert state.preset == CUSTOM_PRESET_NAME
    with pytest.raises(IndexError):
        state.set_band(10, 1.0)


def test_auto_preamp_prevents_boost_headroom_loss():
    state = EqualizerState(gains=[6, 9, 0, 0, 0, 0, 0, 0, 0, 0], preamp=1.0)
    assert state.headroom_db == -9.0
    assert state.effective_preamp == -8.0
    state.auto_preamp = False
    assert state.effective_preamp == 1.0


def test_apply_preset_and_reset():
    state = EqualizerState()
    rock = next(p for p in BUILTIN_PRESETS if p.name == "Rock")
    state.apply_preset(rock)
    assert state.gains == list(rock.gains) and state.preset == "Rock"
    state.reset()
    assert state.gains == [0.0] * 10 and state.preset == "Flat"


def test_state_config_round_trip():
    state = EqualizerState(gains=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], preamp=-3, enabled=False, bypass=True)
    again = EqualizerState.from_config(json.loads(json.dumps(state.to_config())))
    assert again == state


# -- preset store ---------------------------------------------------------------
def test_preset_store_save_rename_delete(tmp_path):
    store = PresetStore(tmp_path / "presets")
    store.save("Late Night", [1] * 10, -2)
    assert "Late Night" in store.names()
    assert PresetStore(tmp_path / "presets").get("late night").preamp == -2  # persisted, case-insensitive
    store.rename("Late Night", "Evening")
    assert store.get("Late Night") is None and store.get("Evening") is not None
    store.delete("Evening")
    assert store.custom_names() == []


def test_builtin_presets_are_protected(tmp_path):
    store = PresetStore(tmp_path / "presets")
    with pytest.raises(PresetError):
        store.save("Rock", [0] * 10)
    with pytest.raises(PresetError):
        store.delete("Pop")
    with pytest.raises(PresetError):
        store.rename("Jazz", "Mine")


def test_preset_import_export(tmp_path):
    store = PresetStore(tmp_path / "a")
    store.save("Mine", [2, 2, 2, 0, 0, 0, 0, -2, -2, -2])
    exported = tmp_path / "mine.json"
    store.export("Mine", exported)
    data = json.loads(exported.read_text())
    assert data["format"] == "pulsedeck-eq-preset" and data["bands_hz"][0] == 31
    other = PresetStore(tmp_path / "b")
    imported = other.import_file(exported)
    assert imported[0].gains == Preset("x", (2, 2, 2, 0, 0, 0, 0, -2, -2, -2)).gains
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"presets": [{"name": "Rock", "gains": [0] * 10}, {"name": "B", "gains": [1] * 10}]}))
    names = [p.name for p in other.import_file(bundle)]
    assert names == ["Rock (imported)", "B"]
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "x", "gains": [1, 2]}')
    with pytest.raises(PresetError):
        other.import_file(bad)


# -- filter chain -------------------------------------------------------------
def test_disabled_or_bypassed_eq_has_no_filters():
    off = EqualizerState(gains=[5] * 10, enabled=False)
    bypass = EqualizerState(gains=[5] * 10, bypass=True)
    assert build_chain(DspSettings(off)) == []
    assert build_chain(DspSettings(bypass)) == []
    assert ffmpeg_af_string([]) == "anull"


def test_chain_structure_is_stable_while_moving_sliders():
    a = EqualizerState()
    b = EqualizerState(gains=[12, 0, -12, 0, 0, 0, 0, 0, 0, 3])
    assert chain_structure(build_chain(DspSettings(a))) == chain_structure(build_chain(DspSettings(b)))
    commands = live_update_commands(a, b)
    assert ("eq0", "gain", "12") in commands and ("eq2", "gain", "-12") in commands
    assert ("preamp", "volume", "-12dB") in commands


def test_mpv_filter_string_is_labelled():
    af = mpv_af_string(build_chain(DspSettings(EqualizerState(gains=[1] * 10))))
    for i in range(10):
        assert f"@eq{i}:lavfi=[equalizer=f={BANDS[i]}:" in af
    assert "@preamp:" in af and "@limiter:" in af


# -- audible effect (renders real audio through FFmpeg) -----------------------
FFMPEG = shutil.which("ffmpeg")
RATE = 44100


def _render(af: str, seconds: float = 3.0) -> np.ndarray:
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"anoisesrc=d={seconds}:c=pink:r={RATE}:a=0.25:seed=7", "-ac", "2", "-af", af,
           "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)


def _band_energy(signal: np.ndarray, low: float, high: float) -> float:
    spectrum = np.abs(np.fft.rfft(signal[:, 0])) ** 2
    freqs = np.fft.rfftfreq(len(signal), 1 / RATE)
    return float(spectrum[(freqs >= low) & (freqs < high)].sum())


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg required")
def test_equalizer_really_changes_audio_output():
    flat = _render("anull")
    state = EqualizerState(gains=[0, 12, 0, 0, 0, 0, 0, 0, 0, 0], auto_preamp=False)
    boosted = _render(ffmpeg_af_string(build_chain(DspSettings(state, clip_protection=False))))
    gain_62 = 10 * np.log10(_band_energy(boosted, 50, 75) / _band_energy(flat, 50, 75))
    gain_4k = 10 * np.log10(_band_energy(boosted, 3500, 4500) / _band_energy(flat, 3500, 4500))
    assert gain_62 > 9.0          # the 62 Hz band is boosted by ~12 dB
    assert abs(gain_4k) < 0.5     # far-away bands are untouched

    cut = EqualizerState(gains=[0, 0, 0, 0, 0, 0, 0, 0, -12, 0], auto_preamp=False)
    cut_out = _render(ffmpeg_af_string(build_chain(DspSettings(cut, clip_protection=False))))
    assert 10 * np.log10(_band_energy(cut_out, 7000, 9000) / _band_energy(flat, 7000, 9000)) < -9.0


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg required")
def test_bypass_leaves_audio_bit_identical():
    original = _render("anull")
    state = EqualizerState(gains=[12] * 10, bypass=True)
    bypassed = _render(ffmpeg_af_string(build_chain(DspSettings(state))))
    assert np.array_equal(original, bypassed)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg required")
def test_full_boost_does_not_clip():
    state = EqualizerState(gains=[12] * 10, auto_preamp=True)
    out = _render(ffmpeg_af_string(build_chain(DspSettings(state, clip_protection=True))))
    assert np.max(np.abs(out)) <= 1.0
    loud = EqualizerState(gains=[12] * 10, preamp=12, auto_preamp=False)
    limited = _render(ffmpeg_af_string(build_chain(DspSettings(loud, clip_protection=True))))
    assert np.max(np.abs(limited)) <= 0.99


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg required")
def test_stereo_channels_stay_independent():
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"sine=f=440:d=1:r={RATE}", "-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=mono:d=1",
           "-filter_complex", "[0][1]amerge=inputs=2," + ffmpeg_af_string(build_chain(DspSettings(
               EqualizerState(gains=[3] * 10)))), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    out = np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, dtype=np.float32).reshape(-1, 2)
    assert np.max(np.abs(out[:, 0])) > 0.1
    assert np.max(np.abs(out[:, 1])) < 1e-6   # silent right channel stays silent
