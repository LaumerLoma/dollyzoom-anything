"""Exercise the external CLI contract without a model or browser."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from photo_dolly import cli


class CliTests(unittest.TestCase):
    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_schema_runs_without_scientific_imports(self):
        process = subprocess.run(
            [sys.executable, "-S", "-m", "photo_dolly", "schema"],
            capture_output=True,
            text=True,
            check=True,
        )
        reply = json.loads(process.stdout)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["schema_version"], 1)
        self.assertEqual(reply["result"]["defaults"]["strength"], 1.25)

    def test_doctor_missing_returns_diagnostics(self):
        with patch("photo_dolly.runtime.find_runtime", return_value={}):
            code, reply, _ = self.invoke("doctor", "--json")
        self.assertEqual(code, 1)
        self.assertFalse(reply["ok"])
        self.assertIn("model", reply["result"]["missing"])

    def test_parse_error_is_one_json_object(self):
        code, reply, err = self.invoke("--json", "run", "photo.jpg", "--anchor", "nan,0.5")
        self.assertEqual(code, 2)
        self.assertEqual(reply["error"]["type"], "UsageError")
        self.assertNotIn("Traceback", err)

    def test_missing_file_is_actionable(self):
        code, reply, _ = self.invoke("inspect", "/does-not-exist/image.jpg", "--json")
        self.assertEqual(code, 2)
        self.assertIn("Photo does not exist", reply["error"]["message"])

    def test_json_never_waits_for_a_picker(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as photo:
            with patch.object(cli, "image_runtime") as load:
                code, reply, _ = self.invoke(photo.name, "--json")
        self.assertEqual(code, 2)
        self.assertIn("requires --anchor", reply["error"]["message"])
        load.assert_not_called()

    def test_nonempty_output_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "photo.jpg"
            photo.write_bytes(b"not loaded")
            with patch.object(cli, "image_runtime") as load:
                code, reply, _ = self.invoke(
                    "run", str(photo), "--anchor", ".5,.5", "--output", str(root), "--json"
                )
            self.assertEqual(photo.read_bytes(), b"not loaded")
        self.assertEqual(code, 2)
        self.assertIn("never overwritten", reply["error"]["message"])
        load.assert_not_called()

    def test_nan_settings_rejected_before_runtime(self):
        with tempfile.NamedTemporaryFile() as photo:
            with patch.object(cli, "image_runtime") as load:
                code, reply, _ = self.invoke(
                    "run", photo.name, "--anchor", ".5,.5", "--strength", "nan", "--json"
                )
        self.assertEqual(code, 2)
        self.assertIn("finite", reply["error"]["message"])
        load.assert_not_called()

    def test_json_view_fails_without_hanging(self):
        code, reply, _ = self.invoke("view", ".", "--json")
        self.assertEqual(code, 2)
        self.assertIn("long-running", reply["error"]["message"])

    def test_logs_go_to_stderr(self):
        def fake_execute(args, argv):
            print("progress")
            return {"answer": 42}, 0

        with patch.object(cli, "execute", side_effect=fake_execute):
            code, reply, err = self.invoke("doctor", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(reply["result"]["answer"], 42)
        self.assertEqual(err, "progress\n")

    def test_preset_then_shortcut_then_explicit_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            preset = Path(directory) / "preset.json"
            preset.write_text('{"half_seconds": 4, "crop": 1.1, "easing": "smooth"}')
            args = cli.build_parser().parse_args(
                ["run", "photo.jpg", "--preset", str(preset), "--tiktok", "--half-seconds", "1.5"]
            )
            result = cli.render_options(args)
        self.assertEqual(result["half_seconds"], 1.5)
        self.assertEqual(result["crop"], 1.1)
        self.assertEqual(result["easing"], "bouncy")

    def test_bad_preset_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            preset = Path(directory) / "preset.json"
            preset.write_text('{"unknown": 2}')
            args = cli.build_parser().parse_args(["run", "photo.jpg", "--preset", str(preset)])
            with self.assertRaisesRegex(ValueError, "Unknown preset"):
                cli.render_options(args)
