# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""SQLite storage for the music library, favourites and playback history."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pulsedeck.core import platform
from pulsedeck.library.models import TrackInfo

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_TRACK_COLUMNS = (
    "path", "path_key", "title", "artist", "album", "album_artist", "genre", "year",
    "track_number", "disc_number", "composer", "copyright", "duration", "bitrate",
    "sample_rate", "channels", "file_size", "mtime", "codec", "has_artwork",
    "replaygain_track_gain", "replaygain_album_gain",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    added_at REAL NOT NULL,
    last_scan REAL
);
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    path_key TEXT NOT NULL UNIQUE,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    title TEXT DEFAULT '', artist TEXT DEFAULT '', album TEXT DEFAULT '',
    album_artist TEXT DEFAULT '', genre TEXT DEFAULT '', year TEXT DEFAULT '',
    track_number TEXT DEFAULT '', disc_number TEXT DEFAULT '',
    composer TEXT DEFAULT '', copyright TEXT DEFAULT '',
    duration REAL DEFAULT 0, bitrate INTEGER DEFAULT 0, sample_rate INTEGER DEFAULT 0,
    channels INTEGER DEFAULT 0, file_size INTEGER DEFAULT 0, mtime REAL DEFAULT 0,
    codec TEXT DEFAULT '', has_artwork INTEGER DEFAULT 0,
    replaygain_track_gain REAL, replaygain_album_gain REAL,
    content_sig TEXT DEFAULT '',
    favourite INTEGER DEFAULT 0,
    play_count INTEGER DEFAULT 0,
    last_played REAL,
    added_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tracks_sig ON tracks(content_sig);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    path_key TEXT NOT NULL,
    path TEXT NOT NULL,
    played_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_played ON history(played_at);
CREATE TABLE IF NOT EXISTS favourites (
    path_key TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    added_at REAL NOT NULL
);
"""


def content_signature(info: TrackInfo) -> str:
    """Metadata fingerprint used to spot the same song stored twice."""
    if not (info.title or info.artist) or not info.duration:
        return ""
    return "|".join(
        [
            info.title.strip().casefold(),
            info.artist.strip().casefold(),
            info.album.strip().casefold(),
            str(int(round(info.duration))),
        ]
    )


class LibraryDatabase:
    FILE_NAME = "library.sqlite3"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or platform.data_dir() / self.FILE_NAME
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)))

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    # -- folders ---------------------------------------------------------
    def add_folder(self, path: str) -> int:
        self._exec("INSERT OR IGNORE INTO folders(path, added_at) VALUES(?, ?)", (path, time.time()))
        return int(self._query("SELECT id FROM folders WHERE path=?", (path,))[0]["id"])

    def folders(self) -> list[str]:
        return [r["path"] for r in self._query("SELECT path FROM folders ORDER BY path")]

    def remove_folder(self, path: str, remove_tracks: bool = True) -> int:
        rows = self._query("SELECT id FROM folders WHERE path=?", (path,))
        if not rows:
            return 0
        folder_id = rows[0]["id"]
        removed = 0
        with self.transaction() as conn:
            if remove_tracks:
                removed = conn.execute("DELETE FROM tracks WHERE folder_id=?", (folder_id,)).rowcount
            conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        return removed

    def mark_folder_scanned(self, path: str) -> None:
        self._exec("UPDATE folders SET last_scan=? WHERE path=?", (time.time(), path))

    # -- tracks ----------------------------------------------------------
    def get_scan_state(self, path_key: str) -> tuple[int, float] | None:
        rows = self._query("SELECT file_size, mtime FROM tracks WHERE path_key=?", (path_key,))
        return (int(rows[0]["file_size"]), float(rows[0]["mtime"])) if rows else None

    def find_duplicate_by_signature(self, sig: str, exclude_key: str) -> str | None:
        if not sig:
            return None
        rows = self._query(
            "SELECT path FROM tracks WHERE content_sig=? AND path_key<>? LIMIT 1", (sig, exclude_key)
        )
        return rows[0]["path"] if rows else None

    def upsert_track(self, info: TrackInfo, folder_id: int | None = None) -> int:
        key = platform.normalize_path(info.path)
        values = {c: getattr(info, c) for c in _TRACK_COLUMNS if c != "path_key"}
        values["path_key"] = key
        values["has_artwork"] = int(bool(info.has_artwork))
        values["content_sig"] = content_signature(info)
        cols = list(values)
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "path_key")
        sql = (
            f"INSERT INTO tracks({','.join(cols)}, folder_id, added_at) VALUES({placeholders}, ?, ?) "
            f"ON CONFLICT(path_key) DO UPDATE SET {updates}, "
            f"folder_id=COALESCE(excluded.folder_id, tracks.folder_id)"
        )
        self._exec(sql, [values[c] for c in cols] + [folder_id, time.time()])
        favourite = self._query("SELECT 1 FROM favourites WHERE path_key=?", (key,))
        if favourite:
            self._exec("UPDATE tracks SET favourite=1 WHERE path_key=?", (key,))
        return int(self._query("SELECT id FROM tracks WHERE path_key=?", (key,))[0]["id"])

    def remove_track(self, path: str) -> bool:
        return self._exec("DELETE FROM tracks WHERE path_key=?", (platform.normalize_path(path),)).rowcount > 0

    def remove_missing(self, folder: str, seen_keys: set[str]) -> int:
        rows = self._query(
            "SELECT t.path_key FROM tracks t JOIN folders f ON f.id=t.folder_id WHERE f.path=?", (folder,)
        )
        stale = [r["path_key"] for r in rows if r["path_key"] not in seen_keys]
        with self.transaction() as conn:
            for key in stale:
                conn.execute("DELETE FROM tracks WHERE path_key=?", (key,))
        return len(stale)

    def get_track(self, path: str) -> TrackInfo | None:
        rows = self._query("SELECT * FROM tracks WHERE path_key=?", (platform.normalize_path(path),))
        return self._row_to_track(rows[0]) if rows else None

    def track_count(self) -> int:
        return int(self._query("SELECT COUNT(*) AS n FROM tracks")[0]["n"])

    def query_tracks(
        self,
        text: str = "",
        fields_: tuple[str, ...] = ("title", "artist", "album", "genre"),
        artist: str | None = None,
        album: str | None = None,
        genre: str | None = None,
        year: str | None = None,
        favourites_only: bool = False,
        order_by: str = "artist, album, CAST(disc_number AS INTEGER), CAST(track_number AS INTEGER), title",
        limit: int | None = None,
    ) -> list[TrackInfo]:
        where: list[str] = []
        params: list[Any] = []
        allowed = {"title", "artist", "album", "genre", "album_artist", "composer", "path", "year"}
        if text:
            terms = [t for t in text.split() if t]
            for term in terms:
                escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                like = f"%{escaped}%"
                parts = [f"{f} LIKE ? ESCAPE '\\'" for f in fields_ if f in allowed]
                where.append("(" + " OR ".join(parts) + ")")
                params.extend([like] * len(parts))
        for column, value in (("artist", artist), ("album", album), ("genre", genre), ("year", year)):
            if value is not None:
                where.append(f"{column} = ? COLLATE NOCASE")
                params.append(value)
        if favourites_only:
            where.append("favourite = 1")
        sql = "SELECT * FROM tracks"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_track(r) for r in self._query(sql, params)]

    def distinct_values(self, column: str) -> list[str]:
        if column not in {"artist", "album", "genre", "year", "album_artist"}:
            raise ValueError(column)
        rows = self._query(
            f"SELECT DISTINCT {column} AS v FROM tracks WHERE {column}<>'' ORDER BY {column} COLLATE NOCASE"
        )
        return [r["v"] for r in rows]

    def albums_for_artist(self, artist: str) -> list[str]:
        rows = self._query(
            "SELECT DISTINCT album FROM tracks WHERE (artist=? COLLATE NOCASE OR album_artist=? COLLATE NOCASE) "
            "AND album<>'' ORDER BY album COLLATE NOCASE",
            (artist, artist),
        )
        return [r["album"] for r in rows]

    # -- favourites and history -----------------------------------------
    def set_favourite(self, path: str, favourite: bool) -> None:
        key = platform.normalize_path(path)
        if favourite:
            self._exec(
                "INSERT OR IGNORE INTO favourites(path_key, path, added_at) VALUES(?, ?, ?)", (key, path, time.time())
            )
        else:
            self._exec("DELETE FROM favourites WHERE path_key=?", (key,))
        self._exec("UPDATE tracks SET favourite=? WHERE path_key=?", (int(favourite), key))

    def is_favourite(self, path: str) -> bool:
        return bool(self._query("SELECT 1 FROM favourites WHERE path_key=?", (platform.normalize_path(path),)))

    def favourites(self) -> list[str]:
        return [r["path"] for r in self._query("SELECT path FROM favourites ORDER BY added_at DESC")]

    def record_play(self, path: str) -> None:
        key = platform.normalize_path(path)
        now = time.time()
        with self.transaction() as conn:
            conn.execute("INSERT INTO history(path_key, path, played_at) VALUES(?, ?, ?)", (key, path, now))
            conn.execute(
                "UPDATE tracks SET play_count = play_count + 1, last_played=? WHERE path_key=?", (now, key)
            )

    def recently_played(self, limit: int = 100) -> list[str]:
        rows = self._query(
            "SELECT path, MAX(played_at) AS last FROM history GROUP BY path_key ORDER BY last DESC LIMIT ?", (limit,)
        )
        return [r["path"] for r in rows]

    def most_played(self, limit: int = 100) -> list[tuple[str, int]]:
        rows = self._query(
            "SELECT path, COUNT(*) AS n FROM history GROUP BY path_key ORDER BY n DESC, MAX(played_at) DESC LIMIT ?",
            (limit,),
        )
        return [(r["path"], int(r["n"])) for r in rows]

    def recently_added(self, limit: int = 100) -> list[TrackInfo]:
        return self.query_tracks(order_by="added_at DESC", limit=limit)

    def clear_history(self) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM history")
            conn.execute("UPDATE tracks SET play_count=0, last_played=NULL")

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _row_to_track(row: sqlite3.Row) -> TrackInfo:
        data = dict(row)
        data["has_artwork"] = bool(data.get("has_artwork"))
        data["favourite"] = bool(data.get("favourite"))
        return TrackInfo.from_dict(data)
