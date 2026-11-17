# Third-party software and model notices

The repository and release bundles contain the CLI integration and browser viewer
code, without model weights, vendored upstream source or installed dependencies.
The MIT [LICENSE](../LICENSE) covers this project's original code only. Upstream
software, models, browsers and codecs keep their own terms. Setup retrieves them
separately; upstream license files remain in those installations.

## Apple SHARP

Source: [apple-aiml-research/ml-sharp](https://github.com/apple-aiml-research/ml-sharp),
pinned to `aed6527499ef91cba3b54c18d49a870f25947190`.
Its [code license](https://github.com/apple-aiml-research/ml-sharp/blob/aed6527499ef91cba3b54c18d49a870f25947190/LICENSE)
and [model license](https://github.com/apple-aiml-research/ml-sharp/blob/aed6527499ef91cba3b54c18d49a870f25947190/LICENSE_MODEL)
are separate. The checkpoint license restricts use to **non-commercial scientific
research and academic development**, and excludes commercial exploitation, product
development, and commercial products or services. Publishing this wrapper under
MIT does not grant broader model rights. Review the upstream terms for your use.

Checkpoint: `sharp_2572gikvuh.pt` from Apple's model CDN; expected SHA-256:
`94211a75198c47f61fca7d739ba08a215418d8d398d48fddf023baccc24f073d`.
The digest is a project pin, not a statement that Apple separately published that
checksum. Downloads are verified before use; verification is cached against file
size and modification time. Inference preprocessing/unprojection follows upstream;
rendering uses Spark rather than SHARP's CUDA renderer.

## Viewer and runtime

| Dependency | Pin | Upstream |
| --- | --- | --- |
| Spark | 2.3.1 | [sparkjsdev/spark](https://github.com/sparkjsdev/spark) |
| Three.js | 0.180.0 | [mrdoob/three.js](https://github.com/mrdoob/three.js) |
| Playwright Core | 1.65.1 | [microsoft/playwright](https://github.com/microsoft/playwright) |

`photo_dolly/viewer-package-lock.json` records the exact viewer tree and package
integrity values. Setup uses `npm ci --ignore-scripts`. Python dependencies are
version-pinned in `photo_dolly/requirements.lock.txt`, preserving the working local
Python 3.13 environment; this version list is not a hash-locked cross-platform
resolver lock. Updates should be reviewed and tested together. PyTorch and its
transitive packages are installed in an isolated runtime. Chrome/Chromium and
FFmpeg are supplied by the user and are not redistributed here.
