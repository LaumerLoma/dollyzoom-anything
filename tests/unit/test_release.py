"""Prevent private working assets from entering the explicit source release."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("build_release", ROOT / "scripts/build_release.py")
release = importlib.util.module_from_spec(loader)
loader.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_bundle_is_reproducible_and_contains_only_public_source(self):
        with tempfile.TemporaryDirectory() as directory:
            first = release.build(Path(directory) / "first.zip")
            second = release.build(Path(directory) / "second.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                for name in names:
                    self.assertFalse(
                        set(Path(name).parts)
                        & {
                            "gaussian_splat",
                            "runs",
                            "outputs",
                            "cache",
                            "runtime",
                            "demo",
                            "to-do",
                            "__pycache__",
                            "node_modules",
                            "skill",
                        },
                        name,
                    )
                    self.assertNotIn(
                        Path(name).suffix.lower(),
                        {
                            ".jpg",
                            ".png",
                            ".mp4",
                            ".gif",
                            ".pt",
                            ".ply",
                            ".blend",
                        },
                        name,
                    )
                self.assertIn("dollyzoom/pyproject.toml", names)
                self.assertIn("dollyzoom/docs/AGENTS.md", names)
                self.assertIn("dollyzoom/photo_dolly/assets/render.mjs", names)
                self.assertTrue(archive.getinfo("dollyzoom/dollyzoom").external_attr >> 16 & 0o111)
