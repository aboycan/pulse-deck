# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""In-memory playlist model."""

from __future__ import annotations

import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pulsedeck.library.models import TrackInfo
from pulsedeck.library.search import matches, parse_query

SORT_KEYS = ("title", "artist", "album", "duration", "path")


@dataclass
class PlaylistEntry:
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    @property
    def display_title(self) -> str:
        return self.title or os.path.splitext(os.path.basename(self.path))[0]

    def as_track(self) -> TrackInfo:
        return TrackInfo(path=self.path, title=self.title, artist=self.artist, album=self.album,
                         duration=self.duration)

    @classmethod
    def from_track(cls, info: TrackInfo) -> PlaylistEntry:
        return cls(info.path, info.title, info.artist, info.album, info.duration)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"path": self.path}
        for key in ("title", "artist", "album"):
            if getattr(self, key):
                data[key] = getattr(self, key)
        if self.duration:
            data["duration"] = round(self.duration, 3)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlaylistEntry:
        return cls(
            path=str(data["path"]),
            title=str(data.get("title", "")),
            artist=str(data.get("artist", "")),
            album=str(data.get("album", "")),
            duration=float(data.get("duration", 0.0) or 0.0),
        )


@dataclass
class Playlist:
    name: str
    entries: list[PlaylistEntry] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    shuffle: bool = False
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def paths(self) -> list[str]:
        return [e.path for e in self.entries]

    @property
    def total_duration(self) -> float:
        return sum(e.duration for e in self.entries)

    def touch(self) -> None:
        self.modified = time.time()

    # -- editing ---------------------------------------------------------
    def add(self, entries: list[PlaylistEntry], at: int | None = None) -> range:
        position = len(self.entries) if at is None else max(0, min(at, len(self.entries)))
        self.entries[position:position] = entries
        self.touch()
        return range(position, position + len(entries))

    def remove(self, indices: list[int]) -> list[PlaylistEntry]:
        removed = []
        for index in sorted(set(indices), reverse=True):
            if 0 <= index < len(self.entries):
                removed.append(self.entries.pop(index))
        if removed:
            self.touch()
        return list(reversed(removed))

    def move(self, indices: list[int], destination: int) -> list[int]:
        """Move rows to ``destination`` (an insertion point in the original list).

        Returns the new indices of the moved rows.
        """
        rows = sorted(i for i in set(indices) if 0 <= i < len(self.entries))
        if not rows:
            return []
        moving = [self.entries[i] for i in rows]
        before = sum(1 for i in rows if i < destination)
        for index in reversed(rows):
            self.entries.pop(index)
        target = max(0, min(destination - before, len(self.entries)))
        self.entries[target:target] = moving
        self.touch()
        return list(range(target, target + len(moving)))

    def move_up(self, indices: list[int]) -> list[int]:
        rows = sorted(set(indices))
        if not rows or rows[0] == 0:
            return rows
        return self.move(rows, rows[0] - 1)

    def move_down(self, indices: list[int]) -> list[int]:
        rows = sorted(set(indices))
        if not rows or rows[-1] >= len(self.entries) - 1:
            return rows
        return self.move(rows, rows[-1] + 2)

    def sort(self, key: str, reverse: bool = False) -> None:
        if key not in SORT_KEYS:
            raise ValueError(key)
        if key == "duration":
            self.entries.sort(key=lambda e: e.duration, reverse=reverse)
        elif key == "title":
            self.entries.sort(key=lambda e: e.display_title.casefold(), reverse=reverse)
        else:
            self.entries.sort(key=lambda e: (str(getattr(e, key)).casefold(), e.display_title.casefold()),
                              reverse=reverse)
        self.touch()

    def shuffle_entries(self, rng: random.Random | None = None) -> None:
        (rng or random.Random()).shuffle(self.entries)
        self.touch()

    def clear(self) -> None:
        self.entries.clear()
        self.touch()

    def duplicate(self, name: str | None = None) -> Playlist:
        return Playlist(
            name=name or f"{self.name} (copy)",
            entries=[PlaylistEntry(**e.__dict__) for e in self.entries],
            shuffle=self.shuffle,
        )

    def search(self, text: str) -> list[int]:
        query = parse_query(text)
        if query.empty:
            return list(range(len(self.entries)))
        return [i for i, e in enumerate(self.entries) if matches(e.as_track(), query)]

    def missing(self) -> list[int]:
        return [i for i, e in enumerate(self.entries) if not e.exists]

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "pulsedeck-playlist",
            "version": 1,
            "id": self.id,
            "name": self.name,
            "shuffle": self.shuffle,
            "created": self.created,
            "modified": self.modified,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Playlist:
        if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
            raise ValueError("Not a PulseDeck playlist")
        entries = []
        for item in data.get("entries", []):
            if isinstance(item, str):
                entries.append(PlaylistEntry(item))
            elif isinstance(item, dict) and "path" in item:
                entries.append(PlaylistEntry.from_dict(item))
        return cls(
            name=str(data.get("name") or "Playlist"),
            entries=entries,
            id=str(data.get("id") or uuid.uuid4().hex),
            shuffle=bool(data.get("shuffle", False)),
            created=float(data.get("created", time.time())),
            modified=float(data.get("modified", time.time())),
        )
