# Contributing to PulseDeck

Thanks for helping! Bug reports, fixes, themes, translations and docs are all welcome.

## Ground rules

1. **Keep it original.** Never add code, skins, icons, sounds, artwork or
   layouts copied from Winamp or any other proprietary player. New visual
   assets must be your own work (or permissively licensed with attribution
   recorded in `THIRD_PARTY_LICENSES.md`).
2. **License.** By contributing you agree that your contribution is released
   under the MIT License.
3. **Dependencies** must have an open-source licence compatible with how we
   distribute (see `NOTICE.md`). Add every new runtime dependency to
   `THIRD_PARTY_LICENSES.md` in the same pull request.
4. **No network access** for metadata or artwork without an explicit,
   opt-in design discussion first.

## Development setup

Run `py install.py --dev` (Windows) or `./install.sh --dev` (macOS/Linux) once. You'll
need an internet connection. It creates `.venv`, installs the dev
dependencies and downloads libmpv. Then:

```bash
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pytest                 # unit + integration tests
ruff check src tests scripts
```

Install libmpv and ffmpeg (see README) to run the playback and equalizer
tests that render real audio. Set `QT_QPA_PLATFORM=offscreen` to run the GUI
smoke tests without a display.

## Code layout

`ui/` talks only to `application.AppController`. The controller owns the
audio engine (`audio/`), library (`library/`, `core/database.py`) and
playlists (`playlists/`). Keep these layers separate: audio, library and
playlist modules must not import Qt. See `docs/ARCHITECTURE.md`.

## Pull requests

- One topic per PR, with tests for behaviour changes.
- Update `CHANGELOG.md` under *Unreleased*.
- Make sure CI is green on all three platforms.
- For UI changes, attach before/after screenshots (`scripts/capture_screenshots.py`).

## Reporting bugs

Use the issue templates. Include your OS, PulseDeck version (*Help > About*)
and the log file (*Help > Open Log Folder*). Please don't attach copyrighted
music - describe the file format instead, or generate a test tone:

```bash
ffmpeg -f lavfi -i "sine=frequency=440:duration=5" tone.flac
```

## Releasing (maintainers)

1. Bump `__version__` in `src/pulsedeck/__init__.py`, `version` in
   `pyproject.toml`, and the release entry in
   `installers/linux/io.github.pulsedeck.PulseDeck.metainfo.xml`.
2. Move *Unreleased* notes in `CHANGELOG.md` under the new version.
3. Tag `vX.Y.Z` and push the tag. The release workflow builds and publishes everything.
