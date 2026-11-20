# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Play order: current track, shuffle, repeat modes and "play next"."""

from __future__ import annotations

import random
from enum import Enum


class RepeatMode(str, Enum):
    OFF = "off"
    ONE = "one"
    ALL = "all"

    @classmethod
    def parse(cls, value: str | RepeatMode | None) -> RepeatMode:
        try:
            return cls(value) if value is not None else cls.OFF
        except ValueError:
            return cls.OFF

    def cycled(self) -> RepeatMode:
        return {RepeatMode.OFF: RepeatMode.ALL, RepeatMode.ALL: RepeatMode.ONE, RepeatMode.ONE: RepeatMode.OFF}[self]


class PlaybackQueue:
    """Tracks the play position within a list of file paths.

    ``order`` is a permutation of playlist indices. Without shuffle it is the
    identity; with shuffle it is a random permutation that starts with the
    current track so already-heard songs are not repeated before the cycle
    ends.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._paths: list[str] = []
        self._order: list[int] = []
        self._pos: int = -1          # position inside _order
        self._shuffle = False
        self.repeat = RepeatMode.OFF
        self._up_next: list[int] = []  # playlist indices queued with "Play Next"
        self._history: list[int] = []  # playlist indices actually played (for Previous in shuffle)

    # -- properties --------------------------------------------------------
    @property
    def paths(self) -> list[str]:
        return list(self._paths)

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def current_index(self) -> int | None:
        if 0 <= self._pos < len(self._order):
            return self._order[self._pos]
        return None

    @property
    def current_path(self) -> str | None:
        idx = self.current_index
        return self._paths[idx] if idx is not None else None

    def __len__(self) -> int:
        return len(self._paths)

    # -- content -----------------------------------------------------------
    def set_tracks(self, paths: list[str], current: int | None = None) -> None:
        self._paths = list(paths)
        self._up_next.clear()
        self._history.clear()
        self._rebuild_order(current)

    def sync(self, paths: list[str], current: int | None) -> None:
        """Replace the list after an edit, keeping ``current`` as the playing item."""
        up_next_paths = [self._paths[i] for i in self._up_next if i < len(self._paths)]
        self._paths = list(paths)
        self._rebuild_order(current)
        self._history = []
        self._up_next = []
        used: set[int] = set()
        for path in up_next_paths:
            for i, p in enumerate(self._paths):
                if p == path and i not in used:
                    self._up_next.append(i)
                    used.add(i)
                    break

    def _rebuild_order(self, current: int | None) -> None:
        n = len(self._paths)
        indices = list(range(n))
        if self._shuffle and n:
            self._rng.shuffle(indices)
            if current is not None and 0 <= current < n:
                indices.remove(current)
                indices.insert(0, current)
        self._order = indices
        if current is not None and 0 <= current < n:
            self._pos = self._order.index(current)
        else:
            self._pos = -1

    def set_shuffle(self, enabled: bool) -> None:
        if enabled == self._shuffle:
            return
        self._shuffle = enabled
        self._rebuild_order(self.current_index)

    def jump_to(self, index: int) -> str:
        if not 0 <= index < len(self._paths):
            raise IndexError(index)
        if self.current_index is not None:
            self._history.append(self.current_index)
        if self._shuffle:
            # Keep the shuffled cycle but make the chosen track current.
            self._order.remove(index)
            insert_at = max(self._pos, 0)
            self._order.insert(insert_at, index)
            self._pos = insert_at
        else:
            self._pos = index
        if index in self._up_next:
            self._up_next.remove(index)
        return self._paths[index]

    def play_next(self, index: int) -> None:
        if 0 <= index < len(self._paths) and index not in self._up_next:
            self._up_next.append(index)

    # -- navigation ----------------------------------------------------------
    def peek_next(self, auto: bool = True) -> int | None:
        """Index that :meth:`advance` would move to, without moving."""
        if not self._paths:
            return None
        if auto and self.repeat is RepeatMode.ONE and self.current_index is not None:
            return self.current_index
        if self._up_next:
            return self._up_next[0]
        nxt = self._pos + 1
        if nxt < len(self._order):
            return self._order[nxt]
        if self.repeat is RepeatMode.ALL and self._order:
            return self._order[0]
        return None

    def advance(self, auto: bool = True) -> str | None:
        """Move to the next track.

        ``auto`` is True when the previous song finished on its own (repeat-one
        applies) and False when the user pressed Next.
        """
        if not self._paths:
            return None
        if auto and self.repeat is RepeatMode.ONE and self.current_index is not None:
            return self.current_path
        if self.current_index is not None:
            self._history.append(self.current_index)
        if self._up_next:
            index = self._up_next.pop(0)
            if self._shuffle:
                self._order.remove(index)
                self._order.insert(self._pos + 1, index)
                self._pos += 1
            else:
                self._pos = index
            return self._paths[index]
        if self._pos + 1 < len(self._order):
            self._pos += 1
            return self.current_path
        if self.repeat is RepeatMode.ALL:
            # The shuffled cycle repeats as-is so peek_next() stays accurate
            # for gapless pre-loading.
            self._pos = 0
            return self.current_path
        return None

    def previous(self) -> str | None:
        if not self._paths:
            return None
        if self._shuffle and self._history:
            index = self._history.pop()
            if index < len(self._paths):
                self._pos = self._order.index(index)
                return self._paths[index]
        if self._pos > 0:
            self._pos -= 1
            return self.current_path
        if self.repeat is RepeatMode.ALL and self._order:
            self._pos = len(self._order) - 1
            return self.current_path
        return self.current_path

    def stop(self) -> None:
        """Forget the current position (used when the queue ends)."""
        self._pos = -1
