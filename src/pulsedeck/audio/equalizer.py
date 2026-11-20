# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""10-band graphic equalizer model, presets and preset storage.

This module is pure Python. The actual DSP is performed by FFmpeg's
``equalizer`` (peaking biquad) filters inside libmpv; see
:mod:`pulsedeck.audio.audio_filters` for how the state is turned into a
filter chain.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pulsedeck.core import platform
from pulsedeck.core.configuration import atomic_write_text

log = logging.getLogger(__name__)

BANDS: tuple[int, ...] = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
BAND_LABELS: tuple[str, ...] = ("31", "62", "125", "250", "500", "1K", "2K", "4K", "8K", "16K")
MIN_GAIN = -12.0
MAX_GAIN = 12.0
DEFAULT_GAIN = 0.0
MIN_PREAMP = -12.0
MAX_PREAMP = 12.0

PRESET_FILE_FORMAT = "pulsedeck-eq-preset"
PRESET_FILE_VERSION = 1


def clamp_gain(value: float, low: float = MIN_GAIN, high: float = MAX_GAIN) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_GAIN
    if number != number:  # NaN
        return DEFAULT_GAIN
    return round(max(low, min(high, number)), 2)


@dataclass(frozen=True)
class Preset:
    name: str
    gains: tuple[float, ...]
    preamp: float = 0.0
    builtin: bool = False

    def __post_init__(self) -> None:
        if len(self.gains) != len(BANDS):
            raise ValueError(f"Preset {self.name!r} needs {len(BANDS)} gains, got {len(self.gains)}")
        object.__setattr__(self, "gains", tuple(clamp_gain(g) for g in self.gains))
        object.__setattr__(self, "preamp", clamp_gain(self.preamp, MIN_PREAMP, MAX_PREAMP))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "gains": list(self.gains), "preamp": self.preamp}


# Original PulseDeck preset curves (dB per band, 31 Hz .. 16 kHz).
BUILTIN_PRESETS: tuple[Preset, ...] = (
    Preset("Flat", (0, 0, 0, 0, 0, 0, 0, 0, 0, 0), builtin=True),
    Preset("Rock", (4.5, 3.5, 2.0, -0.5, -1.5, -0.5, 1.5, 3.0, 4.0, 4.5), builtin=True),
    Preset("Pop", (-1.0, 0.5, 2.5, 3.5, 3.0, 1.0, -0.5, -1.0, -0.5, 0.5), builtin=True),
    Preset("Jazz", (3.0, 2.0, 1.0, 1.5, -1.0, -1.0, 0.0, 1.0, 2.0, 2.5), builtin=True),
    Preset("Classical", (3.0, 2.5, 1.5, 0.5, 0.0, 0.0, 0.0, 1.0, 2.0, 3.0), builtin=True),
    Preset("Dance", (5.5, 4.5, 2.5, 0.0, 0.0, -1.5, -2.0, -1.0, 2.5, 3.5), builtin=True),
    Preset("Electronic", (5.0, 4.0, 1.0, -1.0, -2.0, 1.0, 0.5, 2.0, 4.0, 5.0), builtin=True),
    Preset("Hip-Hop", (6.0, 5.0, 2.0, 2.5, -1.0, -1.0, 1.0, -0.5, 1.5, 2.5), builtin=True),
    Preset("Bass Boost", (8.0, 6.5, 5.0, 3.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0), builtin=True),
    Preset("Treble Boost", (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 2.5, 4.5, 6.5, 8.0), builtin=True),
    Preset("Vocal", (-2.5, -2.0, -1.0, 1.0, 3.5, 4.0, 3.5, 2.0, 0.5, -1.0), builtin=True),
    Preset("Acoustic", (3.5, 3.0, 2.0, 1.0, 1.5, 1.0, 2.0, 2.5, 2.5, 1.5), builtin=True),
)

#: Name used for the unsaved, user-adjusted curve.
CUSTOM_PRESET_NAME = "Custom"
_BUILTIN_NAMES = {p.name.casefold() for p in BUILTIN_PRESETS} | {CUSTOM_PRESET_NAME.casefold()}


@dataclass
class EqualizerState:
    """Live equalizer settings as seen by the UI and the engine."""

    gains: list[float] = field(default_factory=lambda: [DEFAULT_GAIN] * len(BANDS))
    preamp: float = 0.0
    enabled: bool = True
    bypass: bool = False
    auto_preamp: bool = True
    preset: str = "Flat"

    def __post_init__(self) -> None:
        gains = list(self.gains)[: len(BANDS)]
        gains += [DEFAULT_GAIN] * (len(BANDS) - len(gains))
        self.gains = [clamp_gain(g) for g in gains]
        self.preamp = clamp_gain(self.preamp, MIN_PREAMP, MAX_PREAMP)

    @property
    def active(self) -> bool:
        """True when the EQ should actually be in the signal path."""
        return self.enabled and not self.bypass

    @property
    def is_flat(self) -> bool:
        return all(g == 0 for g in self.gains) and self.effective_preamp == 0

    @property
    def headroom_db(self) -> float:
        """Attenuation applied automatically so boosted bands do not clip."""
        if not self.auto_preamp:
            return 0.0
        return -max(0.0, max(self.gains))

    @property
    def effective_preamp(self) -> float:
        return round(self.preamp + self.headroom_db, 2)

    def set_band(self, index: int, gain: float) -> None:
        if not 0 <= index < len(BANDS):
            raise IndexError(index)
        self.gains[index] = clamp_gain(gain)
        self.preset = CUSTOM_PRESET_NAME

    def apply_preset(self, preset: Preset) -> None:
        self.gains = list(preset.gains)
        self.preamp = preset.preamp
        self.preset = preset.name

    def reset(self) -> None:
        self.gains = [DEFAULT_GAIN] * len(BANDS)
        self.preamp = 0.0
        self.preset = "Flat"

    def to_config(self) -> dict[str, Any]:
        return {
            "gains": list(self.gains),
            "preamp": self.preamp,
            "enabled": self.enabled,
            "bypass": self.bypass,
            "auto_preamp": self.auto_preamp,
            "preset": self.preset,
        }

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> EqualizerState:
        return cls(
            gains=list(data.get("gains", [])),
            preamp=float(data.get("preamp", 0.0)),
            enabled=bool(data.get("enabled", True)),
            bypass=bool(data.get("bypass", False)),
            auto_preamp=bool(data.get("auto_preamp", True)),
            preset=str(data.get("preset", "Flat")),
        )


class PresetError(Exception):
    pass


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\- ]+", "_", name, flags=re.UNICODE).strip() or "preset"
    return cleaned[:80]


class PresetStore:
    """Built-in presets plus user presets stored as JSON files."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or platform.config_dir() / "eq_presets"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._custom: dict[str, Preset] = {}
        self.reload()

    # -- queries ---------------------------------------------------------
    def reload(self) -> None:
        self._custom.clear()
        for file in sorted(self.directory.glob("*.json")):
            try:
                preset = self._parse(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, ValueError, PresetError) as exc:
                log.warning("Skipping invalid preset %s: %s", file, exc)
                continue
            self._custom[preset.name.casefold()] = preset

    def names(self) -> list[str]:
        return [p.name for p in BUILTIN_PRESETS] + sorted((p.name for p in self._custom.values()), key=str.casefold)

    def custom_names(self) -> list[str]:
        return sorted((p.name for p in self._custom.values()), key=str.casefold)

    def get(self, name: str) -> Preset | None:
        for preset in BUILTIN_PRESETS:
            if preset.name.casefold() == name.casefold():
                return preset
        return self._custom.get(name.casefold())

    def is_builtin(self, name: str) -> bool:
        return name.casefold() in _BUILTIN_NAMES

    # -- mutations -------------------------------------------------------
    def save(self, name: str, gains: list[float] | tuple[float, ...], preamp: float = 0.0,
             overwrite: bool = True) -> Preset:
        name = name.strip()
        if not name:
            raise PresetError("Preset name cannot be empty")
        if self.is_builtin(name):
            raise PresetError(f"'{name}' is a built-in preset name")
        if not overwrite and name.casefold() in self._custom:
            raise PresetError(f"A preset called '{name}' already exists")
        preset = Preset(name, tuple(gains), preamp)
        self._write(preset)
        self._custom[name.casefold()] = preset
        return preset

    def rename(self, old: str, new: str) -> Preset:
        new = new.strip()
        current = self._custom.get(old.casefold())
        if current is None:
            raise PresetError("Only custom presets can be renamed")
        if not new or self.is_builtin(new):
            raise PresetError(f"Invalid preset name '{new}'")
        if new.casefold() != old.casefold() and new.casefold() in self._custom:
            raise PresetError(f"A preset called '{new}' already exists")
        self.delete(old)
        return self.save(new, current.gains, current.preamp)

    def delete(self, name: str) -> None:
        if name.casefold() not in self._custom:
            raise PresetError("Only custom presets can be deleted")
        preset = self._custom.pop(name.casefold())
        path = self._path_for(preset.name)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def export(self, name: str, destination: Path) -> None:
        preset = self.get(name)
        if preset is None:
            raise PresetError(f"Unknown preset '{name}'")
        atomic_write_text(destination, json.dumps(self._serialize(preset), indent=2))

    def import_file(self, source: Path) -> list[Preset]:
        """Import one preset or a list of presets; returns what was imported."""
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PresetError(f"Cannot read preset file: {exc}") from exc
        items = data.get("presets") if isinstance(data, dict) and "presets" in data else data
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise PresetError("Unrecognised preset file")
        imported = []
        for item in items:
            preset = self._parse(item)
            name = preset.name
            if self.is_builtin(name):
                name = f"{name} (imported)"
            imported.append(self.save(name, preset.gains, preset.preamp))
        return imported

    # -- helpers ---------------------------------------------------------
    def _path_for(self, name: str) -> Path:
        return self.directory / f"{_safe_filename(name)}.json"

    def _write(self, preset: Preset) -> None:
        atomic_write_text(self._path_for(preset.name), json.dumps(self._serialize(preset), indent=2))

    @staticmethod
    def _serialize(preset: Preset) -> dict[str, Any]:
        return {
            "format": PRESET_FILE_FORMAT,
            "version": PRESET_FILE_VERSION,
            "bands_hz": list(BANDS),
            **preset.to_dict(),
        }

    @staticmethod
    def _parse(data: Any) -> Preset:
        if not isinstance(data, dict):
            raise PresetError("Preset entry must be an object")
        name = str(data.get("name", "")).strip()
        gains = data.get("gains")
        if not name or not isinstance(gains, list) or len(gains) != len(BANDS):
            raise PresetError(f"Preset needs a name and {len(BANDS)} gains")
        try:
            return Preset(name, tuple(float(g) for g in gains), float(data.get("preamp", 0.0)))
        except (TypeError, ValueError) as exc:
            raise PresetError(str(exc)) from exc
