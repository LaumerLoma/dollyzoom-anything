"""Find an isolated local runtime; download dependencies only on explicit setup."""

from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
MODEL_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
MODEL_SHA = "94211a75198c47f61fca7d739ba08a215418d8d398d48fddf023baccc24f073d"
SHARP_COMMIT = "aed6527499ef91cba3b54c18d49a870f25947190"
REQUIRED = ("python", "sharp", "model", "node_modules", "node", "ffmpeg", "ffprobe", "browser")
VIEWER_PACKAGES = {"three": "0.180.0", "@sparkjsdev/spark": "2.3.1", "playwright-core": "1.65.1"}


def data_home():
    """Keep writable state out of the installed package and source tree."""
    return Path(os.environ.get("DOLLYZOOM_HOME", Path.home() / ".dollyzoom")).expanduser().resolve()


def runtime_home():
    override = os.environ.get("DOLLYZOOM_RUNTIME") or os.environ.get("PHOTO_DOLLY_RUNTIME")
    return Path(override).expanduser().resolve() if override else data_home() / "runtime"


def find_runtime():
    roots = [runtime_home()]
    # An explicit override is authoritative, including when incomplete.
    if not (os.environ.get("DOLLYZOOM_RUNTIME") or os.environ.get("PHOTO_DOLLY_RUNTIME")):
        roots += [ROOT / "runtime", ROOT.parent / "gaussian_splat"]
    result = {}
    for base in roots:
        python = base / ".venv/bin/python"
        sharp = next(
            (p for p in (base / "vendor/ml-sharp", base / "sharp") if (p / "src/sharp").is_dir()),
            None,
        )
        modules = next(
            (p for p in (base / "viewer/node_modules", base / "node_modules") if p.is_dir()), None
        )
        if python.is_file():
            # Select one installation instead of mixing partial environments.
            result = {
                "python": str(python.absolute()),
                "sharp": str(sharp) if sharp else None,
                "model": str(base / "models/sharp_full.pt")
                if (base / "models/sharp_full.pt").is_file()
                else None,
                "node_modules": str(modules) if modules else None,
            }
            break
    for name in ("node", "ffmpeg", "ffprobe"):
        result[name] = shutil.which(name)
    browsers = [
        os.environ.get("DOLLYZOOM_BROWSER") or os.environ.get("PHOTO_DOLLY_BROWSER"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    result["browser"] = next((str(p) for p in browsers if p and Path(p).is_file()), None)
    return result


def missing_runtime(runtime):
    missing = [key for key in REQUIRED if not runtime.get(key)]
    if runtime.get("node_modules"):
        for package, version in VIEWER_PACKAGES.items():
            try:
                actual = json.loads(
                    (Path(runtime["node_modules"]) / package / "package.json").read_text()
                )["version"]
                if actual != version:
                    missing.append(f"{package}@{version} (found {actual})")
            except (OSError, ValueError, KeyError, TypeError):
                missing.append(f"{package}@{version}")
    return missing


def require_runtime():
    result = find_runtime()
    missing = missing_runtime(result)
    if missing:
        raise RuntimeError(
            "Missing runtime: "
            + ", ".join(missing)
            + ". Run dollyzoom setup, then dollyzoom doctor."
        )
    return result


def maybe_reexec(argv):
    """Run image commands in the managed Python venv after a tiny CLI install."""
    python = find_runtime().get("python")
    if python and Path(python).absolute() != Path(sys.executable).absolute():
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT.parent) + os.pathsep + env.get("PYTHONPATH", "")
        os.execve(python, [python, "-m", "photo_dolly", *argv], env)


def verify_model(path):
    path = Path(path)
    stamp = path.with_suffix(".verified.json")
    expected = {
        "size": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
        "sha256": MODEL_SHA,
    }
    try:
        if json.loads(stamp.read_text()) == expected:
            return
    except (OSError, ValueError):
        pass
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != MODEL_SHA:
        raise RuntimeError("The SHARP checkpoint checksum does not match the pinned checksum.")
    try:
        stamp.write_text(json.dumps(expected))
    except OSError:
        pass


def setup():
    if sys.platform == "win32":
        raise RuntimeError(
            "Setup currently supports POSIX systems. Use macOS or Linux; Windows is untested."
        )
    target = runtime_home()
    uv = shutil.which("uv")
    tools = {name: shutil.which(name) for name in ("git", "node", "npm", "ffmpeg", "ffprobe")}
    missing = (["uv"] if not uv else []) + [name for name, path in tools.items() if not path]
    if missing:
        raise RuntimeError("Install these prerequisites first: " + ", ".join(missing))
    print(
        "SHARP model license: non-commercial scientific research only. See docs/THIRD_PARTY.md.",
        file=sys.stderr,
    )
    target.mkdir(parents=True, exist_ok=True)

    def execute(command):
        subprocess.run(command, check=True, stdout=sys.stderr)

    python = target / ".venv/bin/python"
    if not python.exists():
        execute([uv, "venv", "--python", "3.13", str(target / ".venv")])
    execute(
        [uv, "pip", "install", "--python", str(python), "-r", str(ROOT / "requirements.lock.txt")]
    )
    sharp = target / "vendor/ml-sharp"
    sharp.parent.mkdir(exist_ok=True)
    if not sharp.exists():
        execute(
            [
                tools["git"],
                "clone",
                "https://github.com/apple-aiml-research/ml-sharp.git",
                str(sharp),
            ]
        )
    execute([tools["git"], "-C", str(sharp), "checkout", "--detach", SHARP_COMMIT])
    viewer = target / "viewer"
    viewer.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "viewer-package.json", viewer / "package.json")
    shutil.copyfile(ROOT / "viewer-package-lock.json", viewer / "package-lock.json")
    execute(
        [tools["npm"], "ci", "--prefix", str(viewer), "--no-audit", "--no-fund", "--ignore-scripts"]
    )
    models = target / "models"
    models.mkdir(exist_ok=True)
    model = models / "sharp_full.pt"
    if not model.exists():
        partial = model.with_suffix(".download")
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(
            MODEL_URL, headers={"Range": f"bytes={offset}-"} if offset else {}
        )
        print("Downloading the 2.8 GB model; later runs reuse it.", file=sys.stderr, flush=True)
        with urllib.request.urlopen(request, timeout=120) as response:
            append = offset > 0 and response.status == 206
            if append and not response.headers.get("Content-Range", "").startswith(
                f"bytes {offset}-"
            ):
                raise RuntimeError("The download server returned an unexpected byte range.")
            with partial.open("ab" if append else "wb") as stream:
                shutil.copyfileobj(response, stream, 8 * 1024 * 1024)
        try:
            verify_model(partial)
        except RuntimeError:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(model)
    verify_model(model)
    result = find_runtime()
    missing = missing_runtime(result)
    if missing:
        raise RuntimeError(
            "Setup completed downloads but prerequisites are missing: " + ", ".join(missing)
        )
    return result
