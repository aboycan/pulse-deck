# Building PulseDeck installers

> **Status:** these scripts and the release workflow haven't been run yet,
> and no installer has been built or tested. Expect some fixes on the first
> run. PulseDeck is currently installed from source; see the README.

Installers are built **on the platform they target** (PyInstaller cannot
cross-compile). The GitHub Actions release workflow does this on native
runners; this page explains how to do the same by hand.

All builds produce a self-contained one-folder bundle (Python runtime, Qt,
libmpv/FFmpeg, Mutagen, Pillow and PulseDeck's assets), wrap it in the
platform installer, and then run the bundle's `--self-test` to make sure Qt
and libmpv load.

## Licence texts

Every build first runs `scripts/collect_licenses.py`, which needs the
internet. It fills the `licenses/` folder with:
- the licence files shipped by each bundled Python package, copied verbatim;
- CPython's licence;
- the canonical GPL-2.0, GPL-3.0, LGPL-2.1 and LGPL-3.0 texts from gnu.org.

The PyInstaller spec refuses to build if that folder is incomplete, and it
copies the folder into every installer. The Windows installer shows
`installers/windows/INSTALLER_LICENSE.txt`, which explains that the
installer as a whole is GPL-3.0-or-later while PulseDeck's own code is MIT.

## Common prerequisites

- Python 3.11 or 3.12
- `pip install -e ".[build]"` (adds PyInstaller)
- A libmpv shared library for the target platform. Point `PULSEDECK_LIBMPV` at
  it, or let the scripts find it in the default locations below.

## Windows (x64, optional ARM64)

1. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php).
2. Make sure you're online. The build downloads the latest
   `mpv-dev-x86_64-<date>.7z` (or `mpv-dev-aarch64-...` for ARM64) from
   <https://github.com/shinchiro/mpv-winbuild-cmake/releases> and extracts
   `libmpv-2.dll` automatically through `scripts/fetch_libmpv.py`. To use
   your own copy instead, set `PULSEDECK_LIBMPV`.
3. Run:
   ```powershell
   python scripts\build_windows.py            # or --arch arm64
   ```
4. Output: `dist\PulseDeck-Setup-x64.exe`.

The installer supports Windows 10 (1809+) and 11, installs per-machine or
per-user, adds a Start Menu shortcut and optional desktop shortcut and file
associations, upgrades in place (stable `AppId`), and keeps user data on
uninstall unless the user explicitly chooses to delete it.

## macOS (Intel and Apple Silicon)

1. `brew install mpv`
2. Run `python scripts/build_macos.py`.
3. Output: `dist/PulseDeck-macOS-AppleSilicon.dmg` on an Apple Silicon Mac,
   `dist/PulseDeck-macOS-Intel.dmg` on an Intel Mac.

**Minimum macOS version.** Homebrew bottles target the macOS version they were
built for, so the app requires at least the build machine's macOS (the CI uses
macOS 15 for both Intel and Apple Silicon). For wider compatibility,
build libmpv yourself with `MACOSX_DEPLOYMENT_TARGET` set and pass it with
`PULSEDECK_LIBMPV`.

**Signing and notarization** (optional but recommended for public releases):

```bash
xcrun notarytool store-credentials pulsedeck --apple-id you@example.com --team-id TEAMID
export PULSEDECK_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export PULSEDECK_NOTARY_PROFILE=pulsedeck
python scripts/build_macos.py
```

In CI, add the secrets `MACOS_CERTIFICATE` (base64 .p12),
`MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGNING_IDENTITY`, `NOTARY_APPLE_ID`,
`NOTARY_TEAM_ID` and `NOTARY_PASSWORD`; the release workflow then signs and
notarizes automatically. Without them, builds are ad-hoc signed.

## Linux (AppImage, DEB, RPM)

Build on the **oldest** distribution you want to support; the CI uses Ubuntu 22.04.

```bash
sudo apt install libmpv-dev rpm libfuse2
curl -fsSLO https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
export APPIMAGETOOL=$PWD/appimagetool-x86_64.AppImage
python scripts/build_linux.py --formats appimage,deb,rpm
```

Outputs in `dist/`: `PulseDeck-x86_64.AppImage`, `pulsedeck_<ver>_amd64.deb`,
`pulsedeck-<ver>-1.x86_64.rpm`. On an ARM64 machine the same command produces
the `aarch64`/`arm64` variants.

The DEB and RPM install to `/opt/pulsedeck` with a `/usr/bin/pulsedeck`
launcher, desktop entry, AppStream metadata and icons. User data in
`~/.config/pulsedeck` and `~/.local/share/pulsedeck` is never removed by the
package manager.

## Release workflow

`.github/workflows/release.yml` runs on tags `v*`:

| Job | Runner | Artifact |
|---|---|---|
| Windows x64 | `windows-latest` | `PulseDeck-Setup-x64.exe` |
| Windows ARM64 (experimental) | `windows-11-arm` | `PulseDeck-Setup-ARM64.exe` |
| macOS Intel | `macos-15-intel` | `PulseDeck-macOS-Intel.dmg` |
| macOS Apple Silicon | `macos-15` | `PulseDeck-macOS-AppleSilicon.dmg` |
| Linux x86_64 | `ubuntu-22.04` | AppImage, DEB, RPM (the DEB is installed and self-tested) |
| Linux ARM64 (experimental) | `ubuntu-22.04-arm` | AppImage, DEB, RPM |

The publish job attaches every artifact plus `SHA256SUMS.txt` to a GitHub
release, using the matching section of `CHANGELOG.md` as release notes.

## LGPL-only builds

The default installers are GPL-3.0-or-later as a whole because they include
Mutagen (GPL-2.0+) and GPL builds of libmpv. To ship an LGPL-only build you
would need to replace Mutagen in `library/metadata.py` with an LGPL/MIT tag
library and build mpv with `-Dgpl=false` against an FFmpeg built without
`--enable-gpl`.

## Installer testing checklist

Automated: the build scripts run `--self-test` on the frozen app, and CI
installs the `.deb` and runs it. Before each release also check by hand, on
real machines:

- [ ] Fresh install, launch, play an MP3 and a FLAC file, move EQ sliders and hear the change.
- [ ] Upgrade over the previous version keeps playlists, library and settings.
- [ ] Uninstall removes the app; user data stays unless deletion was requested (Windows prompt).
- [ ] Windows: Start Menu shortcut, optional desktop icon, "Open with PulseDeck" for audio files.
- [ ] macOS: drag-install from DMG, Finder "Open With", media keys (with pyobjc).
- [ ] Linux: AppImage runs on Ubuntu, Fedora and openSUSE; desktop entry and icon appear.
