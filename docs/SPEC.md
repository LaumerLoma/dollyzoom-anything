# CLI specification · v0.1

## Scope

A local command-line tool converting one raster photo into a restrained, anchored
3D dolly zoom. Public command: `dollyzoom`; Python distribution:
`dollyzoom-anything`; module: `photo_dolly`. `photo-dolly` is an alias.
The initial release is alpha. The tagline describes creative subject choice,
not guaranteed results for every image or general video/3D input support.

## Commands

| Command | Input | Result | Requires model/runtime |
| --- | --- | --- | --- |
| `inspect` | Photo; optional focal override | Oriented preview and preflight JSON | Image libraries only |
| `assess` | Photo and anchor, or local picker | Suitability report and manifest | Yes |
| `run` | Photo and anchor, or local picker | Assessment, scene, MP4/GIF and checks | Yes |
| `view` | Completed run directory | Loopback viewer until interrupted | Browser and viewer runtime |
| `setup` | Installed system prerequisites | Managed Python, upstream code, JS and model | Downloads explicitly |
| `doctor` | Environment | Paths, missing components, readiness | No downloads |
| `schema` | None | Machine-readable CLI contract | Standard library only |

A photo path without a command is shorthand for `run`. File paths beginning with
`-` should be supplied after `--` with an explicit command. `--json` is reserved
as an option name. No subcommands silently install or download missing runtimes.

## Inputs and settings

JPEG, PNG, WebP and TIFF use Pillow; HEIC/HEIF uses the installed HEIF reader when
supported by that build. Export RAW images to sRGB first. Minimum image side: 64 px.
Orientation is applied before anchor coordinates. Embedded color profiles are
converted to sRGB when readable; invalid profiles fall back to decoded RGB pixels.
35 mm equivalent focal length comes from `--focal-mm` (5–500 mm), EXIF tag 41989,
or a recorded 30 mm fallback. Ordinary non-equivalent focal length is not substituted.

Anchors contain two finite fractions in `[0,1]`. Cropping must leave the point
inside the renderable image; `anchor` crop mode preserves its relative location.
The renderer constrains the anchor **plane**, not every part of a thick object.

`schema` is the authority for numeric limits and enum choices. Presets must be JSON
objects containing known render settings. Priority is built-in defaults, preset,
`--tiktok` shortcut, then explicit flags. Booleans and nonfinite values are rejected
for numeric settings; FPS and long edge must be integers.

BPM sets seconds per leg to `60 / bpm * beats`. The computed leg must remain
0.2–30 seconds. Bounce clips repeat whole loops to meet `--clip-seconds` (or ≥8 s
when BPM is set); frame counts round to the nearest output frame. Forward clips
export one leg and reject `--clip-seconds`. Even dimensions support H.264/yuv420p.
Bouncy movement stays within the assessed lens range and has a different starting
lens than smooth motion. A bounce's conceptual phase 1 closes exactly; its final
encoded frame precedes that closure to avoid a duplicate frame at the seam.

## Artifacts and state

`DOLLYZOOM_HOME` defaults to `~/.dollyzoom`; it contains the managed `runtime/`,
normalized `cache/inputs/`, reconstructed `cache/scenes/`, and result `runs/`.
`--output` changes only the result directory. Existing nonempty output directories
are rejected before inference; default runs get unique suffixes when repeated.
Original photos remain untouched. Successful runs remove transient frames unless
`--save-frames` was supplied. No automatic cache eviction is performed.

The scene key includes the source SHA-256, calibrated pixel focal length, pinned
model checksum, upstream revision and preprocessing revision. Changing render
settings or anchors reuses a compatible raw scene. Input caches distinguish focal
overrides. Concurrent writes to the same data directory are not supported; use
separate `DOLLYZOOM_HOME` values for concurrent workers.

`job.json` records status, settings, source hashes, anchor/depth, source-code hashes,
model revision and reconstruction details. An assessment-only job ends at
`assessed`; a render progresses through `ready_to_render` to `complete`, or records
`render_failed` for a browser-render failure. Encoding/validation failures may
leave `ready_to_render`; process exit status is authoritative. Do not infer success
from the presence of a partial MP4 alone.

## Validation

The renderer checks the actual Gaussian count, browser errors, projected anchor
position and plane scale across all frames, and conceptual bounce closure.
FFprobe verifies frame count and duration. Preview images and MP4 are checked for
inherited descriptive metadata. Reports also include approximate local texture
tracking and source/first-frame differences; these are diagnostics, not perceptual
quality guarantees. Source filenames/hashes and execution paths in technical
manifests are intentional and should be reviewed before sharing whole run folders.

## Platform and resource limits

Rendering was validated on Apple Silicon/MPS with 24 GB unified memory. Inference
selects MPS, CUDA, then CPU; covariance decomposition runs on CPU. Linux rendering
and CUDA need platform-specific validation. Windows setup is unsupported.
Use Node 20+, FFmpeg with libx264, and a Chrome/Chromium build with working WebGL2.
The full model is about 2.8 GB; peak memory and temporary frame storage depend on
resolution, supersampling, clip duration, and Gaussian count. No latency or minimum
RAM guarantee is made. Doctor checks paths and viewer versions; an actual render
is needed to establish GPU readiness.

Single-view reconstruction cannot recover true hidden surfaces. Glass, reflections,
flat scenes and large moves can fail. Suitability is a heuristic with four ratings:
highly suitable, workable, weak, unsuitable. Auto fill is conservative and inferred.
No remote URLs, directory batches, audio, trained custom models, universal scene
imports, or hosted service are part of this release's supported public interface.
