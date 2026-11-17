"""Behavioral checks independent of the camera implementation."""

from pathlib import Path
import tempfile
import unittest
import numpy as np
from plyfile import PlyData, PlyElement

from photo_dolly.geometry import Scene
from photo_dolly.pipeline import make_config
from photo_dolly.options import DEFAULTS


class SuitabilityTests(unittest.TestCase):
    def scene(self, kind):
        side = 64
        y, x = np.mgrid[:side, :side]
        u = (x + 0.5) / side
        v = (y + 0.5) / side
        depth = np.full((side, side), 100.0)
        if kind == "flat":
            depth[:] = 5
        else:
            depth[(u > 0.15) & (u < 0.35) & (v > 0.25) & (v < 0.55)] = 5
        z = np.tile(depth.ravel(), 2)
        uu = np.tile(u.ravel(), 2)
        vv = np.tile(v.ravel(), 2)
        names = [
            "x",
            "y",
            "z",
            "f_dc_0",
            "f_dc_1",
            "f_dc_2",
            "opacity",
            "scale_0",
            "scale_1",
            "scale_2",
            "rot_0",
            "rot_1",
            "rot_2",
            "rot_3",
        ]
        data = np.zeros(len(z), dtype=[(name, "f4") for name in names])
        data["x"] = (uu - 0.5) * z
        data["y"] = (vv - 0.5) * z
        data["z"] = z
        data["opacity"] = 6
        data["rot_0"] = 1
        for i in range(3):
            data[f"scale_{i}"] = np.log(0.01)
        handle = tempfile.NamedTemporaryFile(suffix=".ply", delete=False)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(path.unlink)
        PlyData([PlyElement.describe(data, "vertex")], text=False).write(path)
        meta = {
            "image_width": 2000,
            "image_height": 2000,
            "focal_length_px": 2000,
            "vertical_fov_degrees": 53.13,
            "sharpness_laplacian_variance_at_768px": 80,
            "focal_source": "EXIF",
            "image_flags": [],
        }
        return Scene(path, meta)

    def test_flat_photo_is_unsuitable(self):
        self.assertEqual(self.scene("flat").assess([0.5, 0.5])["rating"], "unsuitable")

    def test_close_subject_is_highly_suitable(self):
        result = self.scene("layered").assess([0.25, 0.4])
        self.assertEqual(result["rating"], "highly suitable")
        self.assertGreater(result["predicted_background_growth_factor"], 1.2)

    def test_far_anchor_warns_about_near_foreground(self):
        result = self.scene("layered").assess([0.7, 0.4])
        self.assertEqual(result["rating"], "unsuitable")
        self.assertLess(result["near_foreground_scale_factor"], 0.3)

    def test_coordinates_are_validated(self):
        with self.assertRaises(ValueError):
            self.scene("flat").anchor([1.1, 0.2])

    def test_crop_modes_handle_offcenter_anchor(self):
        scene = self.scene("layered")
        assessment = scene.assess([0.98, 0.5])
        anchor = assessment["anchor"]
        with self.assertRaises(ValueError):
            make_config(scene.meta, DEFAULTS, anchor, "test", assessment, len(scene.vertices))
        config = make_config(
            scene.meta,
            {**DEFAULTS, "crop_mode": "anchor"},
            anchor,
            "test",
            assessment,
            len(scene.vertices),
        )
        self.assertAlmostEqual(config["anchor"]["framed_uv"][0], 0.98)


if __name__ == "__main__":
    unittest.main()
