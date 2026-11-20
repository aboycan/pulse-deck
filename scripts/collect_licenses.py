# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Gather the full licence texts PulseDeck must ship into ``licenses/``.

Run with the project's virtual environment so the bundled packages are present:

    .venv\\Scripts\\python scripts\\collect_licenses.py      (Windows)
    .venv/bin/python scripts/collect_licenses.py             (macOS / Linux)

INTERNET CONNECTION REQUIRED for the GPL-3.0 and LGPL-3.0 texts.

What it collects (verbatim, never retyped):
  * the licence files shipped inside each bundled Python package
    (Mutagen, Pillow, python-mpv, PySide6-Essentials, shiboken6);
  * CPython's LICENSE.txt from the running interpreter;
  * the GPL-2.0, GPL-3.0, LGPL-2.1 and LGPL-3.0 texts - the licences that cover Qt,
    libmpv/FFmpeg and Mutagen, and the installers as a whole. Verbatim copies shipped
    inside installed packages are used when available; otherwise they are downloaded
    from gnu.org, falling back to the SPDX licence list on GitHub. Each text is checked
    for the right licence heading and version before it is saved.

The release workflow runs this before packaging, and the PyInstaller spec
bundles the ``licenses/`` folder into every installer.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "licenses"

#: Python distributions that end up inside the installers.
BUNDLED_PACKAGES = ("mutagen", "pillow", "python-mpv", "PySide6-Essentials", "shiboken6")

SPDX_TEXT = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/"

#: Licence texts to provide, where to get them (tried in order), and the headings that
#: prove a file is the right licence and version.
GNU_TEXTS = {
    "GPL-2.0.txt": {
        "urls": ["https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt", SPDX_TEXT + "GPL-2.0-only.txt"],
        "local": [("mutagen", "COPYING"), ("python-mpv", "LICENSE.GPL")],
        "must_contain": [b"GNU GENERAL PUBLIC LICENSE", b"Version 2, June 1991"],
    },
    "GPL-3.0.txt": {
        "urls": ["https://www.gnu.org/licenses/gpl-3.0.txt", SPDX_TEXT + "GPL-3.0-only.txt"],
        "local": [],
        "must_contain": [b"GNU GENERAL PUBLIC LICENSE", b"Version 3, 29 June 2007"],
    },
    "LGPL-2.1.txt": {
        "urls": ["https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt", SPDX_TEXT + "LGPL-2.1-only.txt"],
        "local": [("python-mpv", "LICENSE.LGPL")],
        "must_contain": [b"GNU LESSER GENERAL PUBLIC LICENSE", b"Version 2.1, February 1999"],
    },
    "LGPL-3.0.txt": {
        "urls": ["https://www.gnu.org/licenses/lgpl-3.0.txt", SPDX_TEXT + "LGPL-3.0-only.txt"],
        "local": [],
        "must_contain": [b"GNU LESSER GENERAL PUBLIC LICENSE", b"Version 3, 29 June 2007"],
    },
}

LICENSE_HINTS = ("licen", "copying", "notice", "authors")


def is_license_file(relative: str) -> bool:
    name = relative.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return any(hint in name for hint in LICENSE_HINTS) and not name.endswith((".py", ".pyc", ".pyi"))


def package_license_files(package: str) -> list[tuple[str, Path]]:
    """``(file name, absolute path)`` for licence files recorded in a package's metadata."""
    dist = metadata.distribution(package)
    found = []
    for file in dist.files or []:
        if ".dist-info" in str(file) and is_license_file(str(file)):
            path = Path(dist.locate_file(file))
            if path.is_file():
                found.append((Path(str(file)).name, path))
    return found


def collect_packages(out: Path) -> list[str]:
    lines = []
    for package in BUNDLED_PACKAGES:
        try:
            dist = metadata.distribution(package)
        except metadata.PackageNotFoundError:
            print(f"  ! {package} is not installed in this environment - run install.py first")
            lines.append(f"| {package} | (not collected - package not installed) |")
            continue
        target_dir = out / "python-packages" / f"{dist.metadata['Name']}-{dist.version}"
        target_dir.mkdir(parents=True, exist_ok=True)
        files = package_license_files(package)
        for name, path in files:
            shutil.copy2(path, target_dir / name)
        declared = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        declared = declared.splitlines()[0][:80] if declared else "see files"
        listed = ", ".join(sorted(n for n, _ in files)) or "(no licence file shipped)"
        print(f"  {dist.metadata['Name']} {dist.version}: {listed}")
        lines.append(f"| {dist.metadata['Name']} {dist.version} | {declared} | "
                     f"`python-packages/{target_dir.name}/` ({listed}) |")
    return lines


def collect_python(out: Path) -> str:
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
                      Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
                      / "LICENSE.txt"):
        if candidate.is_file():
            shutil.copy2(candidate, out / "Python-PSF-2.0.txt")
            print(f"  CPython licence: {candidate}")
            return "| CPython | PSF-2.0 | `Python-PSF-2.0.txt` |"
    print("  ! CPython LICENSE.txt not found next to the interpreter")
    return "| CPython | PSF-2.0 | https://docs.python.org/3/license.html |"


def valid_text(name: str, data: bytes) -> bool:
    normalized = b" ".join(data.split())   # SPDX copies may wrap lines differently
    return all(b" ".join(marker.split()) in normalized for marker in GNU_TEXTS[name]["must_contain"])


def local_copy(name: str) -> tuple[bytes, str] | None:
    """Verbatim copy shipped inside an installed package (e.g. Mutagen's COPYING is the GPL-2.0)."""
    for package, file_name in GNU_TEXTS[name]["local"]:
        try:
            files = package_license_files(package)
        except metadata.PackageNotFoundError:
            continue
        for found_name, path in files:
            if found_name == file_name:
                data = path.read_bytes()
                if valid_text(name, data):
                    return data, f"copied from the {package} package ({file_name})"
    return None


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PulseDeck licence collector)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def download_gnu(out: Path, offline: bool = False) -> dict[str, str]:
    """Save each licence text; returns ``{file name: where it came from}`` (missing ones omitted)."""
    sources: dict[str, str] = {}
    for name, spec in GNU_TEXTS.items():
        found = local_copy(name)
        errors = []
        if found is None and not offline:
            for url in spec["urls"]:
                try:
                    data = fetch(url)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    errors.append(f"{url.split('/')[2]}: {getattr(exc, 'reason', exc)}")
                    continue
                if valid_text(name, data):
                    found = (data, url)
                    break
                errors.append(f"{url.split('/')[2]}: unexpected content")
        if found is None:
            print(f"  ! Could not get {name}" + (f" ({'; '.join(errors)})" if errors else ""))
            continue
        data, source = found
        (out / name).write_bytes(data)
        sources[name] = source
        print(f"  {name} <- {source}")
    return sources


def write_index(out: Path, package_lines: list[str], python_line: str, sources: dict[str, str]) -> None:
    gnu = "\n".join(f"| `{name}` | {sources.get(name, 'not collected yet - run scripts/collect_licenses.py')} |"
                    for name in GNU_TEXTS)
    (out / "README.md").write_text(f"""# Licence texts

Full texts of the licences that apply to PulseDeck and the components bundled
in its installers. This folder is generated by `scripts/collect_licenses.py`
(files are copied verbatim from each package, or downloaded from gnu.org or
the SPDX licence list).
See `../THIRD_PARTY_LICENSES.md` for which licence covers which component and
`../NOTICE.md` for what this means for redistribution.

## PulseDeck

PulseDeck's own source code: MIT License - see `../LICENSE`.

## GNU licences

| File | Source |
|---|---|
{gnu}

## Runtime and bundled Python packages

| Component | Declared licence | Files |
|---|---|---|
{python_line}
{chr(10).join(package_lines)}

## Native libraries

libmpv and FFmpeg (and the libraries they link) are covered by LGPL-2.1-or-later
or GPL-2.0-or-later depending on how they were built; the release builds use GPL
configurations, so `GPL-2.0.txt` / `GPL-3.0.txt` apply. Qt is used under
LGPL-3.0 (`LGPL-3.0.txt`, which supplements `GPL-3.0.txt`).
""", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect licence texts into licenses/")
    parser.add_argument("--offline", action="store_true", help="skip downloading the GNU texts")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    print(f"Collecting licence texts into {OUT}")
    package_lines = collect_packages(OUT)
    python_line = collect_python(OUT)
    sources = download_gnu(OUT, offline=args.offline)
    write_index(OUT, package_lines, python_line, sources)
    missing_gnu = [n for n in GNU_TEXTS if n not in sources]
    if missing_gnu:
        print(f"\nMissing: {', '.join(missing_gnu)}. Check your internet connection and run this again.")
        print("If gnu.org and GitHub are both blocked on your network, download those files in a browser")
        print(f"from {SPDX_TEXT} (e.g. GPL-3.0-only.txt) and save them in {OUT} as {', '.join(missing_gnu)}.")
        return 1
    print("\nDone. Commit the licenses/ folder together with the code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
