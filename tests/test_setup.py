# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Tests for the first-run setup helpers (no network access needed)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_libmpv  # noqa: E402

ASSETS = [
    {"name": "mpv-x86_64-20261101-git-abc1234.7z"},
    {"name": "mpv-dev-x86_64-v3-20261101-git-abc1234.7z"},
    {"name": "mpv-dev-x86_64-20261101-git-abc1234.7z", "browser_download_url": "https://example/x64.7z"},
    {"name": "mpv-dev-aarch64-20261101-git-abc1234.7z", "browser_download_url": "https://example/arm.7z"},
    {"name": "mpv-dev-i686-20261101-git-abc1234.7z"},
    {"name": "ffmpeg-x86_64-git-abc.7z"},
]


def test_picks_plain_dev_build_not_v3():
    assert fetch_libmpv.pick_asset(ASSETS, "x86_64")["name"] == "mpv-dev-x86_64-20261101-git-abc1234.7z"


def test_picks_arm64_build():
    assert fetch_libmpv.pick_asset(ASSETS, "aarch64")["browser_download_url"] == "https://example/arm.7z"


def test_missing_build_raises_clear_error():
    with pytest.raises(fetch_libmpv.FetchError, match="No mpv-dev build"):
        fetch_libmpv.pick_asset([{"name": "something-else.zip"}], "x86_64")


def test_library_goes_where_the_app_looks():
    from pulsedeck.audio import mpv_backend

    app_dir = Path(mpv_backend.__file__).resolve().parent / "lib"
    assert fetch_libmpv.LIB_DIR.resolve() == app_dir


def test_windows_arch_detection(monkeypatch):
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "ARM64")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    assert fetch_libmpv.windows_arch() == "aarch64"
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    assert fetch_libmpv.windows_arch() == "x86_64"


def test_existing_windows_dll_is_not_downloaded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_libmpv, "LIB_DIR", tmp_path)
    (tmp_path / "libmpv-2.dll").write_bytes(b"MZ")
    monkeypatch.setattr(fetch_libmpv, "latest_release", lambda: pytest.fail("should not hit the network"))
    assert fetch_libmpv.fetch_windows("x86_64", force=False) == tmp_path / "libmpv-2.dll"


def test_launchers_exist_and_mention_internet():
    root = Path(__file__).resolve().parent.parent
    for name in ("install.bat", "install.sh", "run.bat", "run.sh", "install.py", "PulseDeck.pyw", "uninstall.py"):
        assert (root / name).exists(), name
    for name in ("install.bat", "install.sh", "install.py"):
        assert "internet connection is required" in (root / name).read_text(encoding="utf-8").lower()
    assert b"\r\n" in (root / "install.bat").read_bytes()


def test_shortcut_script_targets_the_venv_pythonw():
    import setup_dev

    assert "WScript.Shell" in setup_dev.SHORTCUT_PS and "ConvertFrom-Json" in setup_dev.SHORTCUT_PS
    if not setup_dev.IS_WINDOWS:
        assert setup_dev.create_windows_shortcuts(desktop=False) is False


def test_pyw_launcher_compiles_and_uses_pythonw():
    root = Path(__file__).resolve().parent.parent
    source = (root / "PulseDeck.pyw").read_text(encoding="utf-8")
    compile(source, "PulseDeck.pyw", "exec")
    assert "pythonw.exe" in source and "pulsedeck.main" in source


def test_only_the_slim_qt_package_is_required():
    import tomllib

    root = Path(__file__).resolve().parent.parent
    deps = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    names = [d.split(">")[0].split("<")[0].split("=")[0].strip().lower() for d in deps]
    assert "pyside6-essentials" in names
    assert "pyside6" not in names   # the full package adds ~450 MB of unused Qt add-ons


def test_setup_removes_unused_packages_and_keeps_essentials():
    import setup_dev

    assert "PySide6-WebEngine" in setup_dev.UNUSED_QT_PACKAGES
    assert not any("essentials" in p.lower() for p in setup_dev.UNUSED_QT_PACKAGES)
    runtime = {"pyside6-essentials", "shiboken6", "python-mpv", "mutagen", "pillow"}
    assert not runtime & {p.lower() for p in setup_dev.DEV_PACKAGES + setup_dev.UNUSED_QT_PACKAGES}


def _load_uninstaller():
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("pd_uninstall", root / "uninstall.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uninstall_removes_environment_and_keeps_data_by_default(tmp_path, monkeypatch, isolated_home):
    un = _load_uninstaller()
    monkeypatch.setattr(un, "ROOT", tmp_path)
    monkeypatch.setattr(un, "IS_WINDOWS", False)
    for rel in (".venv/Scripts/python.exe", "src/pulsedeck/audio/lib/libmpv-2.dll", "src/pulsedeck/main.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    isolated_home.mkdir(parents=True)
    (isolated_home / "settings.json").write_text("{}")
    music = tmp_path / "Music" / "song.mp3"
    music.parent.mkdir()
    music.write_bytes(b"audio")
    monkeypatch.setattr(sys, "argv", ["uninstall.py", "--yes"])
    assert un.main() == 0
    assert not (tmp_path / ".venv").exists() and not (tmp_path / "src/pulsedeck/audio/lib").exists()
    assert (tmp_path / "src/pulsedeck/main.py").exists()          # source code stays
    assert (isolated_home / "settings.json").exists()             # data kept unless asked
    assert music.exists()                                          # music never touched


def test_uninstall_can_remove_data(tmp_path, monkeypatch, isolated_home):
    un = _load_uninstaller()
    monkeypatch.setattr(un, "ROOT", tmp_path)
    monkeypatch.setattr(un, "IS_WINDOWS", False)
    isolated_home.mkdir(parents=True)
    (isolated_home / "settings.json").write_text("{}")
    monkeypatch.setattr(sys, "argv", ["uninstall.py", "--yes", "--remove-data"])
    assert un.main() == 0
    assert not isolated_home.exists()


def test_windows_shortcuts_include_uninstall_entry(monkeypatch, tmp_path):
    import setup_dev

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    specs = setup_dev.shortcut_specs(str(tmp_path / "Desktop"))
    names = [Path(s["path"]).name for s in specs]
    assert names.count("PulseDeck.lnk") == 3 and "Uninstall PulseDeck.lnk" in names
    app = next(s for s in specs if s["path"].endswith("PulseDeck.lnk"))
    assert app["target"].endswith("pythonw.exe") and app["args"] == "-m pulsedeck.main"
    uninstall = next(s for s in specs if "Uninstall" in s["path"])
    assert "uninstall.py" in uninstall["args"] and ".venv" not in uninstall["target"]


def test_manifest_check_detects_damaged_files(tmp_path, monkeypatch):
    import hashlib

    import setup_dev

    good = tmp_path / "src" / "pulsedeck" / "__init__.py"
    good.parent.mkdir(parents=True)
    good.write_text('APP_ID = "x"\n')
    other = tmp_path / "README.md"
    other.write_text("readme")
    manifest = tmp_path / "MANIFEST.sha256"
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(tmp_path).as_posix()}" for p in (good, other)]
    manifest.write_text("\n".join(lines + ["0" * 64 + "  missing.py"]))
    monkeypatch.setattr(setup_dev, "ROOT", tmp_path)
    monkeypatch.setattr(setup_dev, "MANIFEST", manifest)
    assert setup_dev.verify_files() == ["missing: missing.py"]
    other.write_text("overwritten by a bad unzip")
    assert "changed: README.md" in setup_dev.verify_files()
