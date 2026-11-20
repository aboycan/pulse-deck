# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Collection of saved playlists stored as native JSON files."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path

from pulsedeck.core import platform
from pulsedeck.core.configuration import atomic_write_text
from pulsedeck.library.models import is_audio_file
from pulsedeck.playlists import m3u
from pulsedeck.playlists.model import Playlist

log = logging.getLogger(__name__)

IMPORT_EXTENSIONS = (".m3u", ".m3u8", ".json")


class PlaylistError(Exception):
    pass


def load_playlist_file(path: str | os.PathLike[str]) -> Playlist:
    suffix = Path(path).suffix.lower()
    try:
        if suffix in (".m3u", ".m3u8"):
            return m3u.read_m3u(path)
        if suffix == ".json":
            return Playlist.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as exc:
        raise PlaylistError(f"Cannot open playlist: {exc}") from exc
    raise PlaylistError(f"Unsupported playlist format: {suffix}")


def save_playlist_file(playlist: Playlist, path: str | os.PathLike[str]) -> None:
    suffix = Path(path).suffix.lower()
    if suffix in (".m3u", ".m3u8"):
        m3u.write_m3u(playlist, path)
    elif suffix == ".json":
        atomic_write_text(Path(path), json.dumps(playlist.to_dict(), indent=2, ensure_ascii=False))
    else:
        raise PlaylistError(f"Unsupported playlist format: {suffix}")


def relink_missing(playlist: Playlist, search_roots: Iterable[str], max_files: int = 200_000) -> int:
    """Re-point missing entries to a file with the same name under ``search_roots``.

    Only unambiguous matches (exactly one candidate) are relinked.
    """
    missing = {i: os.path.basename(e.path).casefold() for i, e in enumerate(playlist.entries) if not e.exists}
    if not missing:
        return 0
    wanted = set(missing.values())
    found: dict[str, list[str]] = {}
    scanned = 0
    for root in search_roots:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                scanned += 1
                key = name.casefold()
                if key in wanted:
                    found.setdefault(key, []).append(os.path.join(dirpath, name))
            if scanned > max_files:
                break
    fixed = 0
    for index, name in missing.items():
        matches = found.get(name, [])
        if len(matches) == 1:
            playlist.entries[index].path = matches[0]
            fixed += 1
    if fixed:
        playlist.touch()
    return fixed


class PlaylistManager:
    ORDER_FILE = "order.json"

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or platform.data_dir() / "playlists"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._playlists: dict[str, Playlist] = {}
        self._order: list[str] = []
        self.load()

    # -- persistence -----------------------------------------------------
    def load(self) -> None:
        self._playlists.clear()
        for file in self.directory.glob("*.json"):
            if file.name == self.ORDER_FILE:
                continue
            try:
                playlist = Playlist.from_dict(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                log.warning("Skipping unreadable playlist %s: %s", file, exc)
                continue
            self._playlists[playlist.id] = playlist
        order_path = self.directory / self.ORDER_FILE
        order: list[str] = []
        if order_path.exists():
            try:
                order = [i for i in json.loads(order_path.read_text(encoding="utf-8")) if i in self._playlists]
            except (OSError, ValueError):
                order = []
        rest = sorted((p for p in self._playlists.values() if p.id not in order), key=lambda p: p.created)
        self._order = order + [p.id for p in rest]
        if not self._playlists:
            self.create("Default")

    def save(self, playlist: Playlist) -> None:
        if playlist.id not in self._playlists:
            self._playlists[playlist.id] = playlist
            self._order.append(playlist.id)
            self._save_order()
        atomic_write_text(self.directory / f"{playlist.id}.json",
                          json.dumps(playlist.to_dict(), indent=2, ensure_ascii=False))

    def save_all(self) -> None:
        for playlist in self._playlists.values():
            self.save(playlist)
        self._save_order()

    def _save_order(self) -> None:
        atomic_write_text(self.directory / self.ORDER_FILE, json.dumps(self._order))

    # -- queries ---------------------------------------------------------
    def all(self) -> list[Playlist]:
        return [self._playlists[i] for i in self._order if i in self._playlists]

    def get(self, playlist_id: str) -> Playlist | None:
        return self._playlists.get(playlist_id)

    def find_by_name(self, name: str) -> Playlist | None:
        for playlist in self.all():
            if playlist.name.casefold() == name.casefold():
                return playlist
        return None

    def unique_name(self, base: str) -> str:
        names = {p.name.casefold() for p in self._playlists.values()}
        if base.casefold() not in names:
            return base
        n = 2
        while f"{base} {n}".casefold() in names:
            n += 1
        return f"{base} {n}"

    # -- mutations -------------------------------------------------------
    def create(self, name: str = "New playlist") -> Playlist:
        playlist = Playlist(name=self.unique_name(name.strip() or "New playlist"))
        self.save(playlist)
        return playlist

    def rename(self, playlist_id: str, name: str) -> Playlist:
        playlist = self._require(playlist_id)
        name = name.strip()
        if not name:
            raise PlaylistError("Playlist name cannot be empty")
        playlist.name = name
        playlist.touch()
        self.save(playlist)
        return playlist

    def delete(self, playlist_id: str) -> None:
        self._require(playlist_id)
        del self._playlists[playlist_id]
        self._order.remove(playlist_id)
        try:
            (self.directory / f"{playlist_id}.json").unlink()
        except FileNotFoundError:
            pass
        self._save_order()
        if not self._playlists:
            self.create("Default")

    def duplicate(self, playlist_id: str) -> Playlist:
        source = self._require(playlist_id)
        copy = source.duplicate(self.unique_name(f"{source.name} (copy)"))
        self.save(copy)
        index = self._order.index(copy.id)
        self._order.insert(self._order.index(source.id) + 1, self._order.pop(index))
        self._save_order()
        return copy

    def reorder(self, ids: list[str]) -> None:
        if set(ids) == set(self._order):
            self._order = list(ids)
            self._save_order()

    def import_file(self, path: str | os.PathLike[str]) -> Playlist:
        playlist = load_playlist_file(path)
        imported = Playlist(name=self.unique_name(playlist.name), entries=playlist.entries,
                            shuffle=playlist.shuffle)
        self.save(imported)
        return imported

    def export(self, playlist_id: str, path: str | os.PathLike[str]) -> None:
        save_playlist_file(self._require(playlist_id), path)

    def _require(self, playlist_id: str) -> Playlist:
        playlist = self._playlists.get(playlist_id)
        if playlist is None:
            raise PlaylistError("Playlist not found")
        return playlist


def collect_audio_files(paths: Iterable[str]) -> list[str]:
    """Expand files and folders (recursively) into a sorted list of audio files."""
    from pulsedeck.library.scanner import iter_audio_files  # noqa: PLC0415

    result: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            result.extend(sorted(iter_audio_files(path), key=lambda p: p.casefold()))
        elif is_audio_file(path):
            result.append(os.path.abspath(path))
    return result
