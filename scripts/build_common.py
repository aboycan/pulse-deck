# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Helpers shared by the platform build scripts."""

from __future__ import annotations

import os
import platform as py_platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "installers" / "pulsedeck.spec"


def version() -> str:
    text = (ROOT / "src" / "pulsedeck" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("Cannot find __version__")
    return os.environ.get("PULSEDECK_VERSION", match.group(1))


def machine() -> str:
    arch = os.environ.get("PULSEDECK_ARCH") or py_platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(arch, arch)


def artifact_name(target: str, arch: str | None = None) -> str:
    """File names required by the release checklist."""
    arch = arch or machine()
    v = version()
    names = {
        "windows": f"PulseDeck-Setup-{'ARM64' if arch == 'arm64' else 'x64'}.exe",
        "macos": f"PulseDeck-macOS-{'AppleSilicon' if arch == 'arm64' else 'Intel'}.dmg",
        "appimage": f"PulseDeck-{'aarch64' if arch == 'arm64' else 'x86_64'}.AppImage",
        "deb": f"pulsedeck_{v}_{'arm64' if arch == 'arm64' else 'amd64'}.deb",
        "rpm": f"pulsedeck-{v}-1.{'aarch64' if arch == 'arm64' else 'x86_64'}.rpm",
    }
    return names[target]


def run(cmd: list[str], **kwargs) -> None:  # noqa: ANN003
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def require_libmpv(candidates: list[Path]) -> Path:
    env = os.environ.get("PULSEDECK_LIBMPV")
    if env:
        path = Path(env)
        if not path.exists():
            raise SystemExit(f"PULSEDECK_LIBMPV does not exist: {path}")
        return path
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "libmpv was not found. Install it (see docs/BUILDING.md) or set PULSEDECK_LIBMPV to the library path."
    )


def collect_licenses() -> None:
    """Refresh licenses/ with the texts of exactly the packages being bundled (internet required)."""
    run([sys.executable, str(ROOT / "scripts" / "collect_licenses.py")])


def pyinstaller(libmpv: Path, extra_env: dict[str, str] | None = None) -> Path:
    collect_licenses()
    env = dict(os.environ)
    env["PULSEDECK_LIBMPV"] = str(libmpv)
    env["PULSEDECK_VERSION"] = version()
    env.update(extra_env or {})
    shutil.rmtree(DIST / "PulseDeck", ignore_errors=True)
    shutil.rmtree(DIST / "PulseDeck.app", ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(BUILD / "pyinstaller"), str(SPEC)], env=env)
    return DIST


def smoke_test(executable: Path) -> None:
    """Run the frozen app's --self-test to prove Qt, libmpv and friends load."""
    if not executable.exists():
        raise SystemExit(f"Build output missing: {executable}")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([str(executable), "--self-test"], env=env, capture_output=True, text=True, timeout=60)
    print(result.stdout, result.stderr)
    if result.returncode != 0:
        raise SystemExit(f"Smoke test failed with exit code {result.returncode}")
