# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""One-step setup for running PulseDeck from source.

INTERNET CONNECTION REQUIRED for the first run (Python packages and libmpv
are downloaded). After setup PulseDeck runs fully offline.

Steps:
  1. Check the Python version (3.11+).
  2. Create a private virtual environment in ``.venv`` (nothing is installed system-wide
     except libmpv on Linux/macOS, which needs the package manager).
  3. Install PulseDeck and its Python dependencies (PySide6, python-mpv, Mutagen, Pillow).
  4. Download / install libmpv (see scripts/fetch_libmpv.py).
  5. Run PulseDeck's self-test and create launchers.

Usage:  python scripts/setup_dev.py [--yes] [--dev] [--run]
Normally started by double-clicking install.py (Windows) or with ./install.sh (macOS/Linux).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
IS_WINDOWS = sys.platform.startswith("win")
MIN_PYTHON = (3, 11)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_libmpv  # noqa: E402


def banner(text: str) -> None:
    print(f"\n=== {text} ===", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def run(cmd: list[str], **kwargs) -> None:  # noqa: ANN003
    print("  >", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


MANIFEST = ROOT / "MANIFEST.sha256"


def verify_files() -> list[str]:
    """Compare files against MANIFEST.sha256 (shipped in release zips) to catch a broken extraction.

    Returns the list of missing or changed files. Without a manifest (e.g. a git
    clone) nothing is checked.
    """
    if not MANIFEST.exists():
        print("  No MANIFEST.sha256 (source checkout) - skipping file check")
        return []
    import hashlib

    problems = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        path = ROOT / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f"changed: {name}")
    if problems:
        print("  WARNING: some files don't match the release:")
        for problem in problems[:20]:
            print(f"    {problem}")
        if len(problems) > 20:
            print(f"    ... and {len(problems) - 20} more")
        print("  If you didn't edit these yourself, extract the zip again into an empty folder")
        print("  (in File Explorer: right-click the zip > Extract All...).")
    else:
        print("  All files match the release")
    return problems


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(
            f"PulseDeck needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; this is {sys.version.split()[0]}.\n"
            "Install a newer Python from https://www.python.org/downloads/ (internet required) and run setup again."
        )
    print(f"  Python {sys.version.split()[0]} OK")


def create_venv() -> None:
    if venv_python().exists():
        print(f"  Reusing {VENV}")
        return
    try:
        venv.EnvBuilder(with_pip=True, upgrade_deps=False).create(VENV)
    except Exception as exc:  # Debian/Ubuntu without pythonX.Y-venv
        hint = ""
        if sys.platform.startswith("linux"):
            v = f"{sys.version_info.major}.{sys.version_info.minor}"
            hint = f"\nOn Debian/Ubuntu run: sudo apt install python{v}-venv"
        raise SystemExit(f"Could not create the virtual environment: {exc}{hint}") from exc


#: Qt add-on packages PulseDeck never uses (web engine, QML, PDF, 3D, charts...). Older setups
#: installed them through the full "PySide6" package; removing them frees about 450 MB.
UNUSED_QT_PACKAGES = ["PySide6", "PySide6-Addons", "PySide6-WebEngine", "PySide6-Pdf"]
#: Test and code-quality tools, only needed for development (about 135 MB).
DEV_PACKAGES = ["pytest", "pytest-qt", "numpy", "ruff", "mypy", "mypy-extensions", "librt", "ast-serialize",
                "pathspec", "pygments", "iniconfig", "pluggy"]


def installed_packages() -> set[str]:
    result = subprocess.run([str(venv_python()), "-m", "pip", "list", "--format=freeze"],
                            capture_output=True, text=True)
    names = set()
    for line in result.stdout.splitlines():
        name = line.split("==")[0].split(" @ ")[0].strip()
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def package_versions() -> dict[str, str]:
    result = subprocess.run([str(venv_python()), "-m", "pip", "list", "--format=freeze"],
                            capture_output=True, text=True)
    versions = {}
    for line in result.stdout.splitlines():
        if "==" in line:
            name, version = line.split("==", 1)
            versions[name.strip().lower().replace("_", "-")] = version.strip()
    return versions


def qt_works() -> bool:
    check = "import PySide6.QtWidgets, PySide6.QtNetwork"
    return subprocess.run([str(venv_python()), "-c", check], capture_output=True).returncode == 0


def repair_qt() -> None:
    """Reinstall PySide6-Essentials, whose files can be shared with (and deleted by) the full PySide6 package."""
    versions = package_versions()
    pins = [f"{name}=={versions[name]}" if name in versions else name
            for name in ("pyside6-essentials", "shiboken6")]
    print("  Restoring Qt files (from pip's cache when available)...")
    run([venv_python(), "-m", "pip", "install", "--force-reinstall", "--no-deps", "-q", *pins])


def remove_unneeded(dev: bool) -> None:
    """Uninstall packages that only take up space, then make sure Qt still loads."""
    present = installed_packages()
    unwanted = UNUSED_QT_PACKAGES + ([] if dev else DEV_PACKAGES)
    to_remove = [name for name in unwanted if name.lower() in present]
    if to_remove:
        print(f"  Removing packages PulseDeck doesn't need: {', '.join(to_remove)}")
        run([venv_python(), "-m", "pip", "uninstall", "-y", "-q", *to_remove])
    if to_remove or not qt_works():
        repair_qt()
    if not qt_works():
        raise subprocess.CalledProcessError(1, "import PySide6.QtWidgets")


def install_packages(dev: bool) -> None:
    py = venv_python()
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-e", f"{ROOT}[dev]" if dev else str(ROOT)])
    if sys.platform == "darwin":
        run([py, "-m", "pip", "install", "pyobjc-framework-MediaPlayer"])  # system-wide media keys
    remove_unneeded(dev)


SHORTCUT_PS = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($item in ($env:PD_SPEC | ConvertFrom-Json)) {
    $dir = Split-Path -Parent $item.path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $link = $shell.CreateShortcut($item.path)
    $link.TargetPath = $item.target
    $link.Arguments = $item.args
    $link.WorkingDirectory = $env:PD_ROOT
    $link.IconLocation = "$($item.icon),0"
    $link.Description = $item.description
    $link.Save()
    Write-Output "  Shortcut: $($item.path)"
}
"""


def base_python() -> str:
    """The Python that created .venv (needed so the uninstaller can delete .venv)."""
    return getattr(sys, "_base_executable", None) or sys.executable


def windows_desktop_dir() -> str:
    try:
        # Honours OneDrive-redirected desktops.
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def shortcut_specs(desktop_dir: str | None) -> list[dict[str, str]]:
    """Start Menu, Desktop and folder shortcuts, plus a Start Menu "Uninstall PulseDeck" entry.

    They point at signed Python executables, which Smart App Control allows
    (it blocks .bat files downloaded from the internet).
    """
    icon = str(ROOT / "src" / "pulsedeck" / "assets" / "icons" / "pulsedeck.ico")
    app = {"target": str(VENV / "Scripts" / "pythonw.exe"), "args": "-m pulsedeck.main", "icon": icon,
           "description": "PulseDeck music player"}
    locations = [ROOT / "PulseDeck.lnk"]
    appdata = os.environ.get("APPDATA", "")
    start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" if appdata else None
    if start_menu:
        locations.append(start_menu / "PulseDeck.lnk")
    if desktop_dir:
        locations.append(Path(desktop_dir) / "PulseDeck.lnk")
    specs = [{**app, "path": str(path)} for path in locations]
    if start_menu:
        specs.append({"path": str(start_menu / "Uninstall PulseDeck.lnk"), "target": base_python(),
                      "args": f'"{ROOT / "uninstall.py"}"', "icon": icon,
                      "description": "Remove PulseDeck's shortcuts and, optionally, its settings"})
    return specs


def create_windows_shortcuts(desktop: bool) -> bool:
    if not IS_WINDOWS:
        return False
    specs = shortcut_specs(windows_desktop_dir() if desktop else None)
    env = dict(os.environ, PD_SPEC=json.dumps(specs), PD_ROOT=str(ROOT))
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", SHORTCUT_PS],
                                env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  Could not create shortcuts: {exc}")
        return False
    print(result.stdout.rstrip())
    if result.returncode != 0:
        print(f"  Could not create shortcuts: {result.stderr.strip()}")
        return False
    return True


def self_test() -> bool:
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", ""))
    result = subprocess.run([str(venv_python()), "-m", "pulsedeck.main", "--self-test"], env=env)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up PulseDeck to run from source")
    parser.add_argument("--yes", "-y", action="store_true", help="answer yes to install prompts")
    parser.add_argument("--dev", action="store_true",
                        help="also install test/developer tools (pytest, NumPy, Ruff, mypy; ~135 MB)")
    parser.add_argument("--run", action="store_true", help="start PulseDeck when setup finishes")
    parser.add_argument("--no-desktop", action="store_true", help="don't put a shortcut on the Desktop (Windows)")
    args = parser.parse_args()

    print("PulseDeck setup")
    print("NOTE: An internet connection is required for this first-time setup.")
    print("      About 150 MB is downloaded (Qt for Python, the libmpv audio engine and other packages);")
    print("      PulseDeck then uses roughly 350 MB of disk space.")

    banner("1/4  Checking Python and the PulseDeck files")
    check_python()
    if verify_files() and not fetch_libmpv.ask("Continue anyway?", args.yes):
        return 1
    banner("2/4  Creating virtual environment (.venv)")
    create_venv()
    banner("3/4  Installing Python packages (internet required)")
    try:
        install_packages(dev=args.dev)
    except subprocess.CalledProcessError:
        print("\nPackage installation failed. Check your internet connection (and any proxy settings), "
              "then run setup again. If it keeps failing, run uninstall.py, choose to remove the .venv "
              "folder, and set up again.")
        return 1
    banner("4/4  Installing the audio engine, libmpv (internet required)")
    try:
        fetch_libmpv.ensure_libmpv(assume_yes=args.yes)
    except (fetch_libmpv.FetchError, subprocess.CalledProcessError) as exc:
        print(f"\nCould not set up libmpv: {exc}")
        print("PulseDeck will still open, but playback stays disabled until libmpv is installed.")
        print("Fix the problem above and run setup again (it only redoes what is missing).")
        return 1

    banner("Checking the installation")
    ok = self_test()
    if IS_WINDOWS:
        banner("Creating PulseDeck shortcuts")
        create_windows_shortcuts(desktop=not args.no_desktop)
    launcher = ("the PulseDeck shortcut (Start Menu / Desktop) or PulseDeck.pyw in this folder" if IS_WINDOWS
                else "./run.sh")
    if ok:
        print(f"\nSetup complete. Start PulseDeck with: {launcher}")
    else:
        print("\nSetup finished but the self-test reported a problem (see messages above). "
              f"You can still try {launcher}; the log is under Help > Open Log Folder.")
    if args.run and ok:
        launch = [str(VENV / "Scripts" / "pythonw.exe")] if IS_WINDOWS else [str(venv_python())]
        subprocess.Popen([*launch, "-m", "pulsedeck.main"], cwd=ROOT)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
