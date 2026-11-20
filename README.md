# PulseDeck

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Free and open source](https://img.shields.io/badge/free-open%20source-blue.svg)](NOTICE.md)
[![CI](https://github.com/aboycan/pulse-deck/actions/workflows/ci.yml/badge.svg)](https://github.com/aboycan/pulse-deck/actions/workflows/ci.yml)

PulseDeck is a fast, compact desktop music player for your local music
collection. It's built in Python with Qt and has a 10-band equalizer that
processes the audio itself, plus gapless playback, playlists and a
searchable library. It runs on Windows, macOS and Linux.

**Free and open source.** PulseDeck costs nothing and has no ads, no
accounts, no telemetry and no tracking. The full source code is public
under the MIT License.

> PulseDeck is an original, independent project inspired by classic compact
> music players. It contains no Winamp code, skins, artwork or branding. See
> [NOTICE.md](NOTICE.md).

![PulseDeck main window and panels](docs/screenshots/main.png)

*Screenshots are rendered by `scripts/capture_screenshots.py`. Each CI run
regenerates them and uploads them as the `screenshots` artifact.*

## Features

- **Playback:** MP3, FLAC, WAV, AAC/M4A, Ogg Vorbis, Opus, WMA and AIFF.
  Gapless playback, crossfade (0–12 s), seeking, fast-forward and rewind,
  playback speed with pitch correction, balance, ReplayGain (track or
  album), loudness normalization and output device selection.
- **10-band graphic equalizer:** bands at 31 Hz to 16 kHz, ±12 dB each,
  plus preamp, automatic headroom and a clip-protection limiter.
  Adjustments ramp smoothly so there are no clicks. You can bypass the
  equalizer instantly for an A/B comparison. It has 12 built-in presets,
  and you can save, rename, delete, import and export your own.
- **Playlists:** create, rename, duplicate, delete, clear and search.
  Reorder with drag and drop or move tracks up and down. Sort by title,
  artist, album, duration or path. M3U, M3U8 and native JSON are
  supported. Missing files are greyed out, with tools to remove them or
  find where they were moved.
- **Session restore:** PulseDeck reopens the last playlist and track at the
  same position, with your volume, shuffle, repeat and equalizer settings.
- **Music library:** recursive folder scanning in the background with
  duplicate detection. Browse by artist, album, genre or year, and use the
  Favourites, Recently Played, Most Played and Recently Added views. Search
  supports `artist:`, `album:`, `genre:` and `year:` filters.
- **Metadata and artwork:** a detailed track information panel and a safe
  tag editor. Tags are written to a verified temporary copy, the audio data
  is never touched, and the original tags can be restored. Embedded and
  folder artwork is cached, can be viewed full size, and is never
  downloaded from the internet.
- **Right-click menus** for songs, playlists, albums and artists.
- **Desktop integration:** system tray or menu bar icon, track-change
  notifications, system-wide media keys (Windows, Linux MPRIS, and macOS
  with pyobjc), drag and drop, file associations, single instance,
  always on top and a compact mode.
- **Themes:** Classic Dark, Modern Dark, Light and High Contrast. You can
  set a custom accent colour and font size, or add your own themes as JSON
  files (see [docs/THEMES.md](docs/THEMES.md)).
- **Configurable keyboard shortcuts:** defaults are listed below.

## Install

Download the installer for your system from the
[Releases page](https://github.com/aboycan/pulse-deck/releases). You
don't need to install Python, FFmpeg or mpv separately.

| System | File | Notes |
|---|---|---|
| Windows 10 / 11 (64-bit) | `PulseDeck-Setup-x64.exe` | Start Menu shortcut, optional desktop icon and file associations. Uninstall from *Settings > Apps*. |
| Windows on ARM | `PulseDeck-Setup-ARM64.exe` | Experimental. Only published when that build succeeds. |
| macOS (Apple Silicon) | `PulseDeck-macOS-AppleSilicon.dmg` | Open the DMG and drag PulseDeck to Applications. |
| macOS (Intel) | `PulseDeck-macOS-Intel.dmg` | Same as above. |
| Linux (any distribution) | `PulseDeck-x86_64.AppImage` | `chmod +x` the file, then run it. |
| Debian / Ubuntu | `pulsedeck_<version>_amd64.deb` | `sudo apt install ./pulsedeck_*.deb` |
| Fedora / openSUSE | `pulsedeck-<version>-1.x86_64.rpm` | `sudo dnf install ./pulsedeck-*.rpm` |

**Unsigned macOS builds:** the first time you open PulseDeck, right-click
it and choose *Open*. Builds are signed and notarized when the maintainers
add Apple Developer credentials to the release workflow.

### Uninstalling

| System | Steps |
|---|---|
| Windows | Use *Settings > Apps*. The uninstaller asks whether to delete your settings too. |
| macOS | Drag `PulseDeck.app` to the Bin. Your data is in `~/Library/Application Support/PulseDeck` if you want to remove it. |
| Linux | Run `sudo apt remove pulsedeck` or `sudo dnf remove pulsedeck`, or delete the AppImage. Your data is in `~/.config/pulsedeck` and `~/.local/share/pulsedeck`. |

Upgrading keeps your playlists, library and settings.

## Keyboard shortcuts

On macOS, *Ctrl* means the Command key. You can change every shortcut in
*Settings > Keyboard*.

| Shortcut | Action |
|---|---|
| Space | Play or pause |
| Ctrl+O / Ctrl+Shift+O | Open files / open a folder |
| Ctrl+S / Ctrl+N | Save playlist / new playlist |
| Ctrl+F | Search |
| Ctrl+Right / Ctrl+Left | Next / previous track |
| Ctrl+Up / Ctrl+Down | Volume up / down |
| Ctrl+M | Mute |
| Shift+Right / Shift+Left | Fast forward / rewind |
| Ctrl+H / Ctrl+R | Shuffle / cycle repeat (off, all, one) |
| Ctrl+1 to Ctrl+4 | Show or hide the Playlist, Equalizer, Library and Info panels |
| Escape | Close the active dialog |

## Running from source (one-step setup)

> **An internet connection is required for the first-time setup.** It
> downloads about 150 MB: Qt for Python, the libmpv audio engine and other
> packages. PulseDeck then takes roughly 350 MB on disk and runs fully
> offline.

1. Download and unzip the source, or `git clone https://github.com/aboycan/pulse-deck.git`.
2. Run the installer for your system:

| System | Install (once) | Start PulseDeck |
|---|---|---|
| **Windows 10/11** | Double-click **`install.py`** | Use the **PulseDeck** shortcut (Start Menu or Desktop), or double-click **`PulseDeck.pyw`** |
| **macOS** | In Terminal: `./install.sh` | `./run.sh` |
| **Linux** | In a terminal: `./install.sh` | `./run.sh` |

> **Windows Smart App Control:** Windows blocks `.bat` files that came from
> the internet and offers no "Run anyway" option. Use `install.py` and
> `PulseDeck.pyw`, which run through the signed Python launcher and are
> allowed. `install.bat` and `run.bat` are kept for PCs without Smart App
> Control. If double-clicking a `.py` file opens an editor instead, run
> `py install.py` in a terminal in this folder.

The installer handles all the prerequisites:

- **Python 3.11+:** if it's missing, the installer offers to install it.
  Windows uses `winget`, macOS uses Homebrew, and Linux uses apt, dnf,
  zypper or pacman.
- **Python packages:** PySide6, python-mpv, Mutagen and Pillow go into a
  private `.venv` folder, so nothing is installed system-wide.
- **libmpv (the audio engine):**
  - Windows: downloads the latest `mpv-dev-x86_64-<date>.7z` from
    [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake/releases)
    and extracts `libmpv-2.dll` automatically. No 7-Zip needed, because
    Windows 10 and 11 can unpack it themselves.
  - macOS: `brew install mpv` (Homebrew must already be installed; see
    https://brew.sh).
  - Linux: installs the system package (`libmpv2`, `libmpv1` or
    `mpv-libs`) after asking for your password.
- Finally, it runs a self-test. On Windows, it then creates **PulseDeck**
  shortcuts in the Start Menu, on the Desktop and in this folder. Use
  `--no-desktop` to skip the Desktop one.

Running the installer again is safe; it only redoes what's missing and
removes packages PulseDeck doesn't need. Add `--yes` to skip the
confirmation prompts. Developers who want to run the tests should add
`--dev`, which installs pytest, NumPy, Ruff and mypy (about 135 MB more). You can also run the steps
yourself: `python scripts/setup_dev.py`, or just the audio engine with
`python scripts/fetch_libmpv.py`.

If PulseDeck can't load libmpv, it still opens but shows a message that
playback is disabled. Run the installer again to fix it.

### Uninstalling a source setup

Close PulseDeck. Then do one of these:
- Windows: use **Uninstall PulseDeck** in the Start Menu, or double-click
  `uninstall.py`.
- macOS/Linux: run `python3 uninstall.py`.

The uninstaller removes the shortcuts, the `.venv` folder and the
downloaded audio engine. After that you can delete the folder. It asks
before deleting your settings, playlists and library, and keeps them by
default. It never touches your music files.

Run the tests with `pytest` (set up with `install.py --dev` or
`./install.sh --dev` first). Some tests need ffmpeg, libmpv, Mutagen or a
Qt platform; they are skipped when those aren't available. CI runs the full
suite on Windows, macOS and Linux.

## Building installers

See [docs/BUILDING.md](docs/BUILDING.md). In short, on each platform run
`python scripts/build_windows.py`, `python scripts/build_macos.py` or
`python scripts/build_linux.py`. Pushing a `v*` tag makes GitHub Actions
build every installer on native runners and publish a release.

## Documentation

- [docs/FEATURES.md](docs/FEATURES.md): user guide
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the code is organised
- [docs/THEMES.md](docs/THEMES.md): theme file format
- [docs/BUILDING.md](docs/BUILDING.md): packaging and releases
- [CONTRIBUTING.md](CONTRIBUTING.md)

## License

PulseDeck is free and open-source software.
Copyright © 2026 Madhu Kumar and PulseDeck contributors.

| You have | Licence |
|---|---|
| The source code (this repository) | [MIT](LICENSE) |
| A packaged installer (`.exe`, `.dmg`, `.AppImage`, `.deb`, `.rpm`) | GPL-3.0-or-later as a whole, because it bundles Mutagen and GPL builds of libmpv. PulseDeck's own code inside it is still MIT. |

Using PulseDeck carries no obligations. If you redistribute an installer,
you must also offer its source code, and this repository is that source.

Third-party components keep their own licences. They're listed in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md), and their full texts
are in [`licenses/`](licenses/). [NOTICE.md](NOTICE.md) has the details,
including trademark notices.
