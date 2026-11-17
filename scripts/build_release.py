#!/usr/bin/env python3
"""Build a small source ZIP from an explicit allowlist; never include local media."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MODULES = (
    "__init__",
    "__main__",
    "cli",
    "options",
    "runtime",
    "pipeline",
    "imaging",
    "inference",
    "geometry",
    "server",
)
TOP_LEVEL = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "MANIFEST.in",
    ".gitignore",
    ".gitattributes",
    "dollyzoom",
    "photo-dolly",
)


def source_files(root=ROOT):
    paths = [root / name for name in TOP_LEVEL]
    paths += [root / f"photo_dolly/{name}.py" for name in SOURCE_MODULES]
    paths += [
        root / "photo_dolly" / name
        for name in (
            "requirements.lock.txt",
            "viewer-package.json",
            "viewer-package-lock.json",
        )
    ]
    paths += [root / "scripts/build_release.py"]
    for folder, patterns in {
        "docs": ("*.md",),
        "tests/unit": ("*.py",),
        "photo_dolly/assets": ("*.js", "*.mjs", "*.html"),
        "photo_dolly/examples": ("*.json",),
        ".github": ("*.yml", "*.yaml", "*.md"),
    }.items():
        for pattern in patterns:
            paths.extend((root / folder).rglob(pattern))
    return sorted(set(paths))


def build(output):
    files = source_files()
    manifest = {
        "tool": "dollyzoom",
        "files": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
    }
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            name = "dollyzoom/" + path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            executable = path.name in ("dollyzoom", "photo-dolly")
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("dollyzoom/SOURCE_MANIFEST.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, json.dumps(manifest, indent=2) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/dollyzoom-source.zip")
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()
