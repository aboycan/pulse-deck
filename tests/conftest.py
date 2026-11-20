# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Shared fixtures. All audio used by the tests is synthesised on the fly."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FFMPEG = shutil.which("ffmpeg")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point every PulseDeck per-user directory at a temp folder."""
    home = tmp_path / "pulsedeck-home"
    monkeypatch.setenv("PULSEDECK_HOME", str(home))
    return home


def _ffmpeg(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def make_cover(path: Path, color=(200, 40, 90)) -> Path:  # noqa: ANN001
    from PIL import Image

    Image.new("RGB", (64, 64), color).save(path)
    return path


def make_tone(path: Path, seconds: float = 2.0, freq: int = 440, title: str = "Test Tone",
              artist: str = "PulseDeck Tests", album: str = "Synthetic", cover: Path | None = None,
              extra: dict[str, str] | None = None) -> Path:
    """Write a sine tone in the format implied by ``path``'s extension."""
    if FFMPEG is None:
        pytest.skip("ffmpeg is required to synthesise test audio")
    args = ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=44100"]
    if cover is not None:
        args += ["-i", str(cover)]
    args += ["-ac", "2"]
    ext = path.suffix.lower()
    codec = {".mp3": ["-c:a", "libmp3lame", "-b:a", "192k", "-id3v2_version", "3"],
             ".flac": ["-c:a", "flac"], ".ogg": ["-c:a", "libvorbis"], ".opus": ["-c:a", "libopus"],
             ".m4a": ["-c:a", "aac"], ".wav": ["-c:a", "pcm_s16le"]}[ext]
    if cover is not None:
        args += ["-map", "0:a", "-map", "1:v", "-c:v", "copy" if ext == ".flac" else "png",
                 "-disposition:v", "attached_pic", "-metadata:s:v", "comment=Cover (front)"]
    meta = {"title": title, "artist": artist, "album": album, "genre": "Test", "date": "2024", "track": "3"}
    meta.update(extra or {})
    for key, value in meta.items():
        args += ["-metadata", f"{key}={value}"]
    _ffmpeg(*args, *codec, str(path))
    return path


@pytest.fixture
def mp3_file(tmp_path) -> Path:
    return make_tone(tmp_path / "tone.mp3", title="MP3 Tone")


@pytest.fixture
def flac_file(tmp_path) -> Path:
    return make_tone(tmp_path / "tone.flac", title="FLAC Tone", freq=660)


@pytest.fixture
def music_folder(tmp_path) -> Path:
    root = tmp_path / "Music"
    (root / "Artist A" / "Album 1").mkdir(parents=True)
    (root / "Artist B").mkdir(parents=True)
    make_tone(root / "Artist A" / "Album 1" / "01.mp3", title="One", artist="Artist A", album="Album 1")
    make_tone(root / "Artist A" / "Album 1" / "02.flac", title="Two", artist="Artist A", album="Album 1")
    make_tone(root / "Artist B" / "song.ogg", title="Three", artist="Artist B", album="Other")
    (root / "notes.txt").write_text("not audio")
    return root
