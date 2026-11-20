# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Translate DSP settings into an FFmpeg/libmpv audio filter chain.

The same chain is used two ways:

* :func:`mpv_af_string` produces the value for libmpv's ``af`` property. Each
  filter is labelled (``@eq3`` etc.) so gains can later be changed in place
  with ``af-command`` without rebuilding the graph, which keeps adjustments
  click-free.
* :func:`ffmpeg_af_string` produces the equivalent ``ffmpeg -af`` argument.
  The test-suite renders audio through it to prove the equalizer really
  changes the output signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from pulsedeck.audio.equalizer import BANDS, EqualizerState

#: Bandwidth of each peaking filter, in octaves. Bands are one octave apart.
BAND_WIDTH_OCTAVES = 1.0
#: Peak ceiling used by the clip-protection limiter (linear, ~ -0.2 dBFS).
LIMITER_CEILING = 0.977


@dataclass(frozen=True)
class FilterSpec:
    label: str
    expression: str


@dataclass(frozen=True)
class DspSettings:
    equalizer: EqualizerState
    balance: float = 0.0          # -1 .. 1
    normalization: bool = False
    clip_protection: bool = True


def band_label(index: int) -> str:
    return f"eq{index}"


def _fmt(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def equalizer_filters(state: EqualizerState) -> list[FilterSpec]:
    """Peaking filters for every band plus the preamp stage.

    Returns an empty list when the EQ is disabled or bypassed so the signal
    reaches the output untouched.
    """
    if not state.active:
        return []
    specs = [FilterSpec("preamp", f"volume=volume={_fmt(state.effective_preamp)}dB:precision=float")]
    for index, (freq, gain) in enumerate(zip(BANDS, state.gains, strict=True)):
        specs.append(
            FilterSpec(
                band_label(index),
                f"equalizer=f={freq}:t=o:w={_fmt(BAND_WIDTH_OCTAVES)}:g={_fmt(gain)}",
            )
        )
    return specs


def balance_filter(balance: float) -> FilterSpec | None:
    balance = max(-1.0, min(1.0, float(balance)))
    if abs(balance) < 1e-3:
        return None
    left = 1.0 if balance <= 0 else 1.0 - balance
    right = 1.0 if balance >= 0 else 1.0 + balance
    return FilterSpec("balance", f"pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1")


def build_chain(settings: DspSettings) -> list[FilterSpec]:
    chain: list[FilterSpec] = []
    chain.extend(equalizer_filters(settings.equalizer))
    bal = balance_filter(settings.balance)
    if bal:
        chain.append(bal)
    if settings.normalization:
        chain.append(FilterSpec("norm", "dynaudnorm=f=500:g=31:p=0.95:m=10"))
    # The limiter is present whenever DSP is active so that moving a slider
    # never changes the chain structure (structure changes force a graph
    # rebuild). With the EQ off it is left out to keep the path transparent.
    if settings.clip_protection and (settings.equalizer.active or settings.normalization):
        chain.append(FilterSpec("limiter", f"alimiter=limit={LIMITER_CEILING}:attack=5:release=50:level=0"))
    return chain


def mpv_af_string(chain: list[FilterSpec]) -> str:
    return ",".join(f"@{spec.label}:lavfi=[{spec.expression}]" for spec in chain)


def ffmpeg_af_string(chain: list[FilterSpec]) -> str:
    return ",".join(spec.expression for spec in chain) or "anull"


def chain_structure(chain: list[FilterSpec]) -> tuple[str, ...]:
    """Labels in order: if unchanged, values can be updated in place."""
    return tuple(spec.label for spec in chain)


def live_update_commands(old: EqualizerState, new: EqualizerState) -> list[tuple[str, str, str]]:
    """``af-command`` triples to move a running chain from ``old`` to ``new``."""
    commands: list[tuple[str, str, str]] = []
    if old.effective_preamp != new.effective_preamp:
        commands.append(("preamp", "volume", f"{_fmt(new.effective_preamp)}dB"))
    for index, (before, after) in enumerate(zip(old.gains, new.gains, strict=True)):
        if before != after:
            commands.append((band_label(index), "gain", _fmt(after)))
    return commands
