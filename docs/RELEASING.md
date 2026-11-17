# Preparing a GitHub release

The source checkout can contain ignored local research assets. The release builder
uses a source allowlist; do not upload the entire working folder or its old ZIPs.

1. Update `photo_dolly/__init__.py`, `pyproject.toml`, the viewer manifest/lock's
   project version and `CHANGELOG.md` together. The first release is `0.1.0`.
2. Run the unit tests, lint, formatting and builds listed in the README.
3. Inspect the wheel, sdist and `dist/dollyzoom-source.zip` file lists. They must
   contain no photos, generated reports, personal paths, model weights, runtime
   environments, experiment history or bundled third-party installations.
4. Unpack the source ZIP into a clean directory. Test `./dollyzoom --help`,
   `./dollyzoom schema` and the install with `uv tool install .` in an isolated
   tool directory. Doctor should report missing rendering dependencies cleanly.
5. For rendering changes, run setup on the supported platform, render a permitted
   fixture, review its media and confirm `job.json` reaches `complete`. Model
   downloads and GPU checks are outside the lightweight CI suite.
6. Review the README's platform claims, model restrictions, and third-party pins.
   Check availability of the proposed public repository/package name before
   publishing; no public name has been reserved by this project.
7. Review Git's candidate file list and ignored files before staging. This setup
   work does not initialize Git, stage, commit, push, create a repository or
   publish a package. Those are separate release actions.

The GitHub workflow tests changes without release credentials. It uploads build
artifacts for inspection; it does not deploy or publish automatically. After an
explicit release decision, the small source ZIP can be attached to a GitHub release.
