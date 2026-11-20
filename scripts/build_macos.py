# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Build the macOS .app bundle and drag-and-drop DMG.

Usage (on macOS, from the repository root):
    python scripts/build_macos.py

Build on an Intel Mac (or Intel runner) for PulseDeck-macOS-Intel.dmg and on
an Apple Silicon Mac for PulseDeck-macOS-AppleSilicon.dmg. libmpv is taken
from Homebrew (``brew install mpv``) unless PULSEDECK_LIBMPV is set.

Optional signing / notarization (all must be set to sign):
    PULSEDECK_CODESIGN_IDENTITY  "Developer ID Application: Name (TEAMID)"
    PULSEDECK_NOTARY_PROFILE     keychain profile created with `xcrun notarytool store-credentials`
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from build_common import DIST, artifact_name, machine, pyinstaller, require_libmpv, run, smoke_test, version


def brew_libmpv() -> list[Path]:
    try:
        prefix = subprocess.run(["brew", "--prefix", "mpv"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return []
    lib = Path(prefix) / "lib"
    return [lib / "libmpv.2.dylib", lib / "libmpv.dylib"]


def make_dmg(app: Path, output: Path) -> None:
    output.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as staging:
        stage = Path(staging)
        shutil.copytree(app, stage / app.name, symlinks=True)
        os.symlink("/Applications", stage / "Applications")
        (stage / "Uninstall - read me.txt").write_text(
            "To uninstall PulseDeck, drag PulseDeck from Applications to the Bin.\n"
            "Your settings and playlists are kept in ~/Library/Application Support/PulseDeck;\n"
            "delete that folder too if you want to remove them.\n", encoding="utf-8")
        run(["hdiutil", "create", "-volname", f"PulseDeck {version()}", "-srcfolder", str(stage), "-ov",
             "-format", "UDZO", "-fs", "HFS+", str(output)])


def sign_and_notarize(app: Path, dmg: Path) -> None:
    identity = os.environ.get("PULSEDECK_CODESIGN_IDENTITY")
    profile = os.environ.get("PULSEDECK_NOTARY_PROFILE")
    if not identity:
        print("No signing identity configured: the app is ad-hoc signed only. "
              "Users will need to right-click > Open the first time.")
        return
    entitlements = Path(__file__).resolve().parent.parent / "installers" / "macos" / "entitlements.plist"
    run(["codesign", "--force", "--deep", "--options", "runtime", "--timestamp", "--entitlements",
         str(entitlements), "--sign", identity, str(app)])
    run(["codesign", "--verify", "--deep", "--strict", str(app)])
    if profile:
        make_dmg(app, dmg)
        run(["codesign", "--sign", identity, "--timestamp", str(dmg)])
        run(["xcrun", "notarytool", "submit", str(dmg), "--keychain-profile", profile, "--wait"])
        run(["xcrun", "stapler", "staple", str(dmg)])


def main() -> None:
    libmpv = require_libmpv(brew_libmpv())
    arch = machine()
    pyinstaller(libmpv, {"PULSEDECK_ARCH": arch})
    app = DIST / "PulseDeck.app"
    smoke_test(app / "Contents" / "MacOS" / "PulseDeck")
    dmg = DIST / artifact_name("macos", arch)
    sign_and_notarize(app, dmg)
    if not dmg.exists():
        make_dmg(app, dmg)
    print(f"Disk image: {dmg}")


if __name__ == "__main__":
    main()
