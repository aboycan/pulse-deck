# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Album artwork lookup and on-disk thumbnail cache (Pillow).

Artwork comes only from local sources: images embedded in the audio file,
or a cover image sitting next to it in the same folder. Nothing is ever
downloaded and audio files are never modified.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from pulsedeck.core import platform
from pulsedeck.library import metadata

log = logging.getLogger(__name__)

FOLDER_IMAGE_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartsmall")
FOLDER_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")


def find_folder_image(audio_path: str) -> Path | None:
    folder = Path(audio_path).parent
    try:
        entries = {p.name.casefold(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return None
    for stem in FOLDER_IMAGE_NAMES:
        for ext in FOLDER_IMAGE_EXTS:
            match = entries.get(f"{stem}{ext}")
            if match:
                return match
    return None


class ArtworkCache:
    """Caches decoded, resized artwork as PNG files keyed by file identity."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or platform.cache_dir() / "artwork"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._missing: set[str] = set()

    def _key(self, audio_path: str, size: int) -> str:
        try:
            stat = os.stat(audio_path)
            ident = f"{platform.normalize_path(audio_path)}|{stat.st_size}|{int(stat.st_mtime)}|{size}"
        except OSError:
            ident = f"{platform.normalize_path(audio_path)}|{size}"
        return hashlib.sha1(ident.encode("utf-8")).hexdigest()  # noqa: S324

    def load_original(self, audio_path: str) -> bytes | None:
        """Full-resolution artwork bytes (embedded first, then folder image)."""
        try:
            embedded = metadata.extract_artwork(audio_path)
        except metadata.MetadataError:
            embedded = None
        if embedded:
            return embedded[0]
        folder_image = find_folder_image(audio_path)
        if folder_image:
            try:
                return folder_image.read_bytes()
            except OSError:
                return None
        return None

    def thumbnail(self, audio_path: str, size: int = 256) -> Path | None:
        """Path to a cached PNG no larger than ``size`` px, or None."""
        key = self._key(audio_path, size)
        target = self.directory / f"{key}.png"
        if target.exists():
            return target
        if key in self._missing:
            return None
        data = self.load_original(audio_path)
        if not data:
            self._missing.add(key)
            return None
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = image.convert("RGBA") if image.mode in ("P", "LA", "RGBA") else image.convert("RGB")
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                with self._lock:
                    tmp = target.with_suffix(".tmp")
                    image.save(tmp, format="PNG", optimize=True)
                    os.replace(tmp, target)
            return target
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            log.debug("Cannot decode artwork for %s: %s", audio_path, exc)
            self._missing.add(key)
            return None

    def clear(self) -> int:
        count = 0
        for file in self.directory.glob("*.png"):
            try:
                file.unlink()
                count += 1
            except OSError:
                pass
        self._missing.clear()
        return count
