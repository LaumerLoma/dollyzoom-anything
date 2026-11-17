#!/usr/bin/env python3
"""Repeatable, local single-photo dolly zooms."""

from pathlib import Path
import argparse
import json
import sys
import contextlib
import hashlib
import importlib.util
import math
import subprocess

from . import __version__
from .options import DEFAULTS, TIKTOK, LIMITS, CHOICES, validate_options


def anchor_value(value):
    try:
        values = [float(x.strip()) for x in value.split(",")]
        if len(values) != 2 or not all(0 <= x <= 1 for x in values):
            raise ValueError
        return values
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Use X,Y in [0,1], from the oriented photo’s top-left, for example 0.23,0.254."
        )


def bool_value(value):
    value = str(value).strip().lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    raise argparse.ArgumentTypeError("Use true or false.")


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def build_parser():
    parser = Parser(
        prog="dollyzoom",
        description="Dollyzoom anything. Turn a single photo into an anchored dolly zoom.",
    )
    parser.add_argument("--version", action="version", version=f"dollyzoom {__version__}")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write one JSON result to stdout; progress goes to stderr.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "assess"):
        p = sub.add_parser(
            command,
            help="Assess and render a photo."
            if command == "run"
            else "Assess without rendering a video.",
        )
        p.add_argument("photo", type=Path)
        p.add_argument(
            "--anchor",
            type=anchor_value,
            help="Normalized X,Y. Omit to click a point in the local picker.",
        )
        p.add_argument(
            "--anchor-label",
            default="Selected point",
            help="Human-readable name such as Swiss cross or left eye.",
        )
        p.add_argument(
            "--output", type=Path, help="Empty output folder. Existing files are never overwritten."
        )
        p.add_argument(
            "--preset", type=Path, help="JSON render options; CLI flags override the preset."
        )
        p.add_argument(
            "--strength", type=float, help="Lens multiplier; 1.25 means a 25%% increase."
        )
        p.add_argument("--crop", type=float, help="Static framing multiplier, normally 1.0–1.2.")
        p.add_argument(
            "--crop-mode",
            choices=["center", "anchor"],
            help="Center the crop or keep the selected point at its original location.",
        )
        p.add_argument(
            "--half-seconds", type=float, help="Seconds for each leg of the move (default 2)."
        )
        p.add_argument("--fps", type=int, help="Output frame rate (default 60).")
        p.add_argument(
            "--long-edge",
            type=int,
            help="Output long edge in pixels; aspect ratio is preserved (default 1080).",
        )
        p.add_argument(
            "--supersample", type=float, help="Render scale before downsampling (default 1.5)."
        )
        p.add_argument(
            "--polish",
            choices=["off", "conservative", "auto", "fill"],
            help="auto fills only a small isolated foreground against smooth surroundings.",
        )
        p.add_argument(
            "--motion",
            choices=["bounce", "forward"],
            help="Loop out-and-back, or export a single forward move.",
        )
        p.add_argument(
            "--easing",
            choices=["smooth", "bouncy"],
            help="Camera speed curve: smooth (default) or bouncy snap with a settle.",
        )
        p.add_argument(
            "--bpm",
            type=float,
            help="Song tempo; each leg of the move lasts --beats beats (overrides --half-seconds).",
        )
        p.add_argument(
            "--beats",
            type=float,
            help="Beats per leg with --bpm (default 1; use 2 for half-time on fast songs).",
        )
        p.add_argument(
            "--clip-seconds",
            type=float,
            help="Minimum clip length, rounded up to whole loops (default: one loop, or 8 s with --bpm).",
        )
        p.add_argument(
            "--tiktok",
            nargs="?",
            const=True,
            default=False,
            type=bool_value,
            help="--tiktok or --tiktok=true: double speed (1 s each way) with bouncy easing. Explicit flags still override.",
        )
        p.add_argument(
            "--focal-mm",
            type=float,
            help="Override 35 mm equivalent focal length; EXIF is used otherwise.",
        )
        p.add_argument(
            "--no-open",
            action="store_true",
            help="Print the picker URL rather than opening a browser.",
        )
        p.add_argument(
            "--save-frames",
            action="store_true",
            help="Keep temporary PNG frames for further inspection.",
        )
        p.add_argument("--reuse-scene", type=Path, help=argparse.SUPPRESS)
        p.add_argument("--picker-timeout", type=int, default=3600, help=argparse.SUPPRESS)
    sub.add_parser("setup", help="Install or reuse the local model and dependencies.")
    sub.add_parser("doctor", help="Report the available runtime.")
    sub.add_parser("schema", help="Describe the CLI contract for agents as JSON.")
    p = sub.add_parser(
        "inspect", help="Save an oriented preview and image preflight without loading the model."
    )
    p.add_argument("photo", type=Path)
    p.add_argument("--focal-mm", type=float)
    p = sub.add_parser("view", help="Serve an existing run in the local interactive viewer.")
    p.add_argument("folder", type=Path)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-open", action="store_true")
    for child in sub.choices.values():
        child.add_argument(
            "--json",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Write one JSON result to stdout.",
        )
    return parser


def contract():
    return {
        "schema_version": 1,
        "tool": "dollyzoom",
        "version": __version__,
        "commands": ["run", "assess", "inspect", "doctor", "setup", "schema", "view"],
        "defaults": DEFAULTS,
        "limits": LIMITS,
        "choices": CHOICES,
        "anchor": {"format": "X,Y", "range": [0, 1], "origin": "oriented image top-left"},
        "json": {
            "success": {"schema_version": 1, "ok": True, "command": "COMMAND", "result": {}},
            "failure": {
                "schema_version": 1,
                "ok": False,
                "command": "COMMAND",
                "error": {"type": "ERROR_TYPE", "message": "MESSAGE"},
            },
            "progress": "stderr",
            "noninteractive": "Supply --anchor for run/assess; view is interactive.",
        },
        "exit_codes": {
            "0": "success",
            "1": "doctor found missing runtime",
            "2": "invalid input or execution failure",
            "130": "interrupted",
        },
    }


def focal_value(value):
    if value is not None and not math.isfinite(value):
        raise ValueError("--focal-mm must be finite.")
    if value is not None and not 5 <= value <= 500:
        raise ValueError("--focal-mm must be a 35 mm equivalent between 5 and 500.")


def render_options(args):
    options = dict(DEFAULTS)
    if args.preset:
        supplied = json.loads(args.preset.expanduser().read_text())
        if not isinstance(supplied, dict):
            raise ValueError("A preset must be a JSON object of render options.")
        unknown = set(supplied) - set(DEFAULTS)
        if unknown:
            raise ValueError("Unknown preset options: " + ", ".join(sorted(unknown)))
        options.update(supplied)
    if args.tiktok:
        options.update(TIKTOK)
    for key in DEFAULTS:
        value = getattr(args, key, None)
        if value is not None:
            options[key] = value
    return validate_options(options)


def image_runtime(argv):
    from .runtime import maybe_reexec

    maybe_reexec(argv)
    if any(importlib.util.find_spec(name) is None for name in ("PIL", "numpy", "scipy", "plyfile")):
        raise RuntimeError("The image runtime is missing. Run dollyzoom setup first.")


def execute(args, argv):
    from .runtime import find_runtime, setup, missing_runtime, data_home

    if args.command == "schema":
        return contract(), 0
    if args.command == "setup":
        return {"runtime": setup()}, 0
    if args.command == "doctor":
        runtime = find_runtime()
        missing = missing_runtime(runtime)
        return {
            "runtime": runtime,
            "data_home": str(data_home()),
            "missing": missing,
            "ready": not missing,
            "note": "Rendering also tests browser GPU support.",
        }, int(bool(missing))
    if args.command == "view":
        if args.json:
            raise UsageError("view is a long-running interactive server; omit --json.")
        if not 0 <= args.port <= 65535:
            raise UsageError("--port must be between 0 and 65535.")
        import time
        import webbrowser
        from .runtime import require_runtime
        from .server import PreviewServer

        folder = args.folder.expanduser().resolve()
        config = json.loads((folder / "job.json").read_text())
        if config.get("status") != "complete":
            raise ValueError("This run has not finished rendering.")
        with PreviewServer(folder, require_runtime(), config, port=args.port) as server:
            print("Viewer: " + server.url, flush=True)
            if not args.no_open:
                webbrowser.open(server.url)
            while True:
                time.sleep(1)
    focal_value(args.focal_mm)
    source = args.photo.expanduser().resolve()
    if not source.is_file():
        raise ValueError("Photo does not exist or is not a file: " + str(source))
    if args.command == "inspect":
        image_runtime(argv)
        from .imaging import prepare_image

        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        key = hashlib.sha256(f"{digest}:{args.focal_mm}".encode()).hexdigest()[:20]
        folder = data_home() / "cache/inputs" / key
        result = prepare_image(source, folder, args.focal_mm)
        return {
            **result,
            "preview_path": str(folder / "preview.jpg"),
            "assessment_kind": "Image preflight only; anchor/depth assessment requires run or assess.",
        }, 0
    options = render_options(args)
    if args.json and args.anchor is None:
        raise UsageError("--json run/assess requires --anchor X,Y to avoid waiting for a picker.")
    if args.picker_timeout <= 0:
        raise UsageError("--picker-timeout must be positive.")
    if args.output and args.output.expanduser().exists():
        output = args.output.expanduser()
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("Output folder must be empty. Existing files are never overwritten.")
    image_runtime(argv)
    from .pipeline import run_photo

    out = run_photo(
        source,
        args.anchor,
        args.anchor_label,
        args.output,
        options,
        args.focal_mm,
        args.command == "assess",
        args.no_open or args.json,
        args.reuse_scene,
        args.save_frames,
        args.picker_timeout,
    )
    job = json.loads((out / "job.json").read_text())
    result = {
        "run_folder": str(out),
        "status": job["status"],
        "assessment": job["assessment"],
        "artifacts": {
            name: str(out / name)
            for name in ("job.json", "suitability.json", "SUITABILITY.md", "preview.jpg")
        },
    }
    if job["status"] == "complete":
        result["artifacts"].update(
            {
                name: str(out / name)
                for name in ("dolly_zoom.mp4", "dolly_zoom.gif", "scene.ply", "validation.json")
            }
        )
    return result, 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in argv
    # Permit global JSON before or after the command, including photo shorthand.
    operands = [arg for arg in argv if arg != "--json"]
    commands = {"run", "assess", "inspect", "setup", "doctor", "schema", "view"}
    if operands and not operands[0].startswith("-") and operands[0] not in commands:
        operands.insert(0, "run")
    argv = (["--json"] if json_mode else []) + operands
    command = operands[0] if operands and operands[0] in commands else None
    try:
        args = build_parser().parse_args(argv)
        with contextlib.redirect_stdout(sys.stderr):
            result, code = execute(args, argv)
        if args.json or args.command == "schema":
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ok": code == 0,
                        "command": args.command,
                        "result": result,
                    },
                    indent=2,
                    allow_nan=False,
                )
            )
        elif args.command in ("run", "assess"):
            print("Run folder: " + result["run_folder"])
        else:
            print(json.dumps(result, indent=2, allow_nan=False))
        return code
    except KeyboardInterrupt:
        error, code = RuntimeError("Stopped."), 130
    except (
        ValueError,
        RuntimeError,
        OSError,
        TimeoutError,
        subprocess.SubprocessError,
        ImportError,
    ) as caught:
        error, code = caught, 2
    if json_mode:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "command": command,
                    "error": {"type": type(error).__name__, "message": str(error)},
                },
                indent=2,
            )
        )
    else:
        print("dollyzoom: " + str(error), file=sys.stderr)
    return code


def entrypoint():
    return main()


if __name__ == "__main__":
    raise SystemExit(entrypoint())
