# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Static checks on packaging files, plus the frozen-bundle check when one exists.

The real installers are built and smoke-tested by the release workflow on each
platform (``--self-test`` on the bundle, and an install/launch/remove cycle for
the .deb). These tests keep the packaging files consistent between releases.
"""

from __future__ import annotations

import configparser
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_common  # noqa: E402
from pulsedeck import __version__  # noqa: E402


def test_versions_are_consistent():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__
    assert build_common.version() == __version__
    metainfo = ET.parse(ROOT / "installers/linux/io.github.pulsedeck.PulseDeck.metainfo.xml")
    assert metainfo.getroot().find("releases/release").get("version") == __version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog


@pytest.mark.parametrize(("target", "arch", "expected"), [
    ("windows", "x86_64", "PulseDeck-Setup-x64.exe"),
    ("windows", "arm64", "PulseDeck-Setup-ARM64.exe"),
    ("macos", "x86_64", "PulseDeck-macOS-Intel.dmg"),
    ("macos", "arm64", "PulseDeck-macOS-AppleSilicon.dmg"),
    ("appimage", "x86_64", "PulseDeck-x86_64.AppImage"),
])
def test_artifact_names_match_release_requirements(target, arch, expected):
    assert build_common.artifact_name(target, arch) == expected


def test_deb_and_rpm_names():
    assert build_common.artifact_name("deb", "x86_64") == f"pulsedeck_{__version__}_amd64.deb"
    assert build_common.artifact_name("rpm", "arm64") == f"pulsedeck-{__version__}-1.aarch64.rpm"


def test_required_repository_files_exist():
    for name in ("LICENSE", "NOTICE.md", "THIRD_PARTY_LICENSES.md", "README.md", "CONTRIBUTING.md", "CHANGELOG.md",
                 ".gitignore", "pyproject.toml", ".github/workflows/ci.yml", ".github/workflows/release.yml",
                 "installers/pulsedeck.spec", "installers/windows/pulsedeck.iss", "installers/linux/AppRun",
                 "installers/linux/pulsedeck.desktop", "installers/macos/entitlements.plist",
                 "scripts/build_windows.py", "scripts/build_macos.py", "scripts/build_linux.py"):
        assert (ROOT / name).exists(), name
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_icons_exist_for_every_platform():
    icons = ROOT / "src/pulsedeck/assets/icons"
    for name in ("pulsedeck.ico", "pulsedeck.icns", "pulsedeck.svg", "pulsedeck-256.png", "pulsedeck-16.png"):
        assert (icons / name).stat().st_size > 0


def test_desktop_entry_is_valid():
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str  # keep key case
    parser.read(ROOT / "installers/linux/pulsedeck.desktop", encoding="utf-8")
    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application" and entry["Exec"].startswith("pulsedeck")
    assert entry["Icon"] == "pulsedeck"
    assert "audio/flac" in entry["MimeType"] and "audio/mpeg" in entry["MimeType"]
    assert entry["MimeType"].endswith(";") and entry["Categories"].endswith(";")


def test_inno_setup_script_requirements():
    iss = (ROOT / "installers/windows/pulsedeck.iss").read_text(encoding="utf-8")
    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}", iss, re.M)            # stable id for upgrades
    assert "MinVersion=10.0" in iss                                         # Windows 10+
    assert "desktopicon" in iss and "{group}" in iss                        # shortcuts
    assert "OpenWithProgids" in iss                                         # file associations
    assert "CurUninstallStepChanged" in iss and "MB_DEFBUTTON2" in iss      # user data kept by default


def test_no_winamp_assets_or_branding_in_the_app():
    """PulseDeck's own files must not use Winamp names or assets.

    Only the files that state PulseDeck's independence may mention it. Generated
    files (pip's egg-info copy of the README) and downloaded third-party binaries
    such as libmpv are not PulseDeck's files and are skipped.
    """
    pattern = re.compile(r"winamp|nullsoft|\.wsz\b", re.IGNORECASE)
    allowed = {"NOTICE.md", "README.md", "CONTRIBUTING.md", "test_installer.py", "feature_request.yml",
               "pulsedeck.iss", "INSTALLER_LICENSE.txt"}
    skip_dirs = {".git", "build", "dist", "__pycache__", ".venv", ".pytest_cache", ".ruff_cache", "licenses"}
    third_party = ROOT / "src" / "pulsedeck" / "audio" / "lib"   # downloaded libmpv
    binary = {".png", ".ico", ".icns", ".sqlite3", ".dll", ".so", ".dylib", ".exe", ".pyd", ".7z", ".zip", ".lnk"}
    offenders = []
    for path in ROOT.rglob("*"):
        if (not path.is_file() or any(p in skip_dirs or p.endswith(".egg-info") for p in path.parts)
                or third_party in path.parents):
            continue
        if path.name in allowed or path.suffix.lower() in binary:
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
        except OSError:
            continue
    assert offenders == []


def test_spec_bundles_assets_and_licenses():
    spec = (ROOT / "installers/pulsedeck.spec").read_text(encoding="utf-8")
    for needle in ("pulsedeck/assets", "THIRD_PARTY_LICENSES.md", "NOTICE.md", "PULSEDECK_LIBMPV",
                   "CFBundleDocumentTypes", "collect_submodules(\"mutagen\")"):
        assert needle in spec


def test_frozen_bundle_self_test_if_built():
    candidates = [ROOT / "dist/PulseDeck/PulseDeck", ROOT / "dist/PulseDeck/PulseDeck.exe",
                  ROOT / "dist/PulseDeck.app/Contents/MacOS/PulseDeck"]
    exe = next((c for c in candidates if c.exists()), None)
    if exe is None:
        pytest.skip("No frozen build in dist/ (run scripts/build_<platform>.py first)")
    result = subprocess.run([str(exe), "--self-test"], capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_license_and_copyright_are_correct():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "Copyright (c) 2026 Madhu Kumar and PulseDeck contributors" in license_text
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert pyproject["license"] == "MIT"
    assert pyproject["authors"][0]["name"] == "Madhu Kumar"
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    for needle in ("free of charge", "GPL-3.0-or-later", "Trademarks", "MIT"):
        assert needle in notice


def test_every_source_file_has_an_spdx_header():
    files = [*ROOT.glob("src/**/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py"),
             *ROOT.glob("installers/*.py"), ROOT / "install.py", ROOT / "uninstall.py", ROOT / "PulseDeck.pyw"]
    missing = [str(f.relative_to(ROOT)) for f in files
               if not any("SPDX-License-Identifier: MIT" in line
                          for line in f.read_text(encoding="utf-8").splitlines()[:3])]
    assert missing == []


def test_every_bundled_runtime_dependency_is_documented():
    third_party = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    for dep in deps:
        name = re.split(r"[<>=!~ ;\[]", dep, maxsplit=1)[0]
        assert name.lower() in third_party.lower(), f"{name} missing from THIRD_PARTY_LICENSES.md"
    for licence in ("GPL-3.0.txt", "LGPL-3.0.txt", "GPL-2.0.txt", "LGPL-2.1.txt"):
        assert licence in third_party


def test_repository_links_point_to_the_real_repo():
    for name in ("README.md", "pyproject.toml", "NOTICE.md", "installers/windows/pulsedeck.iss"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "github.com/aboycan/pulse-deck" in text and "pulse-deck/pulse-deck" not in text, name


def test_collect_licenses_copies_package_texts(tmp_path, monkeypatch):
    import collect_licenses

    site = tmp_path / "site"
    dist = site / "fakepkg-1.2.dist-info"
    (dist / "licenses").mkdir(parents=True)
    (dist / "licenses" / "COPYING").write_text("GNU GENERAL PUBLIC LICENSE")
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: fakepkg\nVersion: 1.2\nLicense-Expression: GPL-2.0-or-later\n")
    (dist / "RECORD").write_text("fakepkg-1.2.dist-info/METADATA,,\nfakepkg-1.2.dist-info/licenses/COPYING,,\n"
                                 "fakepkg-1.2.dist-info/RECORD,,\nfakepkg/__init__.py,,\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setattr(collect_licenses, "BUNDLED_PACKAGES", ("fakepkg",))
    out = tmp_path / "licenses"
    lines = collect_licenses.collect_packages(out)
    assert (out / "python-packages" / "fakepkg-1.2" / "COPYING").read_text() == "GNU GENERAL PUBLIC LICENSE"
    assert "GPL-2.0-or-later" in lines[0]
    assert collect_licenses.is_license_file("x.dist-info/licenses/LICENSE.txt")
    assert not collect_licenses.is_license_file("pkg/license_check.py")


GPL2 = b"GNU GENERAL PUBLIC LICENSE\n  Version 2, June 1991\n terms..."
GPL3 = b"GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n terms..."
LGPL3_SPDX = b"GNU LESSER GENERAL PUBLIC LICENSE\n\nVersion 3,\n29 June 2007\n terms..."


def test_licence_texts_fall_back_to_spdx_and_check_versions(tmp_path, monkeypatch):
    import urllib.error

    import collect_licenses as cl

    def fake_fetch(url):
        if "gnu.org" in url:
            raise urllib.error.URLError("connection reset")   # what happened on the user's network
        if url.endswith("GPL-3.0-only.txt") and "LGPL" not in url:
            return GPL3
        if url.endswith("LGPL-3.0-only.txt"):
            return LGPL3_SPDX                                  # different line wrapping still validates
        if url.endswith("GPL-2.0-only.txt") and "LGPL" not in url:
            return GPL3                                        # wrong version must be rejected
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(cl, "fetch", fake_fetch)
    monkeypatch.setattr(cl, "local_copy", lambda name: (GPL2, "copied from the mutagen package (COPYING)")
                        if name == "GPL-2.0.txt" else None)
    sources = cl.download_gnu(tmp_path)
    assert sources["GPL-2.0.txt"].startswith("copied from the mutagen package")
    assert sources["GPL-3.0.txt"].startswith("https://raw.githubusercontent.com/spdx/")
    assert sources["LGPL-3.0.txt"].endswith("LGPL-3.0-only.txt")
    assert "LGPL-2.1.txt" not in sources                       # no source available -> reported missing
    assert (tmp_path / "GPL-3.0.txt").read_bytes() == GPL3
    assert not cl.valid_text("GPL-2.0.txt", GPL3)
