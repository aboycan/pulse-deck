# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Build the Windows installer: PyInstaller bundle + Inno Setup.

Usage (on Windows, from the repository root):
    python scripts/build_windows.py [--arch x64|arm64] [--skip-installer]

Needs: Python 3.11+, the build extras (pip install -e .[build]), Inno Setup 6
(iscc.exe on PATH or in its default folder), and an internet connection the
first time: libmpv-2.dll is downloaded automatically by scripts/fetch_libmpv.py
(or set PULSEDECK_LIBMPV to use your own copy).
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import fetch_libmpv
from build_common import BUILD, DIST, ROOT, artifact_name, pyinstaller, require_libmpv, run, smoke_test, version


def write_version_info() -> None:
    parts = [int(p) if p.isdigit() else 0 for p in version().split(".")[:3]] + [0]
    while len(parts) < 4:
        parts.insert(-1, 0)
    tup = tuple(parts[:4])
    BUILD.mkdir(exist_ok=True)
    (BUILD / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'PulseDeck contributors'),
      StringStruct('FileDescription', 'PulseDeck music player'),
      StringStruct('FileVersion', '{version()}'),
      StringStruct('InternalName', 'PulseDeck'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'PulseDeck.exe'),
      StringStruct('ProductName', 'PulseDeck'),
      StringStruct('ProductVersion', '{version()}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


def find_iscc() -> str:
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        candidate = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if candidate.exists():
            return str(candidate)
    raise SystemExit("Inno Setup 6 (ISCC.exe) not found; install it from https://jrsoftware.org/isinfo.php")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=["x64", "arm64"], default="x64")
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("PULSEDECK_LIBMPV") and not (fetch_libmpv.LIB_DIR / "libmpv-2.dll").exists():
        # Internet required: downloads the latest libmpv build automatically.
        fetch_libmpv.fetch_windows("aarch64" if args.arch == "arm64" else "x86_64", force=False)
    libmpv = require_libmpv([fetch_libmpv.LIB_DIR / "libmpv-2.dll", BUILD / "libmpv" / "libmpv-2.dll"])
    write_version_info()
    pyinstaller(libmpv)
    smoke_test(DIST / "PulseDeck" / "PulseDeck.exe")
    if args.skip_installer:
        return
    arch = "arm64" if args.arch == "arm64" else "x86_64"
    output = artifact_name("windows", arch)
    run([find_iscc(), f"/DAppVersion={version()}", f"/DArch={args.arch}", f"/DSourceDir={DIST / 'PulseDeck'}",
         f"/DOutputDir={DIST}", f"/DOutputBaseName={Path(output).stem}",
         str(ROOT / "installers" / "windows" / "pulsedeck.iss")])
    print(f"Installer: {DIST / output}")


if __name__ == "__main__":
    main()
