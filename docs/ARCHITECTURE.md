# How it works

The CLI parses and validates settings with the standard library. Image commands
re-execute in the managed Python environment when it exists, so installing the
small CLI does not install PyTorch. Writable data stays outside site-packages.

```text
photo → oriented sRGB pixels → SHARP Gaussian reconstruction (cached)
      → selected anchor + suitability → optional refinement
      → Spark/Three.js in local Chromium → frames → FFmpeg MP4/GIF
      → geometric, media and metadata validation → completed run
```

`cli.py` owns commands and JSON output; `options.py` owns defaults and constraints.
`runtime.py` owns paths, dependency discovery, setup and checksum validation.
`imaging.py` normalizes input; `inference.py` runs pinned upstream SHARP.
`geometry.py` estimates anchor depth, assesses suitability and refines splats.
`pipeline.py` assembles jobs; `server.py` serves a loopback-only asset allowlist.
The browser assets implement camera motion and Gaussian rendering.

For anchor axial depth `D`, starting focal length `f0` and lens ratio `r`, move
backward by `D * (r - 1)` and use `f = f0 * r`. On the anchor plane:

```text
projected_scale = f0 * r / (D + D * (r - 1)) = f0 / D
```

This keeps position and scale fixed even for an off-center anchor. Use axial depth,
not the Euclidean distance to the point. The 35 mm equivalent focal conversion is
`f_px = f_mm * hypot(width, height) / hypot(36, 24)`. SHARP uses its standard
1536×1536 internal input; calibrated unprojection retains source aspect ratio.

Cleanup contracts selected foreground Gaussians along camera rays and adjusts
visible colors. Auto background fill only runs for small isolated foreground
against suitably smooth surroundings. It estimates continuation from neighbors;
it does not discover hidden detail. Raw reconstruction and refined results stay
separate so a new anchor does not reuse cleanup for a different subject.

The browser server binds `127.0.0.1` on an ephemeral port. It serves only named run
assets and the permitted viewer dependency paths; it is intended for a trusted
local machine, not public hosting. Chrome's sandbox stays enabled by default.
`DOLLYZOOM_NO_SANDBOX=1` is an explicit compatibility override for environments
that require it. `PHOTO_DOLLY_RUNTIME`, `PHOTO_DOLLY_BROWSER`, and
`PHOTO_DOLLY_NO_SANDBOX` remain legacy environment aliases.
