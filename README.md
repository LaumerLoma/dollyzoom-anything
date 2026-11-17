# Dollyzoom anything

**One photo. One fixed point. A whole new perspective.**

`dollyzoom` turns a photograph into an anchored dolly zoom: your subject stays in
place while the background changes scale. Pick a point, choose a look, and render
an MP4 and GIF locally from an estimated 3D Gaussian scene.

“Anything” starts with a photo: portraits, objects, landscapes, architecture.
Results depend on depth cues and the chosen anchor. Hidden surfaces are inferred;
this is a modest camera move from one image, not a complete 3D scan.

> **Model license:** the current Apple SHARP backend is restricted to
> non-commercial scientific research. The CLI code is MIT licensed; that does
> not change the model's terms. See [third-party notices](docs/THIRD_PARTY.md).

## Quick start

Python **3.11+** runs the CLI. Rendering setup creates a separate **Python 3.13**
environment and needs **uv, Git, Node.js 20+, npm, FFmpeg/ffprobe, and Chrome or
Chromium** on your PATH (Chrome is also detected in its usual macOS location).
Apple Silicon macOS is the validated rendering platform. Linux CPU/CUDA paths
exist but need validation on your hardware; Windows setup is not supported yet.
Allow several GB for dependencies and the **2.8 GB** checkpoint, plus render space.

From a downloaded or cloned copy of this repository:

```sh
uv tool install .
dollyzoom setup
dollyzoom doctor
dollyzoom photo.jpg
```

Or use `python3 -m pip install .` in a virtual environment. From a checkout,
`./dollyzoom` also works without installing the CLI. Setup is the explicit network
step; inference and rendering use local files. Subsequent photos reuse the model.
No API key or hosted inference service is required.

Click inside the subject in the local picker, then choose **Use this anchor**.
For a terminal-only selection:

```sh
dollyzoom photo.jpg --anchor 0.5,0.4 --anchor-label "subject" --output ./result
```

Coordinates are normalized fractions of the **correctly oriented** image:
`0,0` is top-left, `1,1` is bottom-right. `--anchor-label` only names the point;
it does not find an object. The output folder must be empty.

## Features

- **Anchored camera motion:** holds the selected depth plane's position and scale.
- **Suitability first:** explains whether the photo, anchor, and strength work together.
- **Local reconstruction:** caches SHARP scenes across new anchors and render settings.
- **Smooth or bouncy loops:** out-and-back or forward motion, with optional BPM timing.
- **Photo-shaped exports:** preserves aspect ratio, with supersampling and MP4/GIF output.
- **Conservative refinement:** optional streak reduction and scene-dependent background fill.
- **Reviewable results:** saves the scene, preview frames, settings, hashes, and validation reports.
- **Agent-friendly CLI:** JSON results, explicit exit codes, and machine-readable settings.

## A few useful commands

```sh
# Preview and image preflight; no model inference.
dollyzoom inspect photo.jpg --json

# Assess the chosen anchor without rendering a video (still needs the model).
dollyzoom assess photo.jpg --anchor 0.45,0.4 --no-open

# A restrained loop with the anchor kept inside an off-center crop.
dollyzoom photo.jpg --anchor 0.2,0.4 --crop-mode anchor --strength 1.15

# Faster bouncy movement; tempo sets the leg duration.
dollyzoom photo.jpg --anchor 0.5,0.4 --tiktok --bpm 120 --beats 2

# Reuse a preset; explicit flags take precedence.
dollyzoom photo.jpg --anchor 0.5,0.4 \
  --preset photo_dolly/examples/smooth-bounce.json --half-seconds 1.5

# Keep this process running to use the interactive result viewer.
dollyzoom view ./result --no-open
```

| Setting | Default | What it changes |
| --- | --- | --- |
| `--strength` | `1.25` | Lens multiplier and corresponding dolly travel |
| `--crop` / `--crop-mode` | `1.15` / `center` | Static framing; `anchor` retains an off-center point |
| `--half-seconds` | `2` | Seconds per leg: a four-second bounce loop |
| `--motion` / `--easing` | `bounce` / `smooth` | `forward` for one move; `bouncy` for snap and settle |
| `--fps` / `--long-edge` | `60` / `1080` | Frame rate and output long edge, preserving aspect ratio |
| `--supersample` | `1.5` | Render scale before downsampling |
| `--polish` | `auto` | `off`, `conservative`, `auto`, or explicit estimated `fill` |
| `--bpm` / `--beats` | off / `1` | Beat timing; overrides seconds per leg |
| `--clip-seconds` | one loop | Minimum bounce duration, rounded to whole loops; BPM defaults to ≥8 s |
| `--focal-mm` | EXIF, else `30` | Override the 35 mm equivalent focal length |

Run `dollyzoom run --help` for every flag and `dollyzoom schema` for ranges.
`photo-dolly` remains a compatibility alias.

## Connect an agent

Give any agent with shell access the `dollyzoom` executable. No server or SDK is
needed: run `dollyzoom schema`, inspect the photo, then pass the chosen coordinates.

```sh
dollyzoom inspect photo.jpg --json
dollyzoom assess photo.jpg --anchor 0.5,0.4 --json
dollyzoom run photo.jpg --anchor 0.5,0.4 --output ./result --json
```

`--json` writes **one JSON object to stdout**, with progress on stderr. Read
`result.artifacts["dolly_zoom.mp4"]` after a successful run. JSON mode requires
`--anchor` so it never waits for a picker. Agents can interpret named subjects
from `inspect`'s `preview_path`; the CLI itself takes coordinates. See the short
[agent contract](docs/AGENTS.md) for a Python example and error handling.

## Results and best practices

By default, state lives in `~/.dollyzoom/`: `runtime/`, `cache/`, and `runs/`.
`--output` puts a run elsewhere. A nonempty output directory is rejected;
repeated default runs get distinct folders. Source photos are never modified.

A complete run includes `dolly_zoom.mp4`, `dolly_zoom.gif`, `scene.ply`,
`start.png`, `peak.png`, `loop_end.png`, `preview.jpg`, `job.json`,
`SUITABILITY.md`, `suitability.json`, and validation reports. Temporary frames are
removed after success unless you pass `--save-frames`. Failed runs keep diagnostics.
Derived images strip inherited EXIF/GPS/author data; manifests intentionally retain
input filenames, content hashes, settings, and runtime details. Share the finished
media when you do not want to share those manifests or the source pixels.

Start around **1.15–1.3×** with a sharp subject and clear depth separation. Place
the anchor inside a solid, well-defined part of the subject. Review the peak frame
and loop: glass, reflections, hair, thin edges, and newly exposed background can
break the illusion. A suitability rating is advice; it does not block rendering.

Use `DOLLYZOOM_HOME` to relocate all state, `DOLLYZOOM_RUNTIME` for an existing
compatible runtime, or `DOLLYZOOM_BROWSER` for a browser executable. See
[specifications](docs/SPEC.md) for the full behavior and current limitations.

## Development and publishing

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m unittest discover -s tests/unit -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m build
python3 scripts/build_release.py
```

The source ZIP in `dist/` uses an explicit file allowlist. Python packages and
`.gitignore` exclude the local photos, weights, outputs, legacy experiments, and
environments. Existing experiment files stay on disk. See
[contributing](CONTRIBUTING.md), [release checks](docs/RELEASING.md),
[camera math](docs/ARCHITECTURE.md), and [changelog](CHANGELOG.md).
