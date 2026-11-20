# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Build Linux packages: AppImage, .deb and (when rpmbuild exists) .rpm.

Usage (on Linux, from the repository root):
    python scripts/build_linux.py [--formats appimage,deb,rpm]

libmpv comes from the system (``sudo apt install libmpv-dev``) unless
PULSEDECK_LIBMPV is set; it and its dependencies are bundled. Build on the
oldest distribution you want to support (CI uses Ubuntu 22.04) because the
result depends on that system's glibc.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from build_common import BUILD, DIST, ROOT, artifact_name, machine, pyinstaller, require_libmpv, run, smoke_test, version

LINUX = ROOT / "installers" / "linux"
ICONS = ROOT / "src" / "pulsedeck" / "assets" / "icons"
DEB_DEPENDS = ("libc6 (>= 2.35), libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libfontconfig1, "
               "libdbus-1-3, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libasound2 | libasound2t64")


def system_libmpv() -> list[Path]:
    found: list[Path] = []
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if "libmpv.so" in line and "=>" in line:
                found.append(Path(line.split("=>")[1].strip()))
    except (OSError, subprocess.CalledProcessError):
        pass
    found.sort(key=lambda p: (".so.2" not in p.name, p.name))
    return found


def install_tree(dest: Path, prefix: str = "/opt/pulsedeck") -> None:
    """Lay out the files shared by the .deb and .rpm packages under ``dest``."""
    app_dir = dest / prefix.lstrip("/")
    shutil.copytree(DIST / "PulseDeck", app_dir, symlinks=True)
    bin_dir = dest / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pulsedeck").symlink_to(f"{prefix}/PulseDeck")
    apps = dest / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    shutil.copy(LINUX / "pulsedeck.desktop", apps / "pulsedeck.desktop")
    meta = dest / "usr" / "share" / "metainfo"
    meta.mkdir(parents=True)
    shutil.copy(LINUX / "io.github.pulsedeck.PulseDeck.metainfo.xml", meta)
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        target = dest / "usr" / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        target.mkdir(parents=True)
        shutil.copy(ICONS / f"pulsedeck-{size}.png", target / "pulsedeck.png")
    scalable = dest / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    scalable.mkdir(parents=True)
    shutil.copy(ICONS / "pulsedeck.svg", scalable / "pulsedeck.svg")
    docs = dest / "usr" / "share" / "doc" / "pulsedeck"
    docs.mkdir(parents=True)
    for name in ("LICENSE", "NOTICE.md", "THIRD_PARTY_LICENSES.md", "README.md"):
        shutil.copy(ROOT / name, docs / name)
    shutil.copytree(ROOT / "licenses", docs / "licenses")
    # Debian policy: machine-readable copyright summary.
    (docs / "copyright").write_text(
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
        "Upstream-Name: PulseDeck\nSource: https://github.com/aboycan/pulse-deck\n\n"
        "Files: *\nCopyright: 2026 Madhu Kumar and PulseDeck contributors\nLicense: MIT\n\n"
        "Files: opt/pulsedeck/_internal/*\nCopyright: Their respective authors\n"
        "License: GPL-3.0-or-later\n Bundled third-party components (Qt LGPL-3.0, libmpv/FFmpeg GPL-2.0+,\n"
        " Mutagen GPL-2.0+, python-mpv LGPL-2.1+, Pillow MIT-CMU, CPython PSF-2.0).\n"
        " Full texts: /usr/share/doc/pulsedeck/licenses/\n", encoding="utf-8")


def build_appimage() -> Path:
    appdir = BUILD / "PulseDeck.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(DIST / "PulseDeck", appdir / "usr" / "lib" / "pulsedeck", symlinks=True)
    shutil.copy(LINUX / "AppRun", appdir / "AppRun")
    (appdir / "AppRun").chmod((appdir / "AppRun").stat().st_mode | stat.S_IEXEC)
    shutil.copy(LINUX / "pulsedeck.desktop", appdir / "pulsedeck.desktop")
    shutil.copy(ICONS / "pulsedeck-256.png", appdir / "pulsedeck.png")
    shutil.copy(ICONS / "pulsedeck-256.png", appdir / ".DirIcon")
    meta = appdir / "usr" / "share" / "metainfo"
    meta.mkdir(parents=True)
    shutil.copy(LINUX / "io.github.pulsedeck.PulseDeck.metainfo.xml",
                meta / "io.github.pulsedeck.PulseDeck.appdata.xml")
    tool = os.environ.get("APPIMAGETOOL") or shutil.which("appimagetool")
    if not tool:
        raise SystemExit("appimagetool not found (set APPIMAGETOOL); see docs/BUILDING.md")
    output = DIST / artifact_name("appimage")
    env = dict(os.environ, ARCH="aarch64" if machine() == "arm64" else "x86_64")
    run([tool, "--no-appstream", str(appdir), str(output)], env=env)
    return output


def build_deb() -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "pkg"
        install_tree(root)
        control = root / "DEBIAN"
        control.mkdir()
        size_kb = sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) // 1024
        arch = "arm64" if machine() == "arm64" else "amd64"
        (control / "control").write_text(
            f"Package: pulsedeck\nVersion: {version()}\nSection: sound\nPriority: optional\n"
            f"Architecture: {arch}\nInstalled-Size: {size_kb}\nDepends: {DEB_DEPENDS}\n"
            "Maintainer: Madhu Kumar <madhu.a@hotmail.com>\n"
            "Homepage: https://github.com/aboycan/pulse-deck\n"
            "Description: Classic-style desktop music player with a 10-band equalizer\n"
            " PulseDeck plays local music (MP3, FLAC, AAC, Ogg, Opus, WAV, AIFF, WMA) with\n"
            " gapless playback, a real-time equalizer, playlists and a music library.\n",
            encoding="utf-8")
        for script in ("postinst", "postrm"):
            src = LINUX / "debian" / script
            shutil.copy(src, control / script)
            (control / script).chmod(0o755)
        output = DIST / artifact_name("deb")
        run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(output)])
    return output


def build_rpm() -> Path | None:
    if not shutil.which("rpmbuild"):
        print("rpmbuild not installed; skipping RPM")
        return None
    topdir = BUILD / "rpmbuild"
    shutil.rmtree(topdir, ignore_errors=True)
    for sub in ("BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS", "BUILDROOT"):
        (topdir / sub).mkdir(parents=True)
    staged = topdir / "SOURCES" / "root"
    install_tree(staged)
    spec = (LINUX / "pulsedeck.spec.in").read_text(encoding="utf-8").replace("@VERSION@", version())
    spec_path = topdir / "SPECS" / "pulsedeck.spec"
    spec_path.write_text(spec, encoding="utf-8")
    run(["rpmbuild", "-bb", "--define", f"_topdir {topdir}", "--define", f"_staged {staged}", str(spec_path)])
    built = next((topdir / "RPMS").rglob("*.rpm"))
    output = DIST / artifact_name("rpm")
    shutil.copy(built, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formats", default="appimage,deb,rpm")
    args = parser.parse_args()
    libmpv = require_libmpv(system_libmpv())
    pyinstaller(libmpv)
    smoke_test(DIST / "PulseDeck" / "PulseDeck")
    formats = {f.strip() for f in args.formats.split(",") if f.strip()}
    outputs = []
    if "appimage" in formats:
        outputs.append(build_appimage())
    if "deb" in formats:
        outputs.append(build_deb())
    if "rpm" in formats:
        outputs.append(build_rpm())
    for output in filter(None, outputs):
        print(f"Package: {output}")


if __name__ == "__main__":
    main()
