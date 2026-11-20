# Third-party components and licences

PulseDeck's own code is licensed under the MIT License (see `LICENSE`).
The components below keep their own licences. Their full texts are in
the `licenses/` folder, which `scripts/collect_licenses.py` generates and
which ships inside every installer. See `NOTICE.md` for what this means
for using and redistributing PulseDeck.

**Column meanings:**
- **Installers:** whether the component is bundled inside the packaged
  installers.
- **Source setup:** whether `install.py` downloads the component into
  `.venv`.
- **Dev only:** used only to build or test PulseDeck, never shipped to
  users.

## Runtime components

| Component | Used for | Licence (SPDX) | Installers | Source setup | Upstream source |
|---|---|---|---|---|---|
| CPython 3.11+ | Runtime | PSF-2.0 | yes | your own Python | https://www.python.org/ |
| Qt 6 via PySide6-Essentials | User interface (QtCore, QtGui, QtWidgets, QtNetwork, QtDBus) | LGPL-3.0-only (also GPL / commercial) | yes | yes | https://code.qt.io/ |
| shiboken6 | PySide6 binding runtime | LGPL-3.0-only | yes | yes | https://code.qt.io/ |
| libmpv (mpv) | Audio decoding, gapless playback, output, filter graph | GPL-2.0-or-later (builds used); LGPL-2.1-or-later in LGPL builds | yes | yes (downloaded) | https://github.com/mpv-player/mpv |
| FFmpeg (inside libmpv) | Codecs and the `equalizer`, `volume`, `alimiter`, `dynaudnorm` filters | GPL-2.0-or-later (builds used); LGPL-2.1-or-later otherwise | yes | yes (inside libmpv) | https://ffmpeg.org/ |
| Libraries linked into libmpv (libass, libplacebo, zlib, codec libraries…) | libmpv dependencies | Various permissive, LGPL and GPL licences | yes | yes (inside libmpv) | See each libmpv build's notices |
| python-mpv | Python binding for libmpv | LGPL-2.1-or-later (dual-licensed with GPL-2.0-or-later) | yes | yes | https://github.com/jaseg/python-mpv |
| Mutagen | Reading and writing audio tags | GPL-2.0-or-later | yes | yes | https://github.com/quodlibet/mutagen |
| Pillow | Artwork decoding and thumbnails | MIT-CMU | yes | yes | https://github.com/python-pillow/Pillow |
| pyobjc-framework-MediaPlayer (macOS only) | System-wide media keys | MIT | macOS builds | macOS only | https://github.com/ronaldoussoren/pyobjc |
| py7zr (optional) | Unpacking the libmpv download if Windows' built-in `tar` can't | LGPL-2.1-or-later | no | only if needed | https://github.com/miurahr/py7zr |

## Build and development tools (dev only)

| Tool | Used for | Licence | Upstream |
|---|---|---|---|
| PyInstaller | Packaging | GPL-2.0-or-later with a bootloader exception (the bundled bootloader may be distributed under any licence) | https://github.com/pyinstaller/pyinstaller |
| Inno Setup | Windows installer | Inno Setup License (permissive) | https://jrsoftware.org/isinfo.php |
| appimagetool | AppImage creation | MIT | https://github.com/AppImage/appimagetool |
| pytest, pytest-qt | Tests | MIT | https://pytest.org/ |
| NumPy | Equalizer measurement tests | BSD-3-Clause | https://numpy.org/ |
| Ruff | Linting | MIT | https://github.com/astral-sh/ruff |
| mypy | Type checking | MIT | https://github.com/python/mypy |
| GitHub Actions | CI and release builds | Service, not distributed | https://github.com/features/actions |

## Where the libmpv binaries come from

| Platform | Source | Configuration |
|---|---|---|
| Windows | `mpv-dev` builds from https://github.com/shinchiro/mpv-winbuild-cmake/releases, downloaded by `scripts/fetch_libmpv.py` | Statically linked, GPL configuration. `src/pulsedeck/audio/lib/SOURCE.txt` records the exact build. |
| macOS | Homebrew `mpv` formula | GPL configuration; its dylib dependencies are bundled by PyInstaller. |
| Linux | Distribution `libmpv` package (Ubuntu 22.04 in CI) | GPL configuration; dependencies are bundled by PyInstaller. |

## Licence texts in `licenses/`

| File | Covers |
|---|---|
| `GPL-3.0.txt` | Each installer as a whole; also the base licence of Qt's LGPL-3.0 |
| `LGPL-3.0.txt` | Qt / PySide6-Essentials / shiboken6 |
| `GPL-2.0.txt` | Mutagen, the libmpv/FFmpeg builds used, python-mpv's GPL option |
| `LGPL-2.1.txt` | python-mpv (licence used), libmpv/FFmpeg in LGPL builds |
| `Python-PSF-2.0.txt` | CPython |
| `python-packages/<name>-<version>/` | Licence files shipped by each bundled Python package, copied verbatim |

## LGPL-only builds

The default installers are GPL-3.0-or-later as a whole. To produce an
LGPL-only build, you would need to:
1. Replace Mutagen in `src/pulsedeck/library/metadata.py` with a tag
   library under the LGPL or MIT.
2. Link against libmpv built with `-Dgpl=false`.
3. Use an FFmpeg built without `--enable-gpl`.

See `docs/BUILDING.md`.
