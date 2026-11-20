# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec shared by all platforms. Run through scripts/build_*.py,
# which set the environment variables read below.
#
#   PULSEDECK_LIBMPV   path to the libmpv shared library to bundle (required)
#   PULSEDECK_VERSION  version string (defaults to the package version)
#   PULSEDECK_ARCH     target architecture for macOS (x86_64 | arm64)
#
# A one-folder ("onedir") build is used on purpose: it starts faster than a
# one-file build and keeps the LGPL libraries (Qt, libmpv, FFmpeg) as separate,
# replaceable files.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is provided by PyInstaller
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from pulsedeck import __version__  # noqa: E402

VERSION = os.environ.get("PULSEDECK_VERSION", __version__)
LIBMPV = os.environ.get("PULSEDECK_LIBMPV", "")
ICONS = SRC / "pulsedeck" / "assets" / "icons"

if not (ROOT / "licenses" / "GPL-3.0.txt").exists():
    raise SystemExit("licenses/ is incomplete: run scripts/collect_licenses.py before packaging")
if not LIBMPV or not Path(LIBMPV).exists():
    raise SystemExit("PULSEDECK_LIBMPV must point to the libmpv library to bundle")

binaries = [(LIBMPV, ".")]
if sys.platform.startswith("win"):
    # shinchiro's builds ship libmpv-2.dll with everything statically linked;
    # pick up any sibling DLLs in case a different build is used.
    for extra in Path(LIBMPV).parent.glob("*.dll"):
        if extra.name != Path(LIBMPV).name:
            binaries.append((str(extra), "."))

datas = [
    (str(SRC / "pulsedeck" / "assets"), "pulsedeck/assets"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE.md"), "."),
    (str(ROOT / "THIRD_PARTY_LICENSES.md"), "."),
    (str(ROOT / "licenses"), "licenses"),   # full licence texts (scripts/collect_licenses.py)
]

hiddenimports = ["mpv", "PySide6.QtNetwork"] + collect_submodules("mutagen")
if sys.platform.startswith("linux"):
    hiddenimports.append("PySide6.QtDBus")

excludes = [
    "tkinter", "unittest", "pydoc_data", "numpy", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtPdf",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "installers" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe_kwargs = dict(
    name="PulseDeck",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICONS / ("pulsedeck.ico" if sys.platform.startswith("win") else "pulsedeck.icns")),
)
if sys.platform.startswith("win"):
    version_file = ROOT / "build" / "version_info.txt"
    if version_file.exists():
        exe_kwargs["version"] = str(version_file)
if sys.platform == "darwin":
    exe_kwargs["target_arch"] = os.environ.get("PULSEDECK_ARCH") or None
    exe_kwargs["codesign_identity"] = os.environ.get("PULSEDECK_CODESIGN_IDENTITY") or None
    exe_kwargs["entitlements_file"] = str(ROOT / "installers" / "macos" / "entitlements.plist")

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_kwargs)  # noqa: F821
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PulseDeck")  # noqa: F821

if sys.platform == "darwin":
    audio_types = [
        ("MP3 Audio", ["mp3"], "public.mp3"),
        ("FLAC Audio", ["flac"], "org.xiph.flac"),
        ("WAVE Audio", ["wav"], "com.microsoft.waveform-audio"),
        ("AAC Audio", ["aac", "m4a"], "public.mpeg-4-audio"),
        ("Ogg Audio", ["ogg", "oga", "opus"], "org.xiph.ogg-audio"),
        ("AIFF Audio", ["aif", "aiff"], "public.aiff-audio"),
        ("Windows Media Audio", ["wma"], "com.microsoft.windows-media-wma"),
        ("Playlist", ["m3u", "m3u8"], "public.m3u-playlist"),
    ]
    app = BUNDLE(  # noqa: F821
        coll,
        name="PulseDeck.app",
        icon=str(ICONS / "pulsedeck.icns"),
        bundle_identifier="io.github.pulsedeck.PulseDeck",
        version=VERSION,
        info_plist={
            "CFBundleName": "PulseDeck",
            "CFBundleDisplayName": "PulseDeck",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSApplicationCategoryType": "public.app-category.music",
            "LSMinimumSystemVersion": os.environ.get("MACOSX_DEPLOYMENT_TARGET", "11.0"),
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "NSHumanReadableCopyright": "Copyright (c) PulseDeck contributors. MIT License.",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": name,
                    "CFBundleTypeExtensions": exts,
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": [uti],
                }
                for name, exts, uti in audio_types
            ],
        },
    )
