"""Photo → assessed anchor → Gaussian scene → verified dolly zoom."""

from pathlib import Path
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import webbrowser
import numpy as np
from PIL import Image
from scipy import signal
from .imaging import prepare_image
from .geometry import Scene, polish
from .inference import reconstruct
from .server import PreviewServer
from .runtime import ROOT, require_runtime, MODEL_SHA, SHARP_COMMIT, data_home
from .options import DEFAULTS
from . import __version__


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def application_version():
    files = sorted(
        [*ROOT.glob("*.py"), ROOT / "requirements.lock.txt", *ROOT.joinpath("assets").glob("*")]
    )
    sources = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
        if path.is_file()
    }
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    return {"version": __version__, "source_sha256": digest, "source_files": sources}


def crop_rect(meta, options, anchor):
    width, height = meta["image_width"], meta["image_height"]
    vw, vh = width / options["crop"], height / options["crop"]
    center = anchor if options["crop_mode"] == "anchor" else [0.5, 0.5]
    return [center[0] * (width - vw), center[1] * (height - vh), vw, vh]


def make_config(meta, options, anchor, label, assessment, gaussians):
    rect = crop_rect(meta, options, anchor["uv"])
    uv = [
        (anchor["uv"][0] * meta["image_width"] - rect[0]) / rect[2],
        (anchor["uv"][1] * meta["image_height"] - rect[1]) / rect[3],
    ]
    if not all(0.01 < value < 0.99 for value in uv):
        raise ValueError(
            "This centered crop moves the anchor outside the image. Use --crop-mode anchor or reduce --crop."
        )
    scale = options["long_edge"] / max(meta["image_width"], meta["image_height"])
    size = [
        max(64, int(round(meta["image_width"] * scale / 2)) * 2),
        max(64, int(round(meta["image_height"] * scale / 2)) * 2),
    ]
    capture = [int(round(value * options["supersample"] / 2)) * 2 for value in size]
    loop = options["half_seconds"] * (2 if options["motion"] == "bounce" else 1)
    loops = 1
    if options["motion"] == "bounce":
        # A BPM clip repeats whole loops (default ≥8 s) so a looping export stays on tempo.
        target = options.get("clip_seconds") or (8 if options.get("bpm") else loop)
        loops = max(1, math.ceil(target / loop - 1e-9))
    frames = max(2, round(loop * loops * options["fps"]))
    return {
        "loop_seconds": loop,
        "loops": loops,
        "version": 1,
        "image": meta,
        "options": options,
        "anchor": {**anchor, "label": label, "framed_uv": uv},
        "assessment": assessment,
        "gaussian_count": gaussians,
        "crop_rect": rect,
        "video_size": size,
        "capture_size": capture,
        "duration_seconds": frames / options["fps"],
        "frame_count": frames,
        "background_depth": assessment["depth_far"],
    }


def markdown_assessment(meta, result, label):
    lines = [
        f"# Suitability: {result['rating']}",
        "",
        f"Photo: {meta['input_name']}. Anchor: {label}.",
        "",
    ]
    lines += ["- " + text for text in result["reasons"]]
    lines += ["- " + text for text in result["cautions"]]
    lines += [
        "",
        f"Predicted background growth: {result['predicted_background_growth_factor']:.3f}×.",
        f"Near foreground scale at the end: {result['near_foreground_scale_factor']:.3f}×.",
        f"Suggested maximum lens multiplier for a restrained first test: {result['suggested_max_strength']:.2f}×.",
        "",
        result["basis"],
        result["visual_review_note"],
        "",
    ]
    return "\n".join(lines)


def validate_render(run, config):
    report = json.loads((run / "render_report.json").read_text())
    video = json.loads((run / "video_report.json").read_text())
    if report["browser_errors"]:
        raise RuntimeError("The browser reported rendering errors.")
    if int(video["streams"][0]["nb_frames"]) != config["frame_count"]:
        raise RuntimeError("Wrong video frame count.")
    if abs(float(video["format"]["duration"]) - config["duration_seconds"]) > 0.002:
        raise RuntimeError("Wrong video duration.")
    for tags in [video["format"].get("tags", {}), video["streams"][0].get("tags", {})]:
        if any(key in tags for key in ("encoder", "artist", "author", "comment", "creation_time")):
            raise RuntimeError("Unexpected descriptive video metadata.")
    image = Image.open(run / "input.png").convert("RGB")
    rect = config["crop_rect"]
    bounds = [rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]]
    with (
        Image.open(run / "start.png") as first,
        Image.open(run / "peak.png") as peak,
        Image.open(run / "loop_end.png") as last,
    ):
        for saved in (first, peak, last):
            saved.load()
            if saved.getexif() or any(
                k.lower() in ("author", "comment", "software", "xmp") for k in saved.info
            ):
                raise RuntimeError("Unexpected image metadata.")
        base = np.asarray(first.convert("RGB")).astype(float)
        finish = np.asarray(last.convert("RGB")).astype(float)
        reference = np.asarray(
            image.transform(first.size, Image.Transform.EXTENT, bounds, Image.Resampling.BICUBIC)
        ).astype(float)
        front_mae = float(np.abs(base - reference).mean())
        seam = float(np.abs(base - finish).mean())
        # Track the selected rendered patch independently of the camera equations.
        small_size = config["video_size"]
        a = np.asarray(first.convert("L").resize(small_size)).astype(float)
        b = np.asarray(peak.convert("L").resize(small_size)).astype(float)
        x, y = [
            int(round(uv * size)) for uv, size in zip(config["anchor"]["framed_uv"], small_size)
        ]
        radius = 10
        search = 6
        tracking = {"available": False, "reason": "Anchor patch is flat or too close to the edge."}
        if (
            x > radius + search
            and y > radius + search
            and x + radius + search < a.shape[1]
            and y + radius + search < a.shape[0]
        ):
            template = a[y - radius : y + radius + 1, x - radius : x + radius + 1]
            window = b[
                y - radius - search : y + radius + search + 1,
                x - radius - search : x + radius + search + 1,
            ]
            template = template - template.mean()
            if template.std() > 3:
                numerator = signal.correlate2d(window, template, mode="valid")
                ones = np.ones_like(template)
                mean = signal.correlate2d(window, ones, mode="valid") / template.size
                var = signal.correlate2d(window**2, ones, mode="valid") - mean**2 * template.size
                ncc = numerator / np.maximum(
                    np.sqrt(np.maximum(var, 0) * (template**2).sum()), 1e-6
                )
                yy, xx = np.unravel_index(ncc.argmax(), ncc.shape)
                tracking = {
                    "available": True,
                    "peak_offset_pixels": [int(xx - search), int(yy - search)],
                    "correlation": float(ncc[yy, xx]),
                    "note": "Local texture matching is an independent approximate check; a deforming/flat patch may not track reliably.",
                }
    validation = {
        "front_view_mean_absolute_rgb_difference_0_to_255": front_mae,
        "first_last_frame_mean_absolute_rgb_difference": seam,
        "anchor_patch_tracking": tracking,
        "geometric_anchor_drift_pixels": report["max_anchor_drift_pixels"],
        "exact_loop_closed": report["exact_loop_closed"],
        "metadata_checked": True,
    }
    save_json(run / "validation.json", validation)
    return validation


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "anchor"


def run_photo(
    source,
    anchor_uv=None,
    label="Selected point",
    output=None,
    options=None,
    focal_mm=None,
    assess_only=False,
    no_open=False,
    reuse_scene=None,
    save_frames=False,
    picker_timeout=3600,
):
    runtime = require_runtime()
    options = {**DEFAULTS, **(options or {})}
    if output:
        destination = Path(output).expanduser().resolve()
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError("Output folder must be empty. Existing files are never overwritten.")
    source = Path(source).expanduser().resolve()
    with source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    input_key = hashlib.sha256(f"{source_hash}:{focal_mm}".encode()).hexdigest()[:20]
    inputs = data_home() / "cache/inputs" / input_key
    meta = prepare_image(source, inputs, focal_mm)
    scene_identity = f"{MODEL_SHA}:{SHARP_COMMIT}:oriented-sRGB-v1"
    if reuse_scene:
        with Path(reuse_scene).open("rb") as stream:
            scene_identity = "import:" + hashlib.file_digest(stream, "sha256").hexdigest()
    key = hashlib.sha256(
        f"{source_hash}:{meta['focal_length_px']}:{scene_identity}".encode()
    ).hexdigest()[:20]
    raw, scene_meta = reconstruct(
        inputs / "input.png", meta, data_home() / "cache/scenes" / key, runtime, reuse_scene
    )
    scene = Scene(raw, meta)
    if anchor_uv is None:
        with PreviewServer(
            inputs, runtime, {"image": meta, "options": options}, scene=scene
        ) as server:
            print("Choose the fixed point: " + server.url + "/picker", flush=True)
            if not no_open:
                webbrowser.open(server.url + "/picker")
            if not server.selected.wait(picker_timeout):
                raise TimeoutError(
                    "No anchor was selected. Re-run with --anchor X,Y or use the picker."
                )
            anchor_uv = server.selection["uv"]
            label = server.selection["label"]
    assessment = scene.assess(anchor_uv, options["strength"], options["crop"], options["crop_mode"])
    print("Suitability: " + assessment["rating"], flush=True)
    for reason in assessment["reasons"] + assessment["cautions"]:
        print("  " + reason, flush=True)
    identifier = hashlib.sha256(
        json.dumps(
            {"scene": key, "anchor": anchor_uv, "label": label, "options": options}, sort_keys=True
        ).encode()
    ).hexdigest()[:8]
    run = (
        Path(output).expanduser().resolve()
        if output
        else data_home() / "runs" / f"{slug(source.stem)}-{identifier}"
    )
    if output:
        run.mkdir(parents=True, exist_ok=True)
        if any(run.iterdir()):
            raise ValueError("Output folder must be empty. Existing files are never overwritten.")
    else:
        parent = run.parent
        parent.mkdir(parents=True, exist_ok=True)
        base = run
        sequence = 1
        while True:
            try:
                run.mkdir()
                break
            except FileExistsError:
                sequence += 1
                run = parent / f"{base.name}-{sequence}"
    for name in ("input.png", "preview.jpg", "image.json"):
        shutil.copyfile(inputs / name, run / name)
    save_json(run / "suitability.json", assessment)
    (run / "SUITABILITY.md").write_text(markdown_assessment(meta, assessment, label))
    initial = {
        "version": 1,
        "tool": "dollyzoom",
        "application": application_version(),
        "status": "assessed",
        "image": meta,
        "options": options,
        "anchor": {"uv": anchor_uv, "label": label},
        "assessment": assessment,
    }
    save_json(run / "job.json", initial)
    if assess_only:
        return run
    print("Refining the Gaussian scene…", flush=True)
    polish_report = polish(
        scene, run / "input.png", run / "scene.ply", assessment, options["polish"]
    )
    save_json(run / "polish.json", polish_report)
    config = make_config(
        meta, options, assessment["anchor"], label, assessment, polish_report["gaussian_count"]
    )
    config["tool"] = "dollyzoom"
    config["application"] = initial["application"]
    config["reconstruction"] = scene_meta
    config["polish"] = polish_report
    config["status"] = "ready_to_render"
    save_json(run / "job.json", config)
    frames = run / "frames"
    if frames.exists():
        shutil.rmtree(frames)
    print(f"Rendering {config['frame_count']} frames at {options['fps']} fps…", flush=True)
    with PreviewServer(run, runtime, config) as server:
        request = {"url": server.url, "run": str(run), "runtime": runtime, "config": config}
        save_json(run / "render_request.json", request)
        env = dict(os.environ)
        env["NODE_PATH"] = runtime["node_modules"]
        try:
            subprocess.run(
                [
                    runtime["node"],
                    str(ROOT / "assets/render.mjs"),
                    str(run / "render_request.json"),
                ],
                check=True,
                env=env,
                stdout=sys.stderr,
            )
        except subprocess.CalledProcessError as error:
            config["status"] = "render_failed"
            save_json(run / "job.json", config)
            raise RuntimeError(
                "The browser render failed; see its error above and render_failed.json if available."
            ) from error
    validation = validate_render(run, config)
    config["status"] = "complete"
    save_json(run / "job.json", config)
    (run / "README.md").write_text(
        "# Photo dolly zoom\n\n"
        f"Input: {source.name}. Anchor: {label}. Suitability: {assessment['rating']}.\n\n"
        f"{config['duration_seconds']:g} seconds at {options['fps']} fps; {options['strength']:.2f}× lens multiplier; {options['crop']:.2f}× crop.\n\n"
        "Open dolly_zoom.mp4 or dolly_zoom.gif. scene.ply contains the actual refined Gaussian scene.\n"
        "job.json records the image hash, anchor, camera calibration, options, model version and refinement.\n"
        "SUITABILITY.md explains the assessment. validation.json and render_report.json record the checks.\n\n"
        "This is a single-photo estimate intended for modest camera movements; hidden background is inferred.\n"
        f"Render patch check: {json.dumps(validation['anchor_patch_tracking'])}.\n"
    )
    if not save_frames:
        shutil.rmtree(frames)
    print("READY: " + str(run / "dolly_zoom.mp4"), flush=True)
    return run
