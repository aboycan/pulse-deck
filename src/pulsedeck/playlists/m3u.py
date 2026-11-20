# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""M3U / M3U8 playlist reading and writing.

Supports the extended format (``#EXTM3U``, ``#EXTINF``, ``#PLAYLIST``),
relative and absolute paths, ``file://`` URIs and playlists written on a
different operating system (backslash separators). PulseDeck stores its
shuffle preference in a ``#PULSEDECK-SHUFFLE`` comment that other players
ignore.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlparse

from pulsedeck.core.configuration import atomic_write_text
from pulsedeck.playlists.model import Playlist, PlaylistEntry

_EXTINF = re.compile(r"^#EXTINF:\s*(-?\d+(?:\.\d+)?)[^,]*,(.*)$", re.IGNORECASE)
_URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]+://", re.IGNORECASE)


def _decode(raw: bytes, path: Path) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        if path.suffix.lower() == ".m3u8":
            return raw.decode("utf-8", "replace")
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


def resolve_entry_path(line: str, base_dir: Path) -> str:
    line = line.strip()
    if line.lower().startswith("file://"):
        parsed = urlparse(line)
        local = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", local):  # file:///C:/...
            local = local[1:]
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            local = f"//{parsed.netloc}{local}"  # UNC
        return os.path.normpath(local)
    if _URL_SCHEME.match(line):
        return line  # stream URL; kept verbatim
    if os.sep == "/" and "\\" in line:
        win = PureWindowsPath(line)
        if win.drive or win.root:
            return line  # absolute Windows path on POSIX: keep (will show as missing)
        line = "/".join(win.parts)
    candidate = Path(line)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return os.path.normpath(str(candidate))


def read_m3u(path: str | os.PathLike[str]) -> Playlist:
    playlist_path = Path(path)
    text = _decode(playlist_path.read_bytes(), playlist_path)
    base_dir = playlist_path.parent
    name = playlist_path.stem
    shuffle = False
    entries: list[PlaylistEntry] = []
    pending: tuple[float, str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            upper = line.upper()
            match = _EXTINF.match(line)
            if match:
                duration = max(0.0, float(match.group(1)))
                label = match.group(2).strip()
                artist, sep, title = label.partition(" - ")
                pending = (duration, title.strip(), artist.strip()) if sep else (duration, label, "")
            elif upper.startswith("#PLAYLIST:"):
                name = line.split(":", 1)[1].strip() or name
            elif upper.startswith("#PULSEDECK-SHUFFLE:"):
                shuffle = line.split(":", 1)[1].strip() in ("1", "true", "yes")
            continue
        entry = PlaylistEntry(resolve_entry_path(line, base_dir))
        if pending:
            entry.duration, entry.title, entry.artist = pending
            pending = None
        entries.append(entry)
    return Playlist(name=name, entries=entries, shuffle=shuffle)


def _relative_or_absolute(entry_path: str, base_dir: Path, relative: bool) -> str:
    if not relative or _URL_SCHEME.match(entry_path):
        return entry_path
    try:
        rel = os.path.relpath(entry_path, base_dir)
    except ValueError:  # different drive on Windows
        return entry_path
    if rel.startswith(".." + os.sep + ".." + os.sep + ".."):
        return entry_path
    return rel


def write_m3u(playlist: Playlist, path: str | os.PathLike[str], relative: bool = True) -> None:
    target = Path(path)
    base_dir = target.parent.resolve()
    lines = ["#EXTM3U", f"#PLAYLIST:{playlist.name}"]
    if playlist.shuffle:
        lines.append("#PULSEDECK-SHUFFLE:1")
    for entry in playlist.entries:
        label = f"{entry.artist} - {entry.display_title}" if entry.artist else entry.display_title
        seconds = int(round(entry.duration)) if entry.duration else -1
        lines.append(f"#EXTINF:{seconds},{label}")
        lines.append(_relative_or_absolute(entry.path, base_dir, relative))
    atomic_write_text(target, "\n".join(lines) + "\n")
