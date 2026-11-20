# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Download or locate libmpv, the audio engine, for running PulseDeck from source.

INTERNET CONNECTION REQUIRED (Windows download, Homebrew / package installs).

What it does per platform:

* Windows  - downloads the latest ``mpv-dev`` build from
             https://github.com/shinchiro/mpv-winbuild-cmake/releases and
             extracts ``libmpv-2.dll`` into ``src/pulsedeck/audio/lib/``.
* macOS    - installs mpv with Homebrew if needed and links
             ``libmpv.2.dylib`` into ``src/pulsedeck/audio/lib/``.
* Linux    - checks for the system libmpv and, if missing, installs it with
             the distribution's package manager (asks before using sudo).

PulseDeck looks in ``src/pulsedeck/audio/lib/`` automatically, so no
environment variables are needed afterwards. Uses only the standard library.

Usage:  python scripts/fetch_libmpv.py [--yes] [--force] [--arch x86_64|aarch64]
"""

from __future__ import annotations

import argparse
import ctypes.util
import json
import os
import platform as py_platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = ROOT / "src" / "pulsedeck" / "audio" / "lib"
RELEASES_API = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
INTERNET_NOTE = "Note: an internet connection is required to download the audio engine (libmpv)."


class FetchError(Exception):
    pass


def say(message: str) -> None:
    print(f"[libmpv] {message}", flush=True)


def ask(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        return False
    return input(f"[libmpv] {question} [Y/n] ").strip().lower() in ("", "y", "yes")


# -- Windows ------------------------------------------------------------------
def windows_arch() -> str:
    machine = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE")
               or py_platform.machine()).lower()
    return "aarch64" if machine in ("arm64", "aarch64") else "x86_64"


def pick_asset(assets: list[dict], arch: str) -> dict:
    """Choose the plain ``mpv-dev-<arch>-<date>-git-<hash>.7z`` asset.

    The ``-v3`` variants need AVX2-capable CPUs, so they are skipped for
    maximum compatibility.
    """
    pattern = re.compile(rf"^mpv-dev-{re.escape(arch)}-\d{{8}}-git-[0-9a-f]+\.7z$")
    matches = [a for a in assets if pattern.match(a.get("name", ""))]
    if not matches:
        names = ", ".join(a.get("name", "?") for a in assets[:10])
        raise FetchError(f"No mpv-dev build for {arch} in the latest release (assets: {names})")
    return sorted(matches, key=lambda a: a["name"])[-1]


def _request(url: str, accept: str = "application/octet-stream") -> urllib.request.Request:
    headers = {"User-Agent": "PulseDeck-setup", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def latest_release() -> dict:
    try:
        with urllib.request.urlopen(_request(RELEASES_API, "application/vnd.github+json"), timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise FetchError("GitHub rate limit reached; try again in an hour or set GITHUB_TOKEN") from exc
        raise FetchError(f"GitHub API error {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Cannot reach GitHub - check your internet connection ({exc.reason})") from exc


def download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(_request(url), timeout=60) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1024 * 256):
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r[libmpv] Downloading… {done * 100 // total:3d}%  ({done // 1048576} MB)",
                          end="", flush=True)
            print()
    except urllib.error.URLError as exc:
        raise FetchError(f"Download failed - check your internet connection ({exc})") from exc


def extract_7z(archive: Path, dest: Path) -> None:
    """Extract with the tar built into Windows 10+, then 7-Zip, then py7zr."""
    dest.mkdir(parents=True, exist_ok=True)
    attempts = []
    tar = shutil.which("tar")
    if tar:
        attempts.append([tar, "-xf", str(archive), "-C", str(dest)])
    for exe in ("7z", "7za", r"C:\Program Files\7-Zip\7z.exe"):
        found = shutil.which(exe) or (exe if os.path.exists(exe) else None)
        if found:
            attempts.append([found, "x", str(archive), f"-o{dest}", "-y"])
            break
    for cmd in attempts:
        if subprocess.run(cmd, capture_output=True).returncode == 0 and any(dest.rglob("libmpv-2.dll")):
            return
    try:
        import py7zr  # noqa: PLC0415
    except ImportError:
        say("Installing the py7zr extractor…")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "py7zr"], check=True)
        import py7zr  # noqa: PLC0415
    with py7zr.SevenZipFile(archive) as z:
        z.extractall(dest)


def fetch_windows(arch: str, force: bool) -> Path:
    target = LIB_DIR / "libmpv-2.dll"
    if target.exists() and not force:
        say(f"Already installed: {target}")
        return target
    say(INTERNET_NOTE)
    release = latest_release()
    asset = pick_asset(release.get("assets", []), arch)
    size_mb = asset.get("size", 0) // 1048576
    say(f"Downloading {asset['name']} ({size_mb} MB) from shinchiro/mpv-winbuild-cmake…")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset["name"]
        download(asset["browser_download_url"], archive)
        extracted = Path(tmp) / "x"
        extract_7z(archive, extracted)
        dll = next(extracted.rglob("libmpv-2.dll"), None)
        if dll is None:
            raise FetchError("libmpv-2.dll was not found in the downloaded archive")
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dll, target)
    (LIB_DIR / "SOURCE.txt").write_text(
        f"libmpv-2.dll from {asset['name']}\n{release.get('html_url', '')}\n"
        "Licensed under GPL-2.0-or-later (see THIRD_PARTY_LICENSES.md).\n", encoding="utf-8")
    say(f"Installed {target}")
    return target


# -- macOS --------------------------------------------------------------------
def fetch_macos(assume_yes: bool, force: bool) -> Path:
    brew = shutil.which("brew") or next((p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
                                         if os.path.exists(p)), None)
    if not brew:
        raise FetchError("Homebrew is required on macOS. Install it from https://brew.sh "
                         "(internet required), then run this setup again.")

    def prefix() -> Path | None:
        result = subprocess.run([brew, "--prefix", "mpv"], capture_output=True, text=True)
        path = Path(result.stdout.strip()) / "lib" / "libmpv.2.dylib"
        return path if result.returncode == 0 and path.exists() else None

    lib = prefix()
    if lib is None or force:
        say(INTERNET_NOTE)
        if not ask("Install mpv with Homebrew now?", assume_yes):
            raise FetchError("libmpv is required. Run: brew install mpv")
        subprocess.run([brew, "install", "mpv"], check=True)
        lib = prefix()
        if lib is None:
            raise FetchError("Homebrew installed mpv but libmpv.2.dylib was not found")
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    link = LIB_DIR / "libmpv.2.dylib"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(lib)
    say(f"Linked {link} -> {lib}")
    return link


# -- Linux --------------------------------------------------------------------
LINUX_PACKAGES = {
    "apt-get": ["libmpv2"],          # Debian 12+/Ubuntu 23.04+; falls back to libmpv1 below
    "dnf": ["mpv-libs"],
    "zypper": ["libmpv2"],
    "pacman": ["mpv"],
}


def find_system_libmpv() -> str | None:
    return ctypes.util.find_library("mpv")


def fetch_linux(assume_yes: bool) -> str:
    found = find_system_libmpv()
    if found:
        say(f"System libmpv found: {found}")
        return found
    manager = next((m for m in LINUX_PACKAGES if shutil.which(m)), None)
    if manager is None:
        raise FetchError("libmpv not found. Install your distribution's libmpv package (often 'libmpv2' or "
                         "'mpv-libs') and run this setup again.")
    packages = LINUX_PACKAGES[manager]
    install = {"apt-get": ["install", "-y"], "dnf": ["install", "-y"], "zypper": ["--non-interactive", "install"],
               "pacman": ["-S", "--needed", "--noconfirm"]}[manager]
    sudo = [] if os.geteuid() == 0 else ["sudo"]
    say(INTERNET_NOTE)
    command = sudo + [manager, *install, *packages]
    if not ask(f"Install libmpv now with: {' '.join(command)} ?", assume_yes):
        raise FetchError(f"libmpv is required. Run: {' '.join(command)}")
    if manager == "apt-get":
        subprocess.run(sudo + ["apt-get", "update"], check=False)
        if subprocess.run(command).returncode != 0:  # older Ubuntu/Debian ship libmpv1
            subprocess.run(sudo + ["apt-get", *install, "libmpv1"], check=True)
    else:
        subprocess.run(command, check=True)
    found = find_system_libmpv()
    if not found:
        raise FetchError("libmpv still not found after installing; please install it manually")
    say(f"System libmpv installed: {found}")
    return found


def ensure_libmpv(assume_yes: bool = False, force: bool = False, arch: str | None = None) -> str:
    if sys.platform.startswith("win"):
        return str(fetch_windows(arch or windows_arch(), force))
    if sys.platform == "darwin":
        return str(fetch_macos(assume_yes, force))
    return fetch_linux(assume_yes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download or locate libmpv for PulseDeck")
    parser.add_argument("--yes", "-y", action="store_true", help="don't ask before installing packages")
    parser.add_argument("--force", action="store_true", help="download again even if already present")
    parser.add_argument("--arch", choices=["x86_64", "aarch64"], help="Windows build architecture")
    args = parser.parse_args()
    try:
        ensure_libmpv(args.yes, args.force, args.arch)
    except (FetchError, subprocess.CalledProcessError) as exc:
        say(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
