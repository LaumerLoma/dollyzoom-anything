import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from photo_dolly import runtime


class RuntimeTests(unittest.TestCase):
    def test_home_and_override_are_outside_source(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "DOLLYZOOM_HOME": directory,
                    "DOLLYZOOM_RUNTIME": directory + "/custom",
                },
            ),
        ):
            self.assertEqual(runtime.data_home(), Path(directory).resolve())
            self.assertEqual(runtime.runtime_home(), Path(directory).resolve() / "custom")
            result = runtime.find_runtime()
            self.assertIsNone(result.get("model"))

    def test_viewer_versions_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = {key: "/present" for key in runtime.REQUIRED}
            result["node_modules"] = directory
            for name, version in runtime.VIEWER_PACKAGES.items():
                package = root / name
                package.mkdir(parents=True)
                (package / "package.json").write_text(json.dumps({"version": version}))
            self.assertEqual(runtime.missing_runtime(result), [])
            (root / "three/package.json").write_text('{"version": "0.0.0"}')
            self.assertIn("three@0.180.0 (found 0.0.0)", runtime.missing_runtime(result))

    def test_corrupt_stamp_is_rechecked_and_bad_model_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.pt"
            model.write_bytes(b"valid test checkpoint")
            model.with_suffix(".verified.json").write_text("broken")
            with patch.object(runtime, "MODEL_SHA", hashlib.sha256(model.read_bytes()).hexdigest()):
                runtime.verify_model(model)
                self.assertTrue(json.loads(model.with_suffix(".verified.json").read_text()))
                model.write_bytes(b"corrupt")
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    runtime.verify_model(model)
