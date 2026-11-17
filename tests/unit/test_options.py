import unittest
from photo_dolly.options import DEFAULTS, validate_options
from photo_dolly.pipeline import make_config


class SettingsTests(unittest.TestCase):
    def test_numeric_bool_and_nonfinite_values_rejected(self):
        for key, value in [
            ("fps", True),
            ("long_edge", 1080.5),
            ("crop", float("nan")),
            ("strength", float("inf")),
            ("bpm", 0),
            ("beats", None),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_options({**DEFAULTS, key: value})

    def test_bpm_leg_calculated(self):
        result = validate_options({**DEFAULTS, "bpm": 120, "beats": 2})
        self.assertEqual(result["half_seconds"], 1)

    def test_bpm_combination_outside_leg_range_rejected(self):
        with self.assertRaisesRegex(ValueError, "combination"):
            validate_options({**DEFAULTS, "bpm": 400, "beats": 0.25})

    def test_forward_rejects_loop_duration(self):
        with self.assertRaisesRegex(ValueError, "bounce"):
            validate_options({**DEFAULTS, "motion": "forward", "clip_seconds": 10})

    def test_timing_and_even_aspect_dimensions(self):
        meta = {"image_width": 1601, "image_height": 1001}
        anchor = {"uv": [0.5, 0.5]}
        options = validate_options({**DEFAULTS, "bpm": 120, "beats": 2, "clip_seconds": 9})
        config = make_config(meta, options, anchor, "subject", {"depth_far": 100}, 1000)
        self.assertEqual(config["loops"], 5)
        self.assertEqual(config["duration_seconds"], 10)
        self.assertEqual(config["frame_count"], 600)
        self.assertTrue(all(value % 2 == 0 for value in config["video_size"]))
        self.assertLess(abs(config["video_size"][0] / config["video_size"][1] - 1601 / 1001), 0.01)
