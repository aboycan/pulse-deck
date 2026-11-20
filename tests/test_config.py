# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Configuration persistence, cross-platform paths, themes, shortcuts and context menus."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from pulsedeck.core import platform
from pulsedeck.core.configuration import DEFAULTS, Configuration
from pulsedeck.ui import context_menus as cm
from pulsedeck.ui import shortcuts
from pulsedeck.ui.theme import REQUIRED_COLORS, ThemeError, available_themes, build_stylesheet, parse_theme, with_accent


# -- configuration ----------------------------------------------------------------
def test_defaults_and_dotted_access(tmp_path):
    cfg = Configuration(tmp_path / "s.json")
    cfg.load()
    assert cfg.get("audio.volume") == DEFAULTS["audio"]["volume"]
    assert cfg.get("missing.key", "x") == "x"
    cfg.set("audio.volume", 33)
    cfg.set("new.section.value", [1, 2])
    assert cfg.get("audio.volume") == 33 and cfg.get("new.section.value") == [1, 2]


def test_settings_persist_between_launches(tmp_path):
    path = tmp_path / "s.json"
    cfg = Configuration(path)
    cfg.load()
    cfg.set("playback.shuffle", True)
    cfg.set("equalizer.gains", [1.5] * 10)
    cfg.set("interface.theme", "light")
    cfg.save()
    again = Configuration(path)
    again.load()
    assert again.get("playback.shuffle") is True
    assert again.get("equalizer.gains") == [1.5] * 10
    assert again.get("interface.theme") == "light"
    assert again.get("audio.crossfade_seconds") == 0.0  # new defaults are merged in


def test_corrupt_settings_fall_back_to_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{definitely not json")
    cfg = Configuration(path)
    cfg.load()
    assert cfg.get("audio.volume") == DEFAULTS["audio"]["volume"]
    assert (tmp_path / "s.corrupt.json").exists()


def test_listeners_and_reset(tmp_path):
    cfg = Configuration(tmp_path / "s.json")
    seen = []
    cfg.add_listener(lambda k, v: seen.append((k, v)))
    cfg.set("audio.volume", 10)
    cfg.set("audio.volume", 10)  # unchanged -> no event
    cfg.reset("audio.volume")
    assert seen == [("audio.volume", 10), ("audio.volume", DEFAULTS["audio"]["volume"])]


def test_save_is_atomic_and_valid_json(tmp_path):
    cfg = Configuration(tmp_path / "deep" / "dir" / "s.json")
    cfg.save()
    assert json.loads((tmp_path / "deep" / "dir" / "s.json").read_text())["version"] == 1
    assert not [p for p in (tmp_path / "deep" / "dir").iterdir() if p.name.startswith(".")]


# -- cross-platform paths -----------------------------------------------------------
def test_user_dirs_respect_override(isolated_home):
    for func in (platform.config_dir, platform.data_dir, platform.cache_dir, platform.log_dir):
        path = func()
        assert path.is_dir() and isolated_home in path.parents


def test_platform_dirs_without_override(monkeypatch, tmp_path):
    monkeypatch.delenv("PULSEDECK_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    config = platform.config_dir()
    if platform.IS_WINDOWS:
        assert config == tmp_path / "Roaming" / "PulseDeck"
    elif platform.IS_MACOS:
        assert config.parts[-3:] == ("Library", "Application Support", "PulseDeck")
    else:
        assert config == tmp_path / "xdg-config" / "pulsedeck"
    assert platform.data_dir() != config


def test_normalize_path_resolves_aliases(tmp_path):
    target = tmp_path / "Music" / "song.mp3"
    target.parent.mkdir()
    target.write_bytes(b"")
    a = platform.normalize_path(target)
    b = platform.normalize_path(str(tmp_path / "Music" / ".." / "Music" / "song.mp3"))
    assert a == b
    if platform.IS_WINDOWS or platform.IS_MACOS:
        assert platform.normalize_path(str(target).upper()) == a
    if hasattr(os, "symlink") and not platform.IS_WINDOWS:
        link = tmp_path / "link.mp3"
        link.symlink_to(target)
        assert platform.normalize_path(link) == a


def test_unicode_and_space_paths_round_trip(tmp_path):
    from pulsedeck.playlists import m3u
    from pulsedeck.playlists.model import Playlist, PlaylistEntry

    song = tmp_path / "Ünïcødé Földer" / "日本語 song.flac"
    song.parent.mkdir()
    song.write_bytes(b"\0")
    out = tmp_path / "p.m3u8"
    m3u.write_m3u(Playlist("u", [PlaylistEntry(str(song))]), out)
    assert Path(m3u.read_m3u(out).paths[0]).exists()


def test_platform_name_matches_sys():
    expected = "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"
    assert platform.platform_name() == expected


# -- themes --------------------------------------------------------------------------
def test_builtin_themes_are_valid():
    themes = available_themes()
    assert {"classic_dark", "modern_dark", "light", "high_contrast"} <= set(themes)
    for theme in themes.values():
        css = build_stylesheet(theme, 11)
        assert theme.color("accent") in css and "11pt" in css


def test_theme_validation_and_accent():
    good = {"id": "t", "colors": dict.fromkeys(REQUIRED_COLORS, "#123456")}
    theme = parse_theme(good)
    assert with_accent(theme, "#ffffff").colors["accent_text"] == "#000000"
    assert with_accent(theme, "not-a-colour").colors["accent"] == "#123456"
    bad = {"id": "t", "colors": {**good["colors"], "accent": "red"}}
    with pytest.raises(ThemeError):
        parse_theme(bad)
    with pytest.raises(ThemeError):
        parse_theme({"id": "t", "colors": {"text": "#000000"}})


def test_user_themes_are_discovered(isolated_home):
    from pulsedeck.ui.theme import user_theme_dir

    data = {"id": "mine", "name": "Mine", "colors": dict.fromkeys(REQUIRED_COLORS, "#222222")}
    (user_theme_dir() / "mine.json").write_text(json.dumps(data))
    assert available_themes()["mine"].name == "Mine"


# -- shortcuts -------------------------------------------------------------------------
def test_required_default_shortcuts():
    d = shortcuts.defaults()
    expected = {"play_pause": "Space", "open_files": "Ctrl+O", "open_folder": "Ctrl+Shift+O", "save_playlist": "Ctrl+S",
                "new_playlist": "Ctrl+N", "search": "Ctrl+F", "next": "Ctrl+Right", "previous": "Ctrl+Left",
                "volume_up": "Ctrl+Up", "volume_down": "Ctrl+Down"}
    for key, value in expected.items():
        assert d[key] == value
    assert shortcuts.conflicts(d) == {}


def test_shortcut_overrides_and_conflicts():
    mapping = shortcuts.effective({"next": "Ctrl+O", "unknown": "X", "stop": 5})
    assert mapping["next"] == "Ctrl+O" and "unknown" not in mapping
    assert set(shortcuts.conflicts(mapping)["ctrl+o"]) == {"next", "open_files"}


# -- context menus -------------------------------------------------------------------
REQUIRED_SONG = ["Play", "Play Next", "Add to Current Playlist", "Add to New Playlist", "Remove from Playlist",
                 "Remove from Library", "View Song Information", "Edit Metadata", "Set as Favourite",
                 "Copy File Path", "Open Containing Folder"]


def _labels(items):  # noqa: ANN001,ANN202
    return [i.label.rstrip("…") for i in items if i.id != "-"]


def test_song_menu_has_every_required_action():
    labels = _labels(cm.song_menu_items())
    for required in REQUIRED_SONG:
        assert required in labels
    assert cm.reveal_label() in labels


def test_playlist_and_group_menus():
    assert _labels(cm.playlist_menu_items()) == ["Play Playlist", "Shuffle Playlist", "Rename Playlist",
                                                 "Duplicate Playlist", "Export Playlist", "Clear Playlist",
                                                 "Delete Playlist"]
    assert _labels(cm.group_menu_items("artist")) == ["Play All", "Add to Playlist", "View Albums", "View Information"]


def test_menu_context_disables_and_cleans_separators():
    ctx = cm.MenuContext(disabled={"remove_playlist"}, hidden={"play", "play_next"}, labels={"favourite": "Unfav"})
    resolved = cm.resolve(cm.song_menu_items(), ctx)
    assert resolved[0][0].id != "-"                     # no leading separator after hiding items
    states = {item.id: (enabled, label) for item, enabled, label in resolved}
    assert states["remove_playlist"][0] is False
    assert states["favourite"][1] == "Unfav"
    assert "play" not in states


def test_qt_menu_builds_and_dispatches():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    calls = []
    ctx = cm.MenuContext(dynamic={"playlists": [("id1", "Road Trip")]}, disabled={"edit"})
    menu = cm.build_menu(cm.song_menu_items(), ctx, lambda a, v: calls.append((a, v)))
    actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}
    actions["Play"].trigger()
    assert calls == [("play", None)]
    assert not actions["Edit Metadata…"].isEnabled()
    submenu = actions["Add to Playlist"].menu()
    submenu.actions()[0].trigger()
    assert calls[-1] == ("add_to", "id1")


# -- Windows notification identity -------------------------------------------
def test_windows_identity_shows_app_name_not_raw_id(tmp_path):
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"png")
    values = platform.windows_app_identity_values("PulseDeck", icon)
    assert values["DisplayName"] == "PulseDeck"
    assert "io.github" not in values["DisplayName"]
    assert values["IconUri"] == str(icon.resolve())
    assert "IconUri" not in platform.windows_app_identity_values("PulseDeck", tmp_path / "missing.png")


def test_register_identity_is_a_no_op_off_windows():
    if not platform.IS_WINDOWS:
        assert platform.register_windows_app_identity("x.y.Z", "PulseDeck") is False
