# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Audio output device helpers."""

from __future__ import annotations

from dataclasses import dataclass

from pulsedeck.audio.playback_engine import PlaybackEngine


@dataclass(frozen=True)
class AudioDevice:
    name: str          # backend identifier, "auto" for the system default
    description: str


def list_devices(engine: PlaybackEngine) -> list[AudioDevice]:
    seen: set[str] = set()
    devices: list[AudioDevice] = []
    for name, description in engine.devices():
        if name in seen:
            continue
        seen.add(name)
        devices.append(AudioDevice(name, description))
    if "auto" not in seen:
        devices.insert(0, AudioDevice("auto", "System default"))
    return devices


def resolve_device(requested: str, available: list[AudioDevice]) -> str:
    """Fall back to the default device when the saved one is unplugged."""
    names = {d.name for d in available}
    return requested if requested in names else "auto"
