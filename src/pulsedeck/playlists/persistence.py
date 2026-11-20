# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Session save/restore: which playlist and track were playing, and where."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from pulsedeck.core import platform
from pulsedeck.core.configuration import atomic_write_text

log = logging.getLogger(__name__)


@dataclass
class SessionState:
    playlist_id: str | None = None
    track_index: int | None = None
    track_path: str | None = None
    position: float = 0.0
    was_playing: bool = False
    queue_order: list[int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        names = {f.name for f in fields(cls)}
        state = cls(**{k: v for k, v in data.items() if k in names})
        if state.track_index is not None and not isinstance(state.track_index, int):
            state.track_index = None
        try:
            state.position = max(0.0, float(state.position or 0.0))
        except (TypeError, ValueError):
            state.position = 0.0
        return state


class SessionStore:
    FILE_NAME = "session.json"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or platform.data_dir() / self.FILE_NAME

    def save(self, state: SessionState) -> None:
        try:
            atomic_write_text(self.path, json.dumps(state.to_dict(), indent=2))
        except OSError:
            log.exception("Could not save session")

    def load(self) -> SessionState:
        """Never raises: a damaged session file yields an empty session."""
        if not self.path.exists():
            return SessionState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("session root is not an object")
            return SessionState.from_dict(data)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Ignoring damaged session file: %s", exc)
            return SessionState()

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def resolve_restore_index(entries_paths: list[str], state: SessionState) -> int | None:
    """Find the track to resume, tolerating playlist edits since the save."""
    idx = state.track_index
    if idx is not None and 0 <= idx < len(entries_paths) and (
        state.track_path is None or entries_paths[idx] == state.track_path
    ):
        return idx
    if state.track_path is not None:
        for i, path in enumerate(entries_paths):
            if path == state.track_path:
                return i
    return None
