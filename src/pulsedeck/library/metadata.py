# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Reading and safely editing audio metadata with Mutagen.

Reading never modifies files. Editing writes to a temporary copy, verifies
the copy can be read back, and only then replaces the original, so a crash
or a Mutagen error can never leave a half-written file. The tags that were
present before the first edit are saved as JSON so they can be restored.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pulsedeck.core import platform
from pulsedeck.core.configuration import atomic_write_text
from pulsedeck.library.models import TrackInfo

log = logging.getLogger(__name__)

try:  # Mutagen is a hard runtime dependency, but keep imports lazy-tolerant for tooling.
    import mutagen
    from mutagen.flac import Picture
    MUTAGEN_AVAILABLE = True
except ImportError:  # pragma: no cover
    mutagen = None  # type: ignore[assignment]
    Picture = None  # type: ignore[assignment,misc]
    MUTAGEN_AVAILABLE = False


class MetadataError(Exception):
    pass


#: Fields the metadata editor exposes.
EDITABLE_FIELDS = (
    "title", "artist", "album_artist", "album", "genre", "year",
    "track_number", "disc_number", "composer", "copyright",
)

_ID3_FRAMES = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "album_artist": "TPE2",
    "genre": "TCON", "year": "TDRC", "track_number": "TRCK", "disc_number": "TPOS",
    "composer": "TCOM", "copyright": "TCOP",
}
_VORBIS_KEYS = {
    "title": "title", "artist": "artist", "album": "album", "album_artist": "albumartist",
    "genre": "genre", "year": "date", "track_number": "tracknumber", "disc_number": "discnumber",
    "composer": "composer", "copyright": "copyright",
}
_MP4_KEYS = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "album_artist": "aART",
    "genre": "\xa9gen", "year": "\xa9day", "composer": "\xa9wrt", "copyright": "cprt",
}
_ASF_KEYS = {
    "title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "album_artist": "WM/AlbumArtist",
    "genre": "WM/Genre", "year": "WM/Year", "track_number": "WM/TrackNumber",
    "disc_number": "WM/PartOfSet", "composer": "WM/Composer", "copyright": "Copyright",
}


def _require_mutagen() -> None:
    if not MUTAGEN_AVAILABLE:
        raise MetadataError("Mutagen is not installed")


def _first(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        value = value[0]
    if hasattr(value, "text"):  # ID3 frame
        return _first(value.text)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value).strip()


def _parse_gain(value: str) -> float | None:
    try:
        return float(value.lower().replace("db", "").strip())
    except (AttributeError, ValueError):
        return None


def _container(audio: Any) -> str:
    return type(audio).__module__.rsplit(".", 1)[-1]


def read_metadata(path: str | os.PathLike[str]) -> TrackInfo:
    """Read tags and stream info. Raises :class:`MetadataError` on failure."""
    _require_mutagen()
    path = os.fspath(path)
    try:
        stat = os.stat(path)
    except OSError as exc:
        raise MetadataError(f"Cannot access file: {exc.strerror or exc}") from exc
    info = TrackInfo(path=path, file_size=stat.st_size, mtime=stat.st_mtime)
    try:
        audio = mutagen.File(path)
    except Exception as exc:  # Mutagen raises many exception types for corrupt files
        raise MetadataError(f"Unreadable or corrupted file: {exc}") from exc
    if audio is None:
        raise MetadataError("Unsupported or unrecognised audio format")

    stream = getattr(audio, "info", None)
    if stream is not None:
        info.duration = float(getattr(stream, "length", 0.0) or 0.0)
        info.bitrate = int(getattr(stream, "bitrate", 0) or 0)
        info.sample_rate = int(getattr(stream, "sample_rate", 0) or 0)
        info.channels = int(getattr(stream, "channels", 0) or 0)
        info.codec = str(getattr(stream, "codec", "") or "") or _container(audio)
        if not info.bitrate and info.duration > 0:
            info.bitrate = int(stat.st_size * 8 / info.duration)
        if not info.sample_rate and _container(audio) == "oggopus":
            # Mutagen doesn't report a rate for Opus because Opus always decodes at 48 kHz.
            info.sample_rate = 48_000

    tags = audio.tags
    kind = _container(audio)
    if tags is not None:
        if kind in ("mp3", "aiff", "wave", "id3") or hasattr(tags, "getall"):
            _read_id3(tags, info)
        elif kind == "mp4":
            _read_mp4(tags, info)
        elif kind == "asf":
            _read_asf(tags, info)
        else:
            _read_vorbis(tags, info)
    info.has_artwork = extract_artwork(path, audio=audio) is not None
    return info


def _read_id3(tags: Any, info: TrackInfo) -> None:
    for field, frame in _ID3_FRAMES.items():
        if frame in tags:
            setattr(info, field, _first(tags[frame]))
    for frame in tags.getall("TXXX"):
        desc = (frame.desc or "").lower()
        if desc == "replaygain_track_gain":
            info.replaygain_track_gain = _parse_gain(_first(frame))
        elif desc == "replaygain_album_gain":
            info.replaygain_album_gain = _parse_gain(_first(frame))


def _read_vorbis(tags: Any, info: TrackInfo) -> None:
    lowered = {k.lower(): v for k, v in tags.items()} if hasattr(tags, "items") else {}
    for field, key in _VORBIS_KEYS.items():
        if key in lowered:
            setattr(info, field, _first(lowered[key]))
    if "replaygain_track_gain" in lowered:
        info.replaygain_track_gain = _parse_gain(_first(lowered["replaygain_track_gain"]))
    if "replaygain_album_gain" in lowered:
        info.replaygain_album_gain = _parse_gain(_first(lowered["replaygain_album_gain"]))


def _read_mp4(tags: Any, info: TrackInfo) -> None:
    for field, key in _MP4_KEYS.items():
        if key in tags:
            setattr(info, field, _first(tags[key]))
    for field, key in (("track_number", "trkn"), ("disc_number", "disk")):
        if key in tags and tags[key]:
            number, total = (tuple(tags[key][0]) + (0, 0))[:2]
            setattr(info, field, f"{number}/{total}" if total else str(number))
    for key, attr in (("replaygain_track_gain", "replaygain_track_gain"),
                      ("replaygain_album_gain", "replaygain_album_gain")):
        full = f"----:com.apple.iTunes:{key}"
        if full in tags:
            setattr(info, attr, _parse_gain(_first(tags[full])))


def _read_asf(tags: Any, info: TrackInfo) -> None:
    for field, key in _ASF_KEYS.items():
        if key in tags:
            setattr(info, field, _first(tags[key]))


# -- artwork ---------------------------------------------------------------
def extract_artwork(path: str | os.PathLike[str], audio: Any = None) -> tuple[bytes, str] | None:
    """Return ``(image_bytes, mime_type)`` for embedded cover art, if any.

    The front cover is preferred when a file carries several pictures.
    """
    _require_mutagen()
    if audio is None:
        try:
            audio = mutagen.File(os.fspath(path))
        except Exception:
            return None
        if audio is None:
            return None
    candidates: list[tuple[int, bytes, str]] = []  # (picture type, data, mime)

    pictures = getattr(audio, "pictures", None)  # FLAC
    if pictures:
        candidates += [(p.type, p.data, p.mime) for p in pictures]
    tags = audio.tags
    if tags is not None:
        if hasattr(tags, "getall"):  # ID3
            candidates += [(f.type, f.data, f.mime) for f in tags.getall("APIC")]
        elif _container(audio) == "mp4" and "covr" in tags:
            for cover in tags["covr"]:
                mime = "image/png" if getattr(cover, "imageformat", 0) == 14 else "image/jpeg"
                candidates.append((3, bytes(cover), mime))
        elif _container(audio) == "asf" and "WM/Picture" in tags:
            for value in tags["WM/Picture"]:
                parsed = _parse_asf_picture(bytes(value.value))
                if parsed:
                    candidates.append((3, parsed[0], parsed[1]))
        elif hasattr(tags, "get"):
            for raw in tags.get("metadata_block_picture", []) or []:
                try:
                    pic = Picture(base64.b64decode(raw))
                    candidates.append((pic.type, pic.data, pic.mime))
                except Exception:
                    continue
    if not candidates:
        return None
    candidates.sort(key=lambda c: 0 if c[0] == 3 else 1)
    _, data, mime = candidates[0]
    return (bytes(data), mime or "image/jpeg") if data else None


def _parse_asf_picture(data: bytes) -> tuple[bytes, str] | None:
    """Decode a WM/Picture blob: type(1) size(4) mime(utf16z) desc(utf16z) data."""
    try:
        pos = 5
        end = data.index(b"\x00\x00", pos)
        while (end - pos) % 2:
            end = data.index(b"\x00\x00", end + 1)
        mime = data[pos:end].decode("utf-16-le")
        pos = end + 2
        end = data.index(b"\x00\x00", pos)
        while (end - pos) % 2:
            end = data.index(b"\x00\x00", end + 1)
        pos = end + 2
        return data[pos:], mime or "image/jpeg"
    except (ValueError, UnicodeDecodeError):
        return None


# -- editing ---------------------------------------------------------------
def _backup_dir() -> Path:
    path = platform.data_dir() / "metadata_backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_path_for(path: str) -> Path:
    digest = hashlib.sha1(platform.normalize_path(path).encode("utf-8")).hexdigest()  # noqa: S324
    return _backup_dir() / f"{digest}.json"


def save_original_metadata(path: str) -> Path:
    """Store the current tag values once; later edits keep the first snapshot."""
    target = backup_path_for(path)
    if not target.exists():
        current = read_metadata(path)
        snapshot = {"path": path, "fields": {f: getattr(current, f) for f in EDITABLE_FIELDS}}
        atomic_write_text(target, json.dumps(snapshot, indent=2, ensure_ascii=False))
    return target


def write_metadata(path: str, changes: dict[str, str]) -> TrackInfo:
    """Apply tag ``changes`` safely and return the re-read metadata."""
    _require_mutagen()
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise MetadataError(f"Not editable: {', '.join(sorted(unknown))}")
    if not os.access(path, os.W_OK):
        raise MetadataError("The file is read-only")
    save_original_metadata(path)

    directory = os.path.dirname(os.path.abspath(path))
    suffix = os.path.splitext(path)[1]
    fd, tmp = tempfile.mkstemp(prefix=".pulsedeck-tag-", suffix=suffix, dir=directory)
    os.close(fd)
    try:
        shutil.copy2(path, tmp)
        _apply_tags(tmp, changes)
        read_metadata(tmp)  # verify the result is still a valid file
        os.replace(tmp, path)
    except MetadataError:
        _silent_unlink(tmp)
        raise
    except Exception as exc:
        _silent_unlink(tmp)
        raise MetadataError(f"Could not save tags: {exc}") from exc
    return read_metadata(path)


def restore_original_metadata(path: str) -> TrackInfo:
    backup = backup_path_for(path)
    if not backup.exists():
        raise MetadataError("No saved original metadata for this file")
    data = json.loads(backup.read_text(encoding="utf-8"))
    info = write_metadata(path, {k: str(v) for k, v in data.get("fields", {}).items()})
    backup.unlink(missing_ok=True)
    return info


def _silent_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _apply_tags(path: str, changes: dict[str, str]) -> None:
    audio = mutagen.File(path)
    if audio is None:
        raise MetadataError("Unsupported format for tag editing")
    kind = _container(audio)
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception as exc:
            raise MetadataError(f"This file cannot hold tags: {exc}") from exc
    tags = audio.tags
    if hasattr(tags, "getall"):  # ID3 in MP3/AIFF/WAV
        from mutagen import id3  # noqa: PLC0415

        for field, value in changes.items():
            frame_id = _ID3_FRAMES[field]
            tags.delall(frame_id)
            if value:
                tags.add(getattr(id3, frame_id)(encoding=3, text=[value]))
        audio.save(v2_version=4) if kind == "mp3" else audio.save()
        return
    if kind == "mp4":
        for field, value in changes.items():
            if field in ("track_number", "disc_number"):
                key = "trkn" if field == "track_number" else "disk"
                if not value:
                    tags.pop(key, None)
                    continue
                number, _, total = value.partition("/")
                try:
                    tags[key] = [(int(number or 0), int(total or 0))]
                except ValueError as exc:
                    raise MetadataError(f"Invalid {field.replace('_', ' ')}: {value}") from exc
                continue
            key = _MP4_KEYS[field]
            if value:
                tags[key] = [value]
            else:
                tags.pop(key, None)
        audio.save()
        return
    if kind == "asf":
        for field, value in changes.items():
            key = _ASF_KEYS[field]
            if value:
                tags[key] = [value]
            elif key in tags:
                del tags[key]
        audio.save()
        return
    # Vorbis comments (FLAC, Ogg Vorbis, Opus)
    for field, value in changes.items():
        key = _VORBIS_KEYS[field]
        if value:
            tags[key] = [value]
        elif key in tags:
            del tags[key]
    audio.save()
