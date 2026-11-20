# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Recursive folder scanning into the library database.

Scanning is read-only for audio files. Unchanged files (same size and
modification time) are skipped, so rescans of large libraries are fast.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

from pulsedeck.core import platform
from pulsedeck.core.database import LibraryDatabase, content_signature
from pulsedeck.library.models import TrackInfo, is_audio_file

log = logging.getLogger(__name__)

MetadataReader = Callable[[str], TrackInfo]
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (skipped, existing)
    errors: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False

    def merge(self, other: ScanResult) -> None:
        self.added += other.added
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.removed += other.removed
        self.duplicates += other.duplicates
        self.errors += other.errors
        self.cancelled = self.cancelled or other.cancelled

    @property
    def summary(self) -> str:
        parts = [f"{self.added} added", f"{self.updated} updated", f"{self.removed} removed"]
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} duplicates skipped")
        if self.errors:
            parts.append(f"{len(self.errors)} unreadable")
        return ", ".join(parts)


def iter_audio_files(folder: str) -> Iterator[str]:
    """Yield audio files below ``folder``; follows no symlinked directories."""
    stack = [folder]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        key = platform.normalize_path(current)
        if key in visited:
            continue
        visited.add(key)
        try:
            with os.scandir(current) as entries:
                dirs: list[str] = []
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs.append(entry.path)
                        elif entry.is_file() and is_audio_file(entry.name):
                            yield entry.path
                    except OSError:
                        continue
                stack.extend(sorted(dirs, reverse=True))
        except OSError as exc:
            log.warning("Cannot read folder %s: %s", current, exc)


class LibraryScanner:
    def __init__(self, db: LibraryDatabase, reader: MetadataReader | None = None,
                 duplicate_mode: str = "path+metadata") -> None:
        if reader is None:
            from pulsedeck.library.metadata import read_metadata  # noqa: PLC0415

            reader = read_metadata
        self.db = db
        self.reader = reader
        self.duplicate_mode = duplicate_mode

    def scan_folder(self, folder: str, progress: ProgressCallback | None = None,
                    cancel: threading.Event | None = None) -> ScanResult:
        folder = os.path.abspath(folder)
        folder_id = self.db.add_folder(folder)
        files = list(iter_audio_files(folder))
        result, seen = self._process(files, folder_id, progress, cancel)
        if not result.cancelled:
            result.removed = self.db.remove_missing(folder, seen)
            self.db.mark_folder_scanned(folder)
        return result

    def rescan_all(self, progress: ProgressCallback | None = None,
                   cancel: threading.Event | None = None) -> ScanResult:
        total = ScanResult()
        for folder in self.db.folders():
            if cancel and cancel.is_set():
                total.cancelled = True
                break
            if not os.path.isdir(folder):
                log.warning("Library folder missing: %s", folder)
                continue
            total.merge(self.scan_folder(folder, progress, cancel))
        return total

    def add_files(self, paths: Iterable[str], progress: ProgressCallback | None = None,
                  cancel: threading.Event | None = None) -> ScanResult:
        files = [os.path.abspath(p) for p in paths if is_audio_file(p)]
        result, _ = self._process(files, None, progress, cancel)
        return result

    def _process(self, files: list[str], folder_id: int | None, progress: ProgressCallback | None,
                 cancel: threading.Event | None) -> tuple[ScanResult, set[str]]:
        result = ScanResult()
        seen: set[str] = set()
        total = len(files)
        for index, path in enumerate(files, start=1):
            if cancel and cancel.is_set():
                result.cancelled = True
                break
            if progress and (index == 1 or index % 25 == 0 or index == total):
                progress(index, total, path)
            key = platform.normalize_path(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                stat = os.stat(path)
            except OSError as exc:
                result.errors.append((path, str(exc)))
                continue
            previous = self.db.get_scan_state(key)
            if previous and previous[0] == stat.st_size and abs(previous[1] - stat.st_mtime) < 1e-3:
                result.unchanged += 1
                continue
            try:
                info = self.reader(path)
            except Exception as exc:  # corrupted/unsupported files must not stop the scan
                result.errors.append((path, str(exc)))
                continue
            if previous is None and self.duplicate_mode == "path+metadata":
                existing = self.db.find_duplicate_by_signature(content_signature(info), key)
                if existing and os.path.exists(existing):
                    result.duplicates.append((path, existing))
                    continue
            self.db.upsert_track(info, folder_id)
            if previous is None:
                result.added += 1
            else:
                result.updated += 1
        return result, seen
