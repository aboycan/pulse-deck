# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Application controller: owns the services and implements every user action.

Windows and panels never talk to the engine, database or playlist storage
directly; they call methods here and react to the signals below. That keeps
the UI, audio engine, library and playlist layers separate.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal

from pulsedeck.audio.backend import AudioBackend, AudioParams, BackendCallbacks, SimulatedBackend
from pulsedeck.audio.equalizer import EqualizerState, PresetStore
from pulsedeck.audio.playback_engine import PlaybackEngine, PlaybackState
from pulsedeck.audio.playback_queue import PlaybackQueue, RepeatMode
from pulsedeck.core.configuration import Configuration
from pulsedeck.core.database import LibraryDatabase
from pulsedeck.library import metadata as md
from pulsedeck.library.artwork import ArtworkCache
from pulsedeck.library.models import TrackInfo, is_audio_file
from pulsedeck.library.scanner import LibraryScanner, ScanResult
from pulsedeck.playlists.manager import (
    IMPORT_EXTENSIONS,
    PlaylistError,
    PlaylistManager,
    collect_audio_files,
)
from pulsedeck.playlists.model import Playlist, PlaylistEntry
from pulsedeck.playlists.persistence import SessionState, SessionStore, resolve_restore_index
from pulsedeck.ui.engine_bridge import EngineBridge

log = logging.getLogger(__name__)

RESTART_THRESHOLD_SECONDS = 3.0
VOLUME_STEP = 5


# -- background workers ----------------------------------------------------
class _MetadataSignals(QObject):
    loaded = Signal(object)


class MetadataJob(QRunnable):
    """Reads tags for playlist entries off the GUI thread."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = _MetadataSignals()

    def run(self) -> None:
        results: list[TrackInfo] = []
        for path in self.paths:
            try:
                results.append(md.read_metadata(path))
            except Exception:  # missing/corrupt files simply keep their file name
                continue
            if len(results) >= 50:
                self.signals.loaded.emit(results)
                results = []
        if results:
            self.signals.loaded.emit(results)


class ScanThread(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)

    def __init__(self, scanner: LibraryScanner, folders: list[str] | None, files: list[str] | None) -> None:
        super().__init__()
        self.scanner = scanner
        self.folders = folders
        self.files = files
        self.cancel_event = threading.Event()

    def run(self) -> None:
        result = ScanResult()

        def report(i: int, n: int, path: str) -> None:
            self.progress.emit(i, n, path)

        try:
            if self.files:
                result.merge(self.scanner.add_files(self.files, report, self.cancel_event))
            if self.folders is None and not self.files:
                result.merge(self.scanner.rescan_all(report, self.cancel_event))
            for folder in self.folders or []:
                if self.cancel_event.is_set():
                    result.cancelled = True
                    break
                result.merge(self.scanner.scan_folder(folder, report, self.cancel_event))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Library scan failed")
            result.errors.append(("", str(exc)))
        self.done.emit(result)


# -- controller ------------------------------------------------------------
class AppController(QObject):
    track_changed = Signal(object)            # TrackInfo | None
    state_changed = Signal(str)
    position_changed = Signal(float, float)
    audio_params_changed = Signal(object)
    playlists_changed = Signal()
    playlist_changed = Signal(str)            # playlist id whose entries changed
    active_playlist_changed = Signal(str)
    current_index_changed = Signal(str, int)  # playlist id, index (-1 = none)
    options_changed = Signal()                # volume, mute, shuffle, repeat, speed, balance
    equalizer_changed = Signal()
    library_changed = Signal()
    favourites_changed = Signal()
    history_changed = Signal()
    scan_progress = Signal(int, int, str)
    scan_finished = Signal(object)
    message = Signal(str)
    error = Signal(str)
    show_info_requested = Signal(str, bool)   # path, edit mode
    settings_changed = Signal(str)            # dotted config key

    def __init__(self, config: Configuration | None = None, db: LibraryDatabase | None = None,
                 backend_factory=None, playlist_manager: PlaylistManager | None = None,  # noqa: ANN001
                 preset_store: PresetStore | None = None, session_store: SessionStore | None = None) -> None:
        super().__init__()
        self.config = config or Configuration()
        if config is None:
            self.config.load()
        self.db = db or LibraryDatabase()
        self.presets = preset_store or PresetStore()
        self.playlists = playlist_manager or PlaylistManager()
        self.session_store = session_store or SessionStore()
        self.artwork = ArtworkCache()
        self.pool = QThreadPool.globalInstance()
        self._metadata_cache: OrderedDict[str, TrackInfo] = OrderedDict()

        self.audio_error: str | None = None
        self._backend_factory = backend_factory or self._default_backend_factory
        self.bridge = EngineBridge()
        self.engine = PlaybackEngine(self._create_backend, self.bridge)
        self.queue = PlaybackQueue()
        self._next_path: str | None = None
        self.engine.next_provider = lambda: self._next_path

        self.state = PlaybackState.STOPPED
        self.position = 0.0
        self.duration = 0.0
        self.audio_params = AudioParams()
        self.current_track: TrackInfo | None = None
        self._current_entry: PlaylistEntry | None = None
        self._consecutive_errors = 0
        self._scan_thread: ScanThread | None = None
        self._jobs: list[MetadataJob] = []

        all_lists = self.playlists.all()
        self._active_id = all_lists[0].id
        self.eq = EqualizerState.from_config(self.config.get("equalizer", {}))

        self.bridge.state_changed.connect(self._on_state)
        self.bridge.track_started.connect(self._on_track_started)
        self.bridge.track_finished.connect(self._on_track_finished)
        self.bridge.position_changed.connect(self._on_position)
        self.bridge.audio_params_changed.connect(self._on_audio_params)
        self.bridge.error.connect(self._on_engine_error)

        self._apply_audio_config()
        self.queue.set_shuffle(bool(self.config.get("playback.shuffle")))
        self.queue.repeat = RepeatMode.parse(self.config.get("playback.repeat"))

        self._session_timer = QTimer(self)
        self._session_timer.setInterval(15_000)
        self._session_timer.timeout.connect(self.save_session)
        self._session_timer.start()

    # -- backend creation ------------------------------------------------
    def _default_backend_factory(self, callbacks: BackendCallbacks) -> AudioBackend:
        from pulsedeck.audio.mpv_backend import MpvBackend  # noqa: PLC0415

        return MpvBackend(callbacks)

    def _create_backend(self, callbacks: BackendCallbacks) -> AudioBackend:
        if self.audio_error is None:
            try:
                return self._backend_factory(callbacks)
            except Exception as exc:
                log.exception("Audio engine unavailable")
                self.audio_error = (
                    "The audio engine (libmpv) could not be loaded, so playback is disabled.\n\n"
                    "If you are running from source, run install.bat (Windows) or ./install.sh "
                    "(macOS/Linux) once with an internet connection to download it.\n\n"
                    f"Details: {exc}"
                )
        return SimulatedBackend(callbacks=callbacks)

    def _apply_audio_config(self) -> None:
        c = self.config
        self.engine.set_volume(c.get("audio.volume", 80))
        self.engine.set_muted(c.get("audio.muted", False))
        self.engine.set_speed(c.get("audio.speed", 1.0))
        self.engine.set_balance(c.get("audio.balance", 0.0))
        self.engine.set_normalization(c.get("audio.normalization", False))
        self.engine.set_clip_protection(c.get("audio.clip_protection", True))
        self.engine.set_replaygain(c.get("audio.replaygain", "off"), c.get("audio.replaygain_preamp", 0.0))
        self.engine.set_crossfade(c.get("audio.crossfade_seconds", 0.0))
        self.engine.set_gapless(c.get("audio.gapless", True))
        self.engine.set_device(c.get("audio.output_device", "auto"))
        self.engine.set_equalizer(self.eq)

    def set_setting(self, key: str, value) -> None:  # noqa: ANN001
        """Change a setting, apply it live and notify listeners."""
        self.config.set(key, value)
        engine_setters = {
            "audio.speed": self.engine.set_speed,
            "audio.balance": self.engine.set_balance,
            "audio.normalization": self.engine.set_normalization,
            "audio.clip_protection": self.engine.set_clip_protection,
            "audio.crossfade_seconds": self.engine.set_crossfade,
            "audio.gapless": self.engine.set_gapless,
            "audio.output_device": self.engine.set_device,
        }
        if key in engine_setters:
            engine_setters[key](value)
        elif key in ("audio.replaygain", "audio.replaygain_preamp"):
            self.engine.set_replaygain(self.config.get("audio.replaygain"), self.config.get("audio.replaygain_preamp"))
        self.settings_changed.emit(key)
        if key in ("audio.speed", "audio.balance"):
            self.options_changed.emit()

    # -- metadata --------------------------------------------------------
    def track_info(self, path: str, refresh: bool = False) -> TrackInfo:
        if not refresh and path in self._metadata_cache:
            self._metadata_cache.move_to_end(path)
            return self._metadata_cache[path]
        info = None if refresh else self.db.get_track(path)
        if info is None or refresh:
            try:
                info = md.read_metadata(path)
            except md.MetadataError as exc:
                log.debug("No metadata for %s: %s", path, exc)
                info = TrackInfo(path=path)
            library_entry = self.db.get_track(path)
            if library_entry is not None and refresh:
                self.db.upsert_track(info)
        info.favourite = self.db.is_favourite(path)
        self._metadata_cache[path] = info
        while len(self._metadata_cache) > 2000:
            self._metadata_cache.popitem(last=False)
        return info

    def _entries_for(self, paths: list[str]) -> list[PlaylistEntry]:
        entries: list[PlaylistEntry] = []
        unknown: list[str] = []
        for path in paths:
            info = self._metadata_cache.get(path) or self.db.get_track(path)
            if info is not None:
                entries.append(PlaylistEntry.from_track(info))
            else:
                entries.append(PlaylistEntry(path))
                unknown.append(path)
        if unknown:
            self._load_metadata_async(unknown)
        return entries

    def _load_metadata_async(self, paths: list[str]) -> None:
        job = MetadataJob(paths)
        job.signals.loaded.connect(self._on_metadata_loaded)
        self._jobs.append(job)
        job.setAutoDelete(False)
        self.pool.start(job)

    def _on_metadata_loaded(self, infos: list[TrackInfo]) -> None:
        by_path = {i.path: i for i in infos}
        for info in infos:
            self._metadata_cache[info.path] = info
        for playlist in self.playlists.all():
            changed = False
            for entry in playlist.entries:
                info = by_path.get(entry.path)
                if info is not None:
                    entry.title, entry.artist = info.title, info.artist
                    entry.album, entry.duration = info.album, info.duration
                    changed = True
            if changed:
                self.playlists.save(playlist)
                self.playlist_changed.emit(playlist.id)
        self._jobs = [j for j in self._jobs if j.signals is not self.sender()]

    # -- playlists -------------------------------------------------------
    @property
    def active_playlist(self) -> Playlist:
        playlist = self.playlists.get(self._active_id)
        if playlist is None:
            playlist = self.playlists.all()[0]
            self._active_id = playlist.id
        return playlist

    @property
    def current_index(self) -> int:
        if self._current_entry is None:
            return -1
        for i, entry in enumerate(self.active_playlist.entries):
            if entry is self._current_entry:
                return i
        return -1

    def set_active_playlist(self, playlist_id: str) -> None:
        if playlist_id == self._active_id or self.playlists.get(playlist_id) is None:
            return
        self._active_id = playlist_id
        self._current_entry = None
        self._sync_queue(reset=True)
        self.active_playlist_changed.emit(playlist_id)

    def _sync_queue(self, reset: bool = False) -> None:
        playlist = self.active_playlist
        index = self.current_index
        self.queue.set_shuffle(self.queue.shuffle)
        if reset:
            self.queue.set_tracks(playlist.paths, index if index >= 0 else None)
        else:
            self.queue.sync(playlist.paths, index if index >= 0 else None)
        self._update_next()
        self.current_index_changed.emit(playlist.id, index)

    def _update_next(self) -> None:
        nxt = self.queue.peek_next(auto=True)
        self._next_path = self.active_playlist.entries[nxt].path if nxt is not None else None
        self.engine.refresh_next()

    def playlist_edited(self, playlist_id: str) -> None:
        """Call after changing a playlist's entries in place."""
        playlist = self.playlists.get(playlist_id)
        if playlist is None:
            return
        self.playlists.save(playlist)
        if playlist_id == self._active_id:
            if self._current_entry is not None and self.current_index < 0:
                self._current_entry = None  # the playing entry was removed
            self._sync_queue()
        self.playlist_changed.emit(playlist_id)

    def new_playlist(self, name: str = "New playlist", paths: Iterable[str] = ()) -> Playlist:
        playlist = self.playlists.create(name)
        files = collect_audio_files(list(paths))
        if files:
            playlist.add(self._entries_for(files))
            self.playlists.save(playlist)
        self.playlists_changed.emit()
        return playlist

    def rename_playlist(self, playlist_id: str, name: str) -> None:
        try:
            self.playlists.rename(playlist_id, name)
        except PlaylistError as exc:
            self.error.emit(str(exc))
            return
        self.playlists_changed.emit()

    def duplicate_playlist(self, playlist_id: str) -> Playlist | None:
        try:
            copy = self.playlists.duplicate(playlist_id)
        except PlaylistError as exc:
            self.error.emit(str(exc))
            return None
        self.playlists_changed.emit()
        return copy

    def delete_playlist(self, playlist_id: str) -> None:
        was_active = playlist_id == self._active_id
        if was_active:
            self.stop()
        self.playlists.delete(playlist_id)
        if was_active:
            self._active_id = self.playlists.all()[0].id
            self._current_entry = None
            self._sync_queue(reset=True)
            self.active_playlist_changed.emit(self._active_id)
        self.playlists_changed.emit()

    def clear_playlist(self, playlist_id: str) -> None:
        playlist = self.playlists.get(playlist_id)
        if playlist is None:
            return
        if playlist_id == self._active_id:
            self.stop()
            self._current_entry = None
        playlist.clear()
        self.playlist_edited(playlist_id)

    def add_paths(self, playlist_id: str, paths: Iterable[str], at: int | None = None,
                  play: bool = False) -> range:
        playlist = self.playlists.get(playlist_id)
        if playlist is None:
            return range(0)
        files = collect_audio_files(list(paths))
        if not files:
            self.message.emit("No supported audio files found")
            return range(0)
        added = playlist.add(self._entries_for(files), at)
        self.playlist_edited(playlist_id)
        if play and len(added):
            if playlist_id != self._active_id:
                self.set_active_playlist(playlist_id)
            self.play_index(added.start)
        return added

    def remove_entries(self, playlist_id: str, indices: list[int]) -> None:
        playlist = self.playlists.get(playlist_id)
        if playlist is None:
            return
        playing_removed = playlist_id == self._active_id and self.current_index in indices
        playlist.remove(indices)
        if playing_removed:
            self.stop()
            self._current_entry = None
        self.playlist_edited(playlist_id)

    def open_paths(self, paths: Iterable[str], play: bool = True) -> None:
        """Open files, folders or playlist files (command line, drag and drop)."""
        audio: list[str] = []
        for path in paths:
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in IMPORT_EXTENSIONS:
                try:
                    playlist = self.playlists.import_file(path)
                except PlaylistError as exc:
                    self.error.emit(str(exc))
                    continue
                self._load_metadata_async([e.path for e in playlist.entries if not e.title])
                self.playlists_changed.emit()
                self.set_active_playlist(playlist.id)
                missing = len(playlist.missing())
                if missing:
                    self.message.emit(f"{missing} file(s) in '{playlist.name}' could not be found")
                if play and playlist.entries:
                    self.play_index(0)
                    play = False
            elif os.path.isdir(path) or is_audio_file(path):
                audio.append(path)
        if audio:
            self.add_paths(self._active_id, audio, play=play)

    def play_playlist(self, playlist_id: str, shuffle: bool | None = None) -> None:
        playlist = self.playlists.get(playlist_id)
        if playlist is None or not playlist.entries:
            return
        self.set_active_playlist(playlist_id)
        if shuffle is not None:
            self.set_shuffle(shuffle)
        self.queue.set_tracks(playlist.paths, None)
        first = self.queue._order[0] if self.queue.shuffle and self.queue._order else 0  # noqa: SLF001
        self.play_index(first)

    def play_paths_next(self, paths: list[str]) -> None:
        """Insert ``paths`` after the current track in the active playlist."""
        playlist = self.active_playlist
        position = self.current_index + 1 if self.current_index >= 0 else len(playlist.entries)
        added = playlist.add(self._entries_for(paths), position)
        self.playlist_edited(playlist.id)
        for index in added:
            self.queue.play_next(index)
        self._update_next()
        if self.state is PlaybackState.STOPPED and self.current_index < 0 and len(added):
            self.play_index(added.start)

    # -- transport -------------------------------------------------------
    def play_index(self, index: int, start: float = 0.0, paused: bool = False) -> None:
        playlist = self.active_playlist
        if not 0 <= index < len(playlist.entries):
            return
        entry = playlist.entries[index]
        if list(self.queue.paths) != playlist.paths:
            self.queue.set_tracks(playlist.paths, index)
        else:
            self.queue.jump_to(index)
        self._current_entry = entry
        self._update_next()
        self.current_index_changed.emit(playlist.id, index)
        if not os.path.isfile(entry.path):
            self._on_engine_error(entry.path, "File not found (it may have been moved or deleted)")
            return
        self._set_current_track(entry.path)
        self.engine.play_file(entry.path, start=start, paused=paused)

    def _set_current_track(self, path: str) -> None:
        self.current_track = self.track_info(path)
        entry = self._current_entry
        if entry is not None and self.current_track.duration and not entry.duration:
            entry.title, entry.artist = self.current_track.title, self.current_track.artist
            entry.album, entry.duration = self.current_track.album, self.current_track.duration
        self.duration = self.current_track.duration
        self.track_changed.emit(self.current_track)

    def toggle_play_pause(self) -> None:
        if self.state is PlaybackState.PLAYING:
            self.engine.pause()
        elif self.state is PlaybackState.PAUSED:
            self.engine.play()
        else:
            self.play()

    def play(self) -> None:
        if self.state is PlaybackState.PAUSED:
            self.engine.play()
            return
        if self.state is PlaybackState.PLAYING:
            return
        index = self.current_index
        if index < 0:
            if not self.active_playlist.entries:
                return
            self.queue.set_tracks(self.active_playlist.paths, None)
            index = self.queue._order[0] if self.queue._order else 0  # noqa: SLF001
        self.play_index(index)

    def pause(self) -> None:
        self.engine.pause()

    def stop(self) -> None:
        self.engine.stop()
        self.position = 0.0

    def next_track(self) -> None:
        if not self.active_playlist.entries:
            return
        path = self.queue.advance(auto=False)
        index = self.queue.current_index
        if path is None or index is None:
            self.message.emit("End of playlist")
            return
        self._play_queue_index(index)

    def previous_track(self) -> None:
        if self.position > RESTART_THRESHOLD_SECONDS and self.state is not PlaybackState.STOPPED:
            self.seek(0.0)
            return
        path = self.queue.previous()
        index = self.queue.current_index
        if path is not None and index is not None:
            self._play_queue_index(index)

    def _play_queue_index(self, index: int) -> None:
        playlist = self.active_playlist
        entry = playlist.entries[index]
        self._current_entry = entry
        self._update_next()
        self.current_index_changed.emit(playlist.id, index)
        if not os.path.isfile(entry.path):
            self._on_engine_error(entry.path, "File not found (it may have been moved or deleted)")
            return
        self._set_current_track(entry.path)
        self.engine.play_file(entry.path)

    def seek(self, seconds: float) -> None:
        self.engine.seek(seconds)
        self.position = seconds

    def seek_relative(self, delta: float) -> None:
        self.engine.seek(delta, relative=True)

    def fast_forward(self) -> None:
        self.seek_relative(float(self.config.get("audio.seek_step_seconds", 5)))

    def rewind(self) -> None:
        self.seek_relative(-float(self.config.get("audio.seek_step_seconds", 5)))

    # -- volume and options ---------------------------------------------
    @property
    def volume(self) -> int:
        return int(self.config.get("audio.volume", 80))

    @property
    def muted(self) -> bool:
        return bool(self.config.get("audio.muted", False))

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        self.config.set("audio.volume", volume)
        self.engine.set_volume(volume)
        if self.muted and volume > 0:
            self.set_muted(False)
        self.options_changed.emit()

    def change_volume(self, delta: int) -> None:
        self.set_volume(self.volume + delta)

    def set_muted(self, muted: bool) -> None:
        self.config.set("audio.muted", bool(muted))
        self.engine.set_muted(bool(muted))
        self.options_changed.emit()

    def toggle_mute(self) -> None:
        self.set_muted(not self.muted)

    @property
    def shuffle(self) -> bool:
        return self.queue.shuffle

    def set_shuffle(self, enabled: bool) -> None:
        self.queue.set_shuffle(bool(enabled))
        self.config.set("playback.shuffle", bool(enabled))
        self.active_playlist.shuffle = bool(enabled)
        self._update_next()
        self.options_changed.emit()

    @property
    def repeat(self) -> RepeatMode:
        return self.queue.repeat

    def set_repeat(self, mode: RepeatMode | str) -> None:
        self.queue.repeat = RepeatMode.parse(mode)
        self.config.set("playback.repeat", self.queue.repeat.value)
        self._update_next()
        self.options_changed.emit()

    def cycle_repeat(self) -> None:
        self.set_repeat(self.queue.repeat.cycled())

    # -- equalizer -------------------------------------------------------
    def apply_equalizer(self, state: EqualizerState | None = None) -> None:
        if state is not None:
            self.eq = state
        self.engine.set_equalizer(self.eq)
        self.config.set("equalizer", {**self.config.get("equalizer", {}), **self.eq.to_config()})
        self.equalizer_changed.emit()

    # -- engine events ---------------------------------------------------
    def _on_state(self, state: str) -> None:
        self.state = PlaybackState(state)
        self.state_changed.emit(state)

    def _on_track_started(self, path: str, auto: bool) -> None:
        if auto:
            advanced = self.queue.advance(auto=True)
            index = self.queue.current_index
            playlist = self.active_playlist
            if advanced == path and index is not None:
                self._current_entry = playlist.entries[index]
            else:  # queue changed under us; locate the file
                matches = [i for i, e in enumerate(playlist.entries) if e.path == path]
                self._current_entry = playlist.entries[matches[0]] if matches else None
                self._sync_queue()
            self._set_current_track(path)
            self._update_next()
            self.current_index_changed.emit(playlist.id, self.current_index)
        self.db.record_play(path)
        self.history_changed.emit()

    def _on_track_finished(self) -> None:
        path = self.queue.advance(auto=True)
        index = self.queue.current_index
        if path is None or index is None:
            self.queue.stop()
            self._current_entry = None
            self.current_index_changed.emit(self._active_id, -1)
            self.message.emit("Playback finished")
            return
        self._play_queue_index(index)

    def _on_position(self, position: float, duration: float) -> None:
        self.position = position
        if duration:
            self.duration = duration
        if position > 0.5:
            self._consecutive_errors = 0
        self.position_changed.emit(position, self.duration)

    def _on_audio_params(self, params: AudioParams) -> None:
        self.audio_params = params
        self.audio_params_changed.emit(params)

    def _on_engine_error(self, path: str, message: str) -> None:
        name = os.path.basename(path) if path else "track"
        self.error_message = f"Cannot play '{name}': {message}"
        self.message.emit(self.error_message)
        self._consecutive_errors += 1
        playlist = self.active_playlist
        if self._consecutive_errors >= max(1, len(playlist.entries)):
            self._consecutive_errors = 0
            self.engine.stop()
            self.error.emit(f"{self.error_message}\n\nNo playable tracks were found in this playlist.")
            return
        # Skip past the failed track.
        path_next = self.queue.advance(auto=False)
        index = self.queue.current_index
        if path_next is None or index is None:
            self.engine.stop()
            return
        QTimer.singleShot(0, lambda i=index: self._play_queue_index(i))

    # -- library ---------------------------------------------------------
    @property
    def scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.isRunning()

    def scan_library(self, folders: list[str] | None = None, files: list[str] | None = None) -> bool:
        if self.scanning:
            self.message.emit("A library scan is already running")
            return False
        scanner = LibraryScanner(self.db, duplicate_mode=self.config.get("library.duplicate_detection"))
        thread = ScanThread(scanner, folders, files)
        thread.progress.connect(self.scan_progress)
        thread.done.connect(self._on_scan_done)
        self._scan_thread = thread
        thread.start()
        return True

    def cancel_scan(self) -> None:
        if self._scan_thread is not None:
            self._scan_thread.cancel_event.set()

    def _on_scan_done(self, result: ScanResult) -> None:
        self._scan_thread = None
        self.config.set("library.folders", self.db.folders())
        self.library_changed.emit()
        self.scan_finished.emit(result)
        self.message.emit(f"Library scan {'cancelled' if result.cancelled else 'finished'}: {result.summary}")

    def add_library_folder(self, folder: str) -> None:
        self.db.add_folder(os.path.abspath(folder))
        self.config.set("library.folders", self.db.folders())
        self.scan_library([os.path.abspath(folder)])

    def remove_library_folder(self, folder: str) -> int:
        removed = self.db.remove_folder(folder)
        self.config.set("library.folders", self.db.folders())
        self.library_changed.emit()
        return removed

    def add_files_to_library(self, paths: list[str]) -> None:
        self.scan_library(folders=[p for p in paths if os.path.isdir(p)],
                          files=[p for p in paths if os.path.isfile(p)])

    def remove_from_library(self, paths: list[str]) -> None:
        for path in paths:
            self.db.remove_track(path)
        self.library_changed.emit()

    def set_favourite(self, path: str, favourite: bool) -> None:
        self.db.set_favourite(path, favourite)
        if path in self._metadata_cache:
            self._metadata_cache[path].favourite = favourite
        if self.current_track and self.current_track.path == path:
            self.current_track.favourite = favourite
        self.favourites_changed.emit()

    def clear_history(self) -> None:
        self.db.clear_history()
        self.history_changed.emit()

    def save_metadata(self, path: str, changes: dict[str, str]) -> TrackInfo:
        """Write tags (raises MetadataError) and refresh every view of the file."""
        info = md.write_metadata(path, changes)
        self.refresh_file(path, info)
        return info

    def refresh_file(self, path: str, info: TrackInfo | None = None) -> None:
        """Re-read a file's tags and update the library, playlists and player."""
        if info is None:
            try:
                info = md.read_metadata(path)
            except md.MetadataError:
                return
        self._metadata_cache.pop(path, None)
        if self.db.get_track(path) is not None:
            self.db.upsert_track(info)
            self.library_changed.emit()
        for playlist in self.playlists.all():
            touched = False
            for entry in playlist.entries:
                if entry.path == path:
                    entry.title, entry.artist, entry.album = info.title, info.artist, info.album
                    touched = True
            if touched:
                self.playlists.save(playlist)
                self.playlist_changed.emit(playlist.id)
        if self.current_track and self.current_track.path == path:
            self.current_track = self.track_info(path)
            self.track_changed.emit(self.current_track)

    # -- session ---------------------------------------------------------
    def save_session(self) -> None:
        if not self.config.get("general.restore_session", True):
            return
        entry_path = self._current_entry.path if self._current_entry else None
        state = SessionState(
            playlist_id=self._active_id,
            track_index=self.current_index if self.current_index >= 0 else None,
            track_path=entry_path,
            position=round(self.position, 2) if entry_path else 0.0,
            was_playing=self.state is PlaybackState.PLAYING,
        )
        self.session_store.save(state)
        try:
            self.config.save()
        except OSError:
            log.exception("Could not save settings")

    def restore_session(self) -> None:
        """Restore the last playlist/track/position. Never raises."""
        try:
            if not self.config.get("general.restore_session", True):
                return
            state = self.session_store.load()
            if state.playlist_id and self.playlists.get(state.playlist_id):
                self._active_id = state.playlist_id
            playlist = self.active_playlist
            self.queue.set_shuffle(self.config.get("playback.shuffle", False))
            index = resolve_restore_index(playlist.paths, state)
            self.queue.set_tracks(playlist.paths, index)
            if index is not None and os.path.isfile(playlist.entries[index].path):
                self._current_entry = playlist.entries[index]
                self._set_current_track(self._current_entry.path)
                self.position = state.position
                self.engine.play_file(self._current_entry.path, start=state.position, paused=True)
            self._update_next()
            self.active_playlist_changed.emit(playlist.id)
            self.current_index_changed.emit(playlist.id, self.current_index)
            missing = [e for e in playlist.entries if not e.title]
            if missing:
                self._load_metadata_async([e.path for e in missing if os.path.isfile(e.path)])
        except Exception:
            log.exception("Session restore failed; starting fresh")

    def startup_tasks(self) -> None:
        if self.config.get("library.auto_scan") and self.db.folders():
            QTimer.singleShot(1500, lambda: self.scan_library(None))

    def shutdown(self) -> None:
        self._session_timer.stop()
        self.save_session()
        self.cancel_scan()
        if self._scan_thread is not None:
            self._scan_thread.wait(3000)
        self.engine.shutdown()
        self.playlists.save_all()
        try:
            self.config.save()
        except OSError:
            log.exception("Could not save settings")
        self.db.close()
        self.pool.waitForDone(2000)
        log.info("Shut down cleanly at %s", time.strftime("%H:%M:%S"))
