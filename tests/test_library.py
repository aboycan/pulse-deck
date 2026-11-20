# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Library database, folder scanning, duplicates, search, favourites and history."""

from __future__ import annotations

import os
import threading
import time

import pytest

from pulsedeck.core.database import LibraryDatabase
from pulsedeck.library.models import TrackInfo, format_duration, format_size, is_audio_file
from pulsedeck.library.scanner import LibraryScanner, iter_audio_files
from pulsedeck.library.search import matches, parse_query, search_library


def fake_reader(path: str) -> TrackInfo:
    """Metadata reader that derives tags from the file name: 'Artist - Title.ext'."""
    if "corrupt" in path:
        raise ValueError("Unreadable or corrupted file")
    stem = os.path.splitext(os.path.basename(path))[0]
    artist, _, title = stem.partition(" - ")
    stat = os.stat(path)
    return TrackInfo(path=path, title=title or stem, artist=artist if title else "", album=os.path.basename(
        os.path.dirname(path)), genre="Rock" if "rock" in path.lower() else "Jazz", year="2001", duration=180.0,
        file_size=stat.st_size, mtime=stat.st_mtime)


def _make(root, rel: str, content: bytes = b"data") -> str:  # noqa: ANN001
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


@pytest.fixture
def db(tmp_path):
    database = LibraryDatabase(tmp_path / "lib.sqlite3")
    yield database
    database.close()


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Music"
    _make(root, "Rock Album/Band - First.mp3")
    _make(root, "Rock Album/Band - Second.flac")
    _make(root, "Jazz/Trio - Blue.ogg")
    _make(root, "Jazz/deep/nested/Trio - Late.m4a")
    _make(root, "Jazz/cover.jpg")
    _make(root, ".hidden/Ghost - Track.mp3")
    return root


def test_audio_extension_filter():
    for name in ("a.MP3", "b.flac", "c.wav", "d.aac", "e.m4a", "f.ogg", "g.opus", "h.wma", "i.aiff"):
        assert is_audio_file(name)
    assert not is_audio_file("cover.jpg")


def test_recursive_scan_finds_audio_only(library):
    names = sorted(os.path.basename(p) for p in iter_audio_files(str(library)))
    assert names == ["Band - First.mp3", "Band - Second.flac", "Trio - Blue.ogg", "Trio - Late.m4a"]


def test_scan_rescan_and_removal(db, library):
    scanner = LibraryScanner(db, reader=fake_reader)
    first = scanner.scan_folder(str(library))
    assert (first.added, first.updated, first.unchanged) == (4, 0, 0)
    assert db.track_count() == 4
    second = scanner.scan_folder(str(library))
    assert (second.added, second.unchanged) == (0, 4)

    changed = library / "Jazz" / "Trio - Blue.ogg"
    changed.write_bytes(b"different size now")
    os.remove(library / "Rock Album" / "Band - Second.flac")
    third = scanner.scan_folder(str(library))
    assert (third.updated, third.removed) == (1, 1)
    assert db.track_count() == 3


def test_scan_never_modifies_audio_files(db, library):
    files = list(iter_audio_files(str(library)))
    before = {f: (os.stat(f).st_mtime_ns, open(f, "rb").read()) for f in files}  # noqa: SIM115
    LibraryScanner(db, reader=fake_reader).scan_folder(str(library))
    assert {f: (os.stat(f).st_mtime_ns, open(f, "rb").read()) for f in files} == before  # noqa: SIM115


def test_duplicate_detection_by_path_and_metadata(db, tmp_path, library):
    scanner = LibraryScanner(db, reader=fake_reader)
    scanner.scan_folder(str(library))
    # Same path through a different spelling is the same track.
    alias = str(library / "Jazz" / ".." / "Jazz" / "Trio - Blue.ogg")
    result = scanner.add_files([alias])
    assert result.added == 0 and db.track_count() == 4
    # A copy elsewhere with identical tags is reported as a duplicate.
    other = tmp_path / "Elsewhere" / "Jazz"
    _make(other, "Trio - Blue.ogg", b"another copy")
    dup = scanner.scan_folder(str(tmp_path / "Elsewhere"))
    assert len(dup.duplicates) == 1 and db.track_count() == 4
    # With path-only detection the copy is added.
    path_only = LibraryScanner(db, reader=fake_reader, duplicate_mode="path").scan_folder(str(tmp_path / "Elsewhere"))
    assert path_only.added == 1


def test_unreadable_files_are_reported_not_fatal(db, library):
    _make(library, "Jazz/corrupt - file.mp3")
    result = LibraryScanner(db, reader=fake_reader).scan_folder(str(library))
    assert result.added == 4 and len(result.errors) == 1


def test_scan_can_be_cancelled(db, library):
    cancel = threading.Event()
    cancel.set()
    result = LibraryScanner(db, reader=fake_reader).scan_folder(str(library), cancel=cancel)
    assert result.cancelled and db.track_count() == 0


def test_remove_folder_removes_its_tracks(db, library):
    LibraryScanner(db, reader=fake_reader).scan_folder(str(library))
    assert db.folders() == [str(library)]
    assert db.remove_folder(str(library)) == 4
    assert db.track_count() == 0 and db.folders() == []


def test_filters_and_distinct_values(db, library):
    LibraryScanner(db, reader=fake_reader).scan_folder(str(library))
    assert db.distinct_values("artist") == ["Band", "Trio"]
    assert len(db.query_tracks(artist="band")) == 2
    assert len(db.query_tracks(genre="Jazz")) == 2
    assert len(db.query_tracks(album="nested")) == 1
    assert len(db.query_tracks(year="2001")) == 4
    assert db.albums_for_artist("Trio") == ["Jazz", "nested"]


def test_search_syntax(db, library):
    LibraryScanner(db, reader=fake_reader).scan_folder(str(library))
    assert [t.title for t in search_library(db, "blue")] == ["Blue"]
    assert {t.title for t in search_library(db, "artist:band")} == {"First", "Second"}
    assert [t.title for t in search_library(db, "trio late")] == ["Late"]
    assert search_library(db, "first", scope="artist") == []
    assert search_library(db, "100%_") == []  # LIKE wildcards are escaped
    q = parse_query('album:"rock album" first')
    assert q.fielded == [("album", "rock album")] and q.words == ["first"]
    assert matches(TrackInfo(path="/x/Song.mp3"), "song")


def test_favourites_history_most_played(db, library):
    LibraryScanner(db, reader=fake_reader).scan_folder(str(library))
    tracks = db.query_tracks()
    a, b = tracks[0].path, tracks[1].path
    db.set_favourite(a, True)
    assert db.is_favourite(a) and db.favourites() == [a]
    assert [t.path for t in db.query_tracks(favourites_only=True)] == [a]
    db.record_play(a)
    time.sleep(0.01)
    db.record_play(b)
    db.record_play(b)
    assert db.recently_played()[0] == b
    assert db.most_played()[0] == (b, 2)
    assert db.get_track(b).play_count == 2
    db.clear_history()
    assert db.recently_played() == [] and db.get_track(b).play_count == 0
    db.set_favourite(a, False)
    assert db.favourites() == []


def test_recently_added_orders_newest_first(db, tmp_path):
    for name in ("one", "two", "three"):
        path = _make(tmp_path, f"{name}.mp3")
        db.upsert_track(fake_reader(path))
        time.sleep(0.01)
    assert [t.title for t in db.recently_added(2)] == ["three", "two"]


def test_formatters():
    assert format_duration(65) == "1:05"
    assert format_duration(3725) == "1:02:05"
    assert format_duration(None) == "--:--"
    assert format_size(512) == "512 B" and format_size(5 * 1024 * 1024) == "5.0 MB"


def test_real_folder_scan_with_mutagen(db, music_folder):
    pytest.importorskip("mutagen")
    result = LibraryScanner(db).scan_folder(str(music_folder))
    assert result.added == 3 and not result.errors
    titles = sorted(t.title for t in db.query_tracks())
    assert titles == ["One", "Three", "Two"]
