# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Playlist model, M3U/M3U8/JSON formats, manager and session restore."""

from __future__ import annotations

import json
import os
import random

import pytest

from pulsedeck.playlists import m3u
from pulsedeck.playlists.manager import (
    PlaylistError,
    PlaylistManager,
    collect_audio_files,
    load_playlist_file,
    relink_missing,
    save_playlist_file,
)
from pulsedeck.playlists.model import Playlist, PlaylistEntry
from pulsedeck.playlists.persistence import SessionState, SessionStore, resolve_restore_index


def _touch(path):  # noqa: ANN001,ANN202
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0")
    return str(path)


def _playlist(tmp_path, n=4) -> Playlist:  # noqa: ANN001
    entries = [PlaylistEntry(_touch(tmp_path / "music" / f"{i}.mp3"), title=f"Song {chr(68 - i)}",
                             artist=f"Artist {i % 2}", album=f"Album {i}", duration=100 + i * 10) for i in range(n)]
    return Playlist("Test", entries)


# -- model ----------------------------------------------------------------------
def test_add_remove_move(tmp_path):
    pl = _playlist(tmp_path)
    original = pl.paths
    pl.move([0], 3)  # move first before the last
    assert pl.paths == [original[1], original[2], original[0], original[3]]
    assert pl.move_up([2]) == [1]
    assert pl.move_down([1]) == [2]
    removed = pl.remove([0, 2])
    assert len(removed) == 2 and len(pl) == 2
    added = pl.add([PlaylistEntry("/x.mp3")], at=1)
    assert list(added) == [1] and pl.entries[1].path == "/x.mp3"


def test_move_multiple_rows_to_end(tmp_path):
    pl = _playlist(tmp_path, 5)
    p = pl.paths
    assert pl.move([0, 2], 5) == [3, 4]
    assert pl.paths == [p[1], p[3], p[4], p[0], p[2]]


def test_sort_and_shuffle(tmp_path):
    pl = _playlist(tmp_path)
    pl.sort("title")
    assert [e.title for e in pl.entries] == ["Song A", "Song B", "Song C", "Song D"]
    pl.sort("duration", reverse=True)
    assert [e.duration for e in pl.entries] == [130, 120, 110, 100]
    pl.sort("artist")
    assert [e.artist for e in pl.entries][:2] == ["Artist 0", "Artist 0"]
    pl.sort("album")
    assert pl.entries[0].album == "Album 0"
    before = pl.paths
    pl.shuffle_entries(random.Random(3))
    assert sorted(pl.paths) == sorted(before)
    with pytest.raises(ValueError):
        pl.sort("bogus")


def test_search_duplicate_clear(tmp_path):
    pl = _playlist(tmp_path)
    assert pl.search("\"song a\"") == [3]
    assert pl.search("album 2") == [2]
    assert pl.search("artist:\"artist 1\"") == [1, 3]
    copy = pl.duplicate()
    assert copy.id != pl.id and copy.paths == pl.paths and copy.name == "Test (copy)"
    copy.entries[0].title = "changed"
    assert pl.entries[0].title != "changed"
    pl.clear()
    assert len(pl) == 0


def test_missing_entries_detected(tmp_path):
    pl = _playlist(tmp_path)
    os.remove(pl.entries[1].path)
    assert pl.missing() == [1]


# -- M3U --------------------------------------------------------------------------
def test_m3u8_round_trip_relative_paths_and_names(tmp_path):
    pl = _playlist(tmp_path)
    pl.name = "Café Mix ♫"
    pl.shuffle = True
    out = tmp_path / "lists" / "mix.m3u8"
    out.parent.mkdir()
    m3u.write_m3u(pl, out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U")
    assert os.path.join("..", "music", "0.mp3") in text   # relative path
    again = m3u.read_m3u(out)
    assert again.name == "Café Mix ♫" and again.shuffle is True
    assert [os.path.normcase(p) for p in again.paths] == [os.path.normcase(os.path.normpath(p)) for p in pl.paths]
    assert again.entries[0].title == pl.entries[0].title and again.entries[0].artist == "Artist 0"
    assert again.entries[0].duration == 100


def test_m3u_reads_plain_and_legacy_encoded_files(tmp_path):
    song = _touch(tmp_path / "Beyoncé.mp3")
    legacy = tmp_path / "old.m3u"
    legacy.write_bytes(b"# comment\r\nBeyonc\xe9.mp3\r\n\r\nhttp://radio.example/stream\r\n")
    pl = m3u.read_m3u(legacy)
    assert pl.paths[0] == os.path.normpath(song)
    assert pl.paths[1] == "http://radio.example/stream"
    assert pl.name == "old"


def test_m3u_handles_file_uris_and_foreign_separators(tmp_path):
    song = _touch(tmp_path / "sub dir" / "a b.mp3")
    lst = tmp_path / "x.m3u8"
    uri = "file://" + ("/" if os.name == "nt" else "") + song.replace(os.sep, "/").replace(" ", "%20")
    lst.write_text(f"#EXTM3U\n{uri}\nsub dir\\a b.mp3\n", encoding="utf-8")
    pl = m3u.read_m3u(lst)
    assert os.path.normcase(pl.paths[0]) == os.path.normcase(os.path.normpath(song))
    assert os.path.normcase(pl.paths[1]) == os.path.normcase(os.path.normpath(song))


def test_json_round_trip_and_format_dispatch(tmp_path):
    pl = _playlist(tmp_path)
    path = tmp_path / "list.json"
    save_playlist_file(pl, path)
    data = json.loads(path.read_text())
    assert data["format"] == "pulsedeck-playlist"
    again = load_playlist_file(path)
    assert again.paths == pl.paths and again.name == pl.name and again.id == pl.id
    with pytest.raises(PlaylistError):
        load_playlist_file(tmp_path / "list.txt")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(PlaylistError):
        load_playlist_file(broken)


# -- manager ----------------------------------------------------------------------
def test_manager_create_rename_duplicate_delete_persist(tmp_path):
    mgr = PlaylistManager(tmp_path / "pl")
    assert [p.name for p in mgr.all()] == ["Default"]
    a = mgr.create("Road Trip")
    a.add([PlaylistEntry(_touch(tmp_path / "s.mp3"))])
    mgr.save(a)
    assert mgr.create("Road Trip").name == "Road Trip 2"
    mgr.rename(a.id, "Drive")
    copy = mgr.duplicate(a.id)
    names = [p.name for p in mgr.all()]
    assert names.index("Drive (copy)") == names.index("Drive") + 1
    reloaded = PlaylistManager(tmp_path / "pl")
    assert [p.name for p in reloaded.all()] == names
    assert reloaded.get(copy.id).paths == a.paths
    reloaded.delete(copy.id)
    assert reloaded.get(copy.id) is None
    with pytest.raises(PlaylistError):
        reloaded.rename(a.id, "  ")


def test_manager_import_export(tmp_path):
    mgr = PlaylistManager(tmp_path / "pl")
    pl = _playlist(tmp_path)
    src = tmp_path / "in.m3u"
    m3u.write_m3u(pl, src)
    imported = mgr.import_file(src)
    assert imported.paths == [os.path.normpath(p) for p in pl.paths]
    out = tmp_path / "out.json"
    mgr.export(imported.id, out)
    assert load_playlist_file(out).paths == imported.paths


def test_manager_skips_corrupt_files(tmp_path):
    folder = tmp_path / "pl"
    folder.mkdir()
    (folder / "junk.json").write_text("{{{")
    mgr = PlaylistManager(folder)
    assert len(mgr.all()) == 1


def test_relink_missing_files(tmp_path):
    pl = _playlist(tmp_path)
    moved_dir = tmp_path / "moved"
    moved_dir.mkdir()
    os.replace(pl.entries[0].path, moved_dir / "0.mp3")
    assert pl.missing() == [0]
    assert relink_missing(pl, [str(moved_dir)]) == 1
    assert pl.missing() == []


def test_collect_audio_files_expands_folders(tmp_path):
    _touch(tmp_path / "f" / "b.flac")
    _touch(tmp_path / "f" / "A.mp3")
    _touch(tmp_path / "f" / "cover.jpg")
    files = collect_audio_files([str(tmp_path / "f"), str(tmp_path / "f" / "cover.jpg")])
    assert [os.path.basename(f) for f in files] == ["A.mp3", "b.flac"]


# -- session ----------------------------------------------------------------------
def test_session_round_trip(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    store.save(SessionState(playlist_id="abc", track_index=2, track_path="/a.mp3", position=42.5, was_playing=True))
    state = store.load()
    assert (state.playlist_id, state.track_index, state.position, state.was_playing) == ("abc", 2, 42.5, True)


@pytest.mark.parametrize("content", ["", "{bad json", "[]", '{"track_index": "x", "position": "nan?"}'])
def test_damaged_session_never_crashes(tmp_path, content):
    path = tmp_path / "session.json"
    path.write_text(content)
    state = SessionStore(path).load()
    assert state.track_index is None
    assert state.position == 0.0


def test_restore_index_tolerates_edits():
    paths = ["/a", "/b", "/c"]
    assert resolve_restore_index(paths, SessionState(track_index=1, track_path="/b")) == 1
    assert resolve_restore_index(["/x", *paths], SessionState(track_index=1, track_path="/b")) == 2
    assert resolve_restore_index(paths, SessionState(track_index=9, track_path="/zzz")) is None
