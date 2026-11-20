# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Plain data models shared by the library, playlists and UI."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from typing import Any

#: File extensions PulseDeck will offer to open and scan.
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff", ".aifc"}
)


def is_audio_file(path: str | os.PathLike[str]) -> bool:
    return os.path.splitext(os.fspath(path))[1].lower() in AUDIO_EXTENSIONS


@dataclass
class TrackInfo:
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    genre: str = ""
    year: str = ""
    track_number: str = ""
    disc_number: str = ""
    composer: str = ""
    copyright: str = ""
    duration: float = 0.0          # seconds
    bitrate: int = 0               # bits per second
    sample_rate: int = 0           # Hz
    channels: int = 0
    file_size: int = 0             # bytes
    mtime: float = 0.0
    codec: str = ""
    has_artwork: bool = False
    replaygain_track_gain: float | None = None
    replaygain_album_gain: float | None = None
    # library-only fields
    id: int | None = None
    favourite: bool = False
    play_count: int = 0
    last_played: float | None = None
    added_at: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def display_artist(self) -> str:
        return self.artist or self.album_artist or "Unknown artist"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackInfo:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # pragma: no cover
