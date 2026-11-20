# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""libmpv audio backend (via the ``python-mpv`` binding).

libmpv gives us FFmpeg decoding for every supported format, gapless
playback, accurate seeking, ReplayGain, output-device selection and the
``lavfi`` audio filter graph that runs the equalizer.

In packaged builds libmpv is shipped next to the executable; this module
points ``python-mpv`` at that copy before importing it, so end users never
need to install mpv or FFmpeg.
"""

from __future__ import annotations

import ctypes.util
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from pulsedeck.audio.backend import AudioBackend, AudioParams, BackendCallbacks
from pulsedeck.core import platform

log = logging.getLogger(__name__)

_LIB_NAMES = {
    "windows": ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll"),
    "macos": ("libmpv.2.dylib", "libmpv.dylib", "libmpv.1.dylib"),
    "linux": ("libmpv.so.2", "libmpv.so.1", "libmpv.so"),
}


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("PULSEDECK_LIBMPV_DIR")
    if env:
        dirs.append(Path(env))
    if platform.is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        dirs += [platform.bundle_dir(), platform.bundle_dir() / "lib", exe_dir, exe_dir.parent / "Frameworks"]
    dirs.append(Path(__file__).resolve().parent / "lib")
    return dirs


def find_bundled_libmpv() -> Path | None:
    for directory in _candidate_dirs():
        for name in _LIB_NAMES[platform.platform_name()]:
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def import_mpv() -> Any:
    """Import ``python-mpv``, preferring a bundled libmpv."""
    bundled = find_bundled_libmpv()
    if bundled is not None:
        log.info("Using bundled libmpv: %s", bundled)
        if platform.IS_WINDOWS:
            os.add_dll_directory(str(bundled.parent))  # type: ignore[attr-defined]
            os.environ["PATH"] = str(bundled.parent) + os.pathsep + os.environ.get("PATH", "")
        else:
            original = ctypes.util.find_library

            def _find_library(name: str) -> str | None:
                if name == "mpv":
                    return str(bundled)
                return original(name)

            ctypes.util.find_library = _find_library  # type: ignore[assignment]
    import mpv  # noqa: PLC0415  (deferred so the loader hook above applies)

    return mpv


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


class MpvBackend(AudioBackend):
    name = "mpv"

    def __init__(self, callbacks: BackendCallbacks | None = None, audio_output: str | None = None) -> None:
        self.callbacks = callbacks or BackendCallbacks()
        mpv = import_mpv()
        options: dict[str, Any] = {
            "video": False,
            "ytdl": False,
            "idle": True,
            "keep_open": False,
            "input_default_bindings": False,
            "input_vo_keyboard": False,
            "osc": False,
            "terminal": False,
            "gapless_audio": "weak",
            "prefetch_playlist": True,
            "audio_display": False,
            "replaygain": "no",
            "audio_pitch_correction": True,
            "volume_max": 100,
            "cache": "auto",
        }
        if audio_output:
            options["ao"] = audio_output
        self._mpv = mpv.MPV(log_handler=self._on_log, loglevel="warn", **options)
        self._lock = threading.RLock()
        self._next_path: str | None = None
        self._current_path: str | None = None
        self._pending_start: float = 0.0
        self._removing = False
        self._last_error: str = ""
        self._stopped_by_user = False
        self._mpv.observe_property("playlist-pos", self._on_playlist_pos)
        self._mpv.observe_property("idle-active", self._on_idle)
        self._mpv.register_event_callback(self._on_event)

    # -- mpv callbacks (run on python-mpv's event thread) ------------------
    def _on_log(self, level: str, component: str, message: str) -> None:
        text = message.strip()
        if level in ("error", "fatal"):
            self._last_error = text
            log.warning("mpv[%s] %s", component, text)
        else:
            log.debug("mpv[%s] %s: %s", component, level, text)

    def _on_event(self, event: Any) -> None:
        try:
            info = event.as_dict(decoder=_decode) if hasattr(event, "as_dict") else {}
        except Exception:  # pragma: no cover - binding differences
            info = {}
        raw_name = _decode(info.get("event"))
        name = str(raw_name).lower().replace("_", "-") if raw_name is not None else ""
        event_id = getattr(getattr(event, "event_id", None), "value", None)
        if "file-loaded" in name or event_id == 8:  # MPV_EVENT_FILE_LOADED
            path = self._safe_get("path")
            if path:
                self._current_path = path
                self.callbacks.on_loaded(path)
        elif "end-file" in name or event_id == 7:  # MPV_EVENT_END_FILE
            reason = _decode(info.get("reason"))
            if reason in ("error", 4):
                detail = info.get("file_error") or info.get("error")
                error = self._last_error or (str(_decode(detail)) if detail else "") or "Playback error"
                failed = self._current_path or self._next_path or ""
                # The core goes idle after a failure; report the error only,
                # not an additional end-of-track.
                self._current_path = None
                self._last_error = ""
                self.callbacks.on_error(failed, error)

    def _on_playlist_pos(self, _name: str, value: Any) -> None:
        if value == 1 and self._next_path is not None and not self._removing:
            with self._lock:
                path = self._next_path
                self._next_path = None
                self._current_path = path
                self._removing = True
            threading.Thread(target=self._drop_finished_entry, daemon=True).start()
            self.callbacks.on_auto_advance(path)

    def _drop_finished_entry(self) -> None:
        try:
            self._mpv.command("playlist-remove", 0)
        except Exception:  # pragma: no cover
            log.debug("playlist-remove failed", exc_info=True)
        finally:
            self._removing = False

    def _on_idle(self, _name: str, idle: Any) -> None:
        if idle and self._current_path is not None:
            self._current_path = None
            if self._stopped_by_user:
                self._stopped_by_user = False
                return
            self.callbacks.on_end()

    # python-mpv's ``player["name"]`` reads/writes the *options/* namespace,
    # which does not contain runtime properties such as time-pos. Attribute
    # access (``player.time_pos``) uses the property API, so go through that.
    def _safe_get(self, prop: str) -> Any:
        try:
            return _decode(getattr(self._mpv, prop.replace("-", "_")))
        except Exception:
            return None

    def _set(self, prop: str, value: Any) -> None:
        setattr(self._mpv, prop.replace("-", "_"), value)

    # -- AudioBackend ------------------------------------------------------
    def load(self, path: str, start: float = 0.0, paused: bool = False) -> None:
        with self._lock:
            self._next_path = None
            # "loadfile replace" switches files without passing through idle.
            self._stopped_by_user = False
            self._last_error = ""
            self._current_path = path
            self._mpv.pause = paused
            # ``start`` is a per-file option; set it globally for this load and
            # clear it once the file is open so pre-fetched files start at 0.
            self._set("start", f"{max(0.0, start):.3f}" if start > 0 else "none")
            self._mpv.command("loadfile", path, "replace")
        if start > 0:
            threading.Timer(0.5, self._clear_start).start()

    def _clear_start(self) -> None:
        try:
            self._set("start", "none")
        except Exception:  # pragma: no cover
            pass

    def set_next(self, path: str | None) -> None:
        with self._lock:
            count = int(self._safe_get("playlist-count") or 0)
            pos = self._safe_get("playlist-pos")
            pos = int(pos) if pos is not None else -1
            # Remove anything queued after the current entry.
            for index in range(count - 1, pos, -1):
                try:
                    self._mpv.command("playlist-remove", index)
                except Exception:
                    pass
            self._next_path = None
            if path and self._current_path is not None:
                self._mpv.command("loadfile", path, "append")
                self._next_path = path

    def play(self) -> None:
        self._mpv.pause = False

    def pause(self) -> None:
        self._mpv.pause = True

    def stop(self) -> None:
        with self._lock:
            self._next_path = None
            if self._current_path is not None:
                self._stopped_by_user = True
            self._mpv.command("stop")

    def seek(self, seconds: float) -> None:
        try:
            self._mpv.command("seek", f"{max(0.0, seconds):.3f}", "absolute+exact")
        except Exception:
            log.debug("seek failed", exc_info=True)

    @property
    def position(self) -> float:
        value = self._safe_get("time-pos")
        return float(value) if value is not None else 0.0

    @property
    def duration(self) -> float:
        value = self._safe_get("duration")
        return float(value) if value is not None else 0.0

    @property
    def is_idle(self) -> bool:
        return bool(self._safe_get("idle-active"))

    def set_volume(self, volume: float) -> None:
        self._mpv.volume = max(0.0, min(100.0, float(volume)))

    def set_muted(self, muted: bool) -> None:
        self._mpv.mute = bool(muted)

    def set_speed(self, speed: float) -> None:
        self._mpv.speed = max(0.25, min(4.0, float(speed)))

    def set_filters(self, af: str) -> None:
        try:
            self._set("af", af)
        except Exception as exc:
            log.error("Could not apply audio filters %r: %s", af, exc)

    def filter_command(self, label: str, command: str, argument: str) -> bool:
        try:
            self._mpv.command("af-command", label, command, argument)
            return True
        except Exception:
            log.debug("af-command %s %s %s failed", label, command, argument, exc_info=True)
            return False

    def set_replaygain(self, mode: str, preamp: float) -> None:
        self._set("replaygain", mode if mode in ("track", "album") else "no")
        self._set("replaygain-preamp", float(preamp))
        self._set("replaygain-clip", False)

    def audio_params(self) -> AudioParams:
        params = self._safe_get("audio-params") or {}
        out = self._safe_get("audio-out-params") or {}
        return AudioParams(
            codec=str(self._safe_get("audio-codec-name") or ""),
            bitrate=int(self._safe_get("audio-bitrate") or 0),
            sample_rate=int(params.get("samplerate", 0) or 0) if isinstance(params, dict) else 0,
            channels=int(params.get("channel-count", 0) or 0) if isinstance(params, dict) else 0,
            output_sample_rate=int(out.get("samplerate", 0) or 0) if isinstance(out, dict) else 0,
        )

    def devices(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for entry in self._safe_get("audio-device-list") or []:
            name = _decode(entry.get("name", ""))
            desc = _decode(entry.get("description", "")) or name
            result.append((name, "System default" if name == "auto" else desc))
        return result or [("auto", "System default")]

    def set_device(self, name: str) -> None:
        try:
            self._set("audio-device", name or "auto")
        except Exception:
            log.warning("Audio device %s unavailable; using default", name)
            self._set("audio-device", "auto")

    def set_gapless(self, enabled: bool) -> None:
        self._set("gapless-audio", "weak" if enabled else "no")

    def shutdown(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:  # pragma: no cover
            pass
