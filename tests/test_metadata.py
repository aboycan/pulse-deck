# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Metadata extraction, artwork and safe tag editing (requires Mutagen + ffmpeg)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess

import pytest

from tests.conftest import make_cover, make_tone

pytest.importorskip("mutagen")

from pulsedeck.library import metadata as md  # noqa: E402
from pulsedeck.library.artwork import ArtworkCache, find_folder_image  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def _audio_hash(path) -> str:  # noqa: ANN001
    """Hash of the decoded audio samples, independent of tags."""
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a",
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("ext", [".mp3", ".flac", ".ogg", ".m4a", ".opus"])
def test_read_tags_and_stream_info(tmp_path, ext):
    path = make_tone(tmp_path / f"t{ext}", seconds=2.0, title="Hello", artist="Someone", album="Record")
    info = md.read_metadata(path)
    assert info.title == "Hello" and info.artist == "Someone" and info.album == "Record"
    assert info.duration == pytest.approx(2.0, abs=0.15)
    assert info.sample_rate in (44100, 48000)
    assert info.channels == 2
    assert info.file_size == path.stat().st_size
    if ext in (".mp3", ".flac"):
        assert info.genre == "Test" and info.year.startswith("2024")
        assert info.track_number.startswith("3")
        assert info.bitrate > 0


@pytest.mark.parametrize("ext", [".mp3", ".flac"])
def test_embedded_artwork_extraction(tmp_path, ext):
    cover = make_cover(tmp_path / "c.png")
    path = make_tone(tmp_path / f"art{ext}", cover=cover)
    art = md.extract_artwork(path)
    assert art is not None
    data, mime = art
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and mime == "image/png"
    assert md.read_metadata(path).has_artwork


def test_artwork_cache_thumbnails_and_folder_images(tmp_path):
    cover = make_cover(tmp_path / "c.png")
    with_art = make_tone(tmp_path / "a.mp3", cover=cover)
    cache = ArtworkCache(tmp_path / "cache")
    thumb = cache.thumbnail(str(with_art), 32)
    assert thumb is not None and thumb.exists()
    assert cache.thumbnail(str(with_art), 32) == thumb  # cached

    folder = tmp_path / "album"
    folder.mkdir()
    plain = make_tone(folder / "b.mp3")
    assert cache.thumbnail(str(plain), 32) is None
    make_cover(folder / "Folder.JPG")
    assert find_folder_image(str(plain)) is not None
    assert cache.load_original(str(plain)) is not None


def test_scanning_does_not_modify_files(tmp_path):
    path = make_tone(tmp_path / "x.flac")
    before = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    md.read_metadata(path)
    md.extract_artwork(path)
    assert (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) == before


@pytest.mark.parametrize("ext", [".mp3", ".flac", ".m4a", ".ogg"])
def test_write_metadata_preserves_audio_and_backs_up_original(tmp_path, ext):
    path = make_tone(tmp_path / f"edit{ext}", title="Old", artist="Old Artist")
    audio_before = _audio_hash(path)
    info = md.write_metadata(str(path), {"title": "New Title", "artist": "New Artist", "composer": "Someone",
                                         "track_number": "5/12"})
    assert info.title == "New Title" and info.artist == "New Artist" and info.composer == "Someone"
    assert info.track_number.startswith("5")
    assert _audio_hash(path) == audio_before
    assert md.backup_path_for(str(path)).exists()
    restored = md.restore_original_metadata(str(path))
    assert restored.title == "Old" and restored.artist == "Old Artist"
    assert _audio_hash(path) == audio_before


def test_write_rejects_unknown_fields_and_leaves_no_temp_files(tmp_path):
    path = make_tone(tmp_path / "x.mp3")
    with pytest.raises(md.MetadataError):
        md.write_metadata(str(path), {"bitrate": "1"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.mp3"]


def test_corrupted_and_missing_files_raise_metadata_error(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"\x00garbage" * 50)
    with pytest.raises(md.MetadataError):
        md.read_metadata(bad)
    with pytest.raises(md.MetadataError):
        md.read_metadata(tmp_path / "missing.flac")
