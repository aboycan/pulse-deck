# Architecture

```
            ┌─────────────────────────── ui/ (PySide6) ───────────────────────────┐
            │ MainWindow · PlaylistWindow · EqualizerWindow · LibraryWindow ·     │
            │ InfoWindow · SettingsWindow · context menus · tray / media keys     │
            └───────────────┬───────────────────────────────▲────────────────────┘
                     method calls                       Qt signals
            ┌───────────────▼───────────────────────────────┴────────────────────┐
            │                application.AppController (QObject)                  │
            └───────┬───────────────────┬──────────────────────┬─────────────────┘
                    │                   │                      │
      ┌─────────────▼─────┐   ┌─────────▼──────────┐   ┌───────▼────────────┐
      │ audio/            │   │ library/ + core/db │   │ playlists/         │
      │ PlaybackEngine    │   │ scanner, metadata, │   │ model, M3U, JSON,  │
      │ PlaybackQueue     │   │ artwork, search,   │   │ manager, session   │
      │ equalizer, filters│   │ SQLite database    │   │                    │
      │ MpvBackend ───────┼─► libmpv / FFmpeg     │   │                    │
      └───────────────────┘   └────────────────────┘   └────────────────────┘
```

**Rule:** only `ui/` and `application.py` import Qt. Everything in `audio/`,
`library/`, `playlists/` and `core/` is plain Python, which keeps it
testable without a display. (The one exception is `ui/engine_bridge.py`,
which turns engine callbacks into queued Qt signals.)

## Audio engine

- `PlaybackEngine` owns a worker thread. Public methods post tasks to it and
  return immediately, so the GUI never blocks on audio I/O. A 25 ms tick
  updates position, runs crossfades and ramps equalizer changes.
- `MpvBackend` wraps one libmpv instance with video disabled. Gapless
  playback works by appending the next track to mpv's internal playlist with
  `gapless-audio=weak` and `prefetch-playlist`. A crossfade uses a second
  backend and an equal-power volume curve.
- `SimulatedBackend` implements the same interface with a virtual clock. The
  tests use it, and the app falls back to it if libmpv can't be loaded.

## Equalizer DSP

`audio_filters.build_chain()` turns the EQ state into an FFmpeg filter chain
inside libmpv:

```
volume (preamp + auto headroom) → 10 × equalizer (peaking biquad, 1 octave)
    → [pan (balance)] → [dynaudnorm] → alimiter (clip protection)
```

Each filter has a label (`@eq0` … `@eq9`, `@preamp`). While the chain
structure stays the same, slider moves become `af-command <label> gain <dB>`
calls that change coefficients in place, stepped at most 1 dB per tick. That
avoids rebuilding the graph and prevents audible clicks. Disable and bypass
remove the EQ filters entirely, so you hear untouched audio. The tests
render audio through the same chain with ffmpeg to check that the boosts,
cuts, bypass and clip protection are measurable.

## Library

`LibraryScanner` walks folders without following symlinked directories and
skips files whose size and modification time are unchanged. It reads tags
with Mutagen and upserts rows into SQLite (`core/database.py`, WAL mode,
thread-safe). Duplicate detection uses canonical paths, plus an optional
fingerprint of title, artist, album and duration. Scans run in a `QThread`
and can be cancelled.

## Persistence

| File | Contents |
|---|---|
| `settings.json` (config dir) | All preferences, EQ state, window geometry, shortcuts |
| `eq_presets/*.json` (config dir) | Custom equalizer presets |
| `themes/*.json` (config dir) | User themes |
| `playlists/*.json` + `order.json` (data dir) | Saved playlists |
| `session.json` (data dir) | Last playlist, track, position |
| `library.sqlite3` (data dir) | Library, favourites, history |
| `metadata_backups/` (data dir) | Original tags saved before the first edit |
| `artwork/` (cache dir) | Thumbnail cache |
| `logs/pulsedeck.log` (data dir) | Structured JSON-lines log (rotating) |

Every write is atomic: the data goes to a temp file, then `os.replace`. A
corrupt settings or session file is set aside, and PulseDeck starts with
defaults instead of crashing. Set `PULSEDECK_HOME` to move all of these
files, for example to run a portable copy or to isolate tests.
