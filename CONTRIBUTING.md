# Contributing

Keep the public surface small: a photo, an anchor, render settings, and files an
agent or person can inspect. Describe new behavior in `docs/SPEC.md` and record it
in `CHANGELOG.md`. Add a regression test for behavior that can fail independently
of the implementation. Keep help/schema/doctor usable without scientific packages.

Use the development commands in the README. Unit tests use synthetic images and
scenes, without model downloads, a browser, a GPU, or private photographs. CI runs
unit tests, lint/format checks and package-build smoke tests. An actual rendering
change also needs a local GPU render and review of the start, peak, and loop.

Use argument arrays for subprocesses, bind local servers to loopback, validate
file paths and numeric settings before expensive work, and keep the browser sandbox
on by default. Never write caches or runtime downloads into the installed package.
Maintain JSON stdout as one object; send progress to stderr. Changes to result
shape require an explicit contract/version decision and corresponding agent docs.

Do not commit private inputs, generated run manifests, checkpoints, dependencies,
local environments or large media. The existing ignored experiment folders are
local working history. Curated public sample assets need a deliberate review of
content rights, metadata and size, plus an explicit ignore exception. Use synthetic
fixtures where possible. Do not include unrelated personal paths in documentation.

Dependency updates must retain upstream notices, verify the model checksum and
review model terms. Do not imply that this wrapper's MIT license covers the model.
For release steps, see `docs/RELEASING.md`.
