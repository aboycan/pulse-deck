# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Build the macOS .app bundle and drag-and-drop DMG.

Usage (on macOS, from the repository root, after `bash install.sh`):
    .venv/bin/pip install -e ".[build,macos]"
    .venv/bin/python scripts/build_macos.py

The result is dist/PulseDeck-macOS-<AppleSilicon|Intel>.dmg containing a
self-contained PulseDeck.app (Python, Qt, libmpv/FFmpeg and every library
they need), so the Mac it runs on needs no Python or Homebrew.

A DMG built on your own Mac carries no "downloaded from the internet"
quarantine flag, so it installs and opens there without any Gatekeeper
prompt. Copies downloaded by other people are unsigned: they approve the
app once in System Settings > Privacy & Security > Open Anyway.

Build on an Intel Mac (or Intel runner) for PulseDeck-macOS-Intel.dmg and on
an Apple Silicon Mac for PulseDeck-macOS-AppleSilicon.dmg. libmpv is taken
from Homebrew (``brew install mpv``) unless PULSEDECK_LIBMPV is set.

Optional signing / notarization (all must be set to sign):
    PULSEDECK_CODESIGN_IDENTITY  "Developer ID Application: Name (TEAMID)"
    PULSEDECK_NOTARY_PROFILE     keychain profile created with `xcrun notarytool store-credentials`
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
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


#: Library locations that exist only on the build Mac (Homebrew, MacPorts, local installs).
EXTERNAL_PREFIXES = ("/opt/homebrew/", "/usr/local/", "/opt/local/")


def check_environment() -> None:
    """Fail early, with a clear message, if the build tools aren't installed in this Python."""
    missing = []
    for module, package in (("PyInstaller", "pyinstaller"), ("PySide6", "PySide6-Essentials"),
                            ("mutagen", "mutagen"), ("mpv", "python-mpv")):
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    if missing:
        raise SystemExit(
            f"Missing in this Python ({sys.executable}): {', '.join(missing)}\n"
            "Run from the repository root:\n"
            "  bash install.sh\n"
            '  .venv/bin/pip install -e ".[build,macos]"\n'
            "  .venv/bin/python scripts/build_macos.py"
        )


def deployment_target() -> str:
    """Oldest macOS the app claims to support.

    Homebrew's libraries are built for the Mac they were installed on, so the
    app can't honestly promise more than the build Mac's own macOS version.
    """
    if os.environ.get("MACOSX_DEPLOYMENT_TARGET"):
        return os.environ["MACOSX_DEPLOYMENT_TARGET"]
    release = platform.mac_ver()[0] or "11.0"
    major = release.split(".")[0]
    return f"{major}.0"


def mach_o_files(app: Path) -> list[Path]:
    files = []
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with open(path, "rb") as handle:
                magic = handle.read(4)
            if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                files.append(path)
    return files


def external_references(otool_output: str) -> list[str]:
    """Library paths from ``otool -L`` output that point outside the app and outside macOS itself."""
    refs = []
    for line in otool_output.splitlines()[1:]:
        lib = line.strip().split(" (compatibility", 1)[0].strip()
        if lib.startswith(EXTERNAL_PREFIXES):
            refs.append(lib)
    return refs


def verify_self_contained(app: Path) -> None:
    """Make sure the app loads nothing from Homebrew, so it works on Macs without it."""
    problems = []
    binaries = mach_o_files(app)
    for binary in binaries:
        out = subprocess.run(["otool", "-L", str(binary)], capture_output=True, text=True).stdout
        for ref in external_references(out):
            problems.append(f"{binary.relative_to(app)} -> {ref}")
    if problems:
        listing = "\n  ".join(problems[:25])
        more = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        raise SystemExit(f"The app still depends on libraries outside the bundle:\n  {listing}{more}")
    print(f"Self-contained: {len(binaries)} binaries checked, no Homebrew or /usr/local dependencies.")


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
    check_environment()
    libmpv = require_libmpv(brew_libmpv())
    arch = machine()
    target = deployment_target()
    print(f"Building PulseDeck {version()} for {arch}, macOS {target} or later")
    pyinstaller(libmpv, {"PULSEDECK_ARCH": arch, "MACOSX_DEPLOYMENT_TARGET": target})
    app = DIST / "PulseDeck.app"
    verify_self_contained(app)
    smoke_test(app / "Contents" / "MacOS" / "PulseDeck")
    dmg = DIST / artifact_name("macos", arch)
    sign_and_notarize(app, dmg)
    if not dmg.exists():
        make_dmg(app, dmg)
    print(f"Disk image: {dmg}")


if __name__ == "__main__":
    main()
