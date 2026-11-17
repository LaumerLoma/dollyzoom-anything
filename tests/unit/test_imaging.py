"""Verify source preservation, orientation, calibration and metadata removal."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from photo_dolly.imaging import prepare_image


class ImagingTests(unittest.TestCase):
    def test_oriented_clean_preview_keeps_original_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.jpg"
            exif = Image.Exif()
            exif[274] = 6
            exif[315] = "Private Author"
            exif[270] = "Private description"
            Image.new("RGB", (128, 96), "red").save(source, exif=exif)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            result = prepare_image(source, root / "clean", focal_mm=40)
            self.assertEqual((result["image_width"], result["image_height"]), (96, 128))
            self.assertEqual(result["focal_mm_35mm_equivalent"], 40)
            self.assertEqual(result["focal_source"], "override")
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            for filename in ("input.png", "preview.jpg"):
                with Image.open(root / "clean" / filename) as image:
                    self.assertFalse(image.getexif())
                    self.assertFalse(set(image.info) & {"author", "comment", "software", "xmp"})

    def test_small_input_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "tiny.png"
            Image.new("RGB", (63, 100)).save(photo)
            with self.assertRaisesRegex(ValueError, "too small"):
                prepare_image(photo, root / "out")
