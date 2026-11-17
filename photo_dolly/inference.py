"""Full SHARP inference with camera calibration and a reusable scene cache."""

from pathlib import Path
import gc
import hashlib
import json
import os
import sys
import time
import shutil
from .runtime import verify_model, MODEL_SHA, SHARP_COMMIT


def reconstruct(image_path, meta, cache, runtime, reuse_scene=None):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    raw = cache / "raw.ply"
    manifest = cache / "scene.json"
    imported_digest = None
    if reuse_scene:
        with Path(reuse_scene).open("rb") as stream:
            imported_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if raw.exists() and manifest.exists():
        stored = json.loads(manifest.read_text())
        matching_origin = (
            (stored.get("imported_scene_sha256") == imported_digest)
            if reuse_scene
            else (
                stored.get("model_sha256") == MODEL_SHA
                and stored.get("sharp_commit") == SHARP_COMMIT
            )
        )
        if (
            matching_origin
            and stored.get("source_sha256") == meta["source_sha256"]
            and stored.get("focal_length_px") == meta["focal_length_px"]
        ):
            print("Reusing the cached Gaussian reconstruction.", flush=True)
            return raw, stored
    if reuse_scene:
        supplied = Path(reuse_scene)
        if not supplied.is_file():
            raise ValueError("The supplied cached scene does not exist.")
        # Explicit advanced import; calibration is supplied by the current photo.
        shutil.copyfile(supplied, raw)
        stored = {
            **meta,
            "method": "Explicitly imported cached Gaussian scene; model provenance not asserted",
            "model_sha256": None,
            "sharp_commit": None,
            "imported_scene_sha256": imported_digest,
        }
        manifest.write_text(json.dumps(stored, indent=2) + "\n")
        return raw, stored
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    os.environ.setdefault("MPLCONFIGDIR", str(cache.parent / ".mpl-cache"))
    os.environ.setdefault("HF_HOME", str(cache.parent / ".hf-cache"))
    sys.path.insert(0, str(Path(runtime["sharp"]) / "src"))
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image
    from sharp.models import PredictorParams, create_predictor
    from sharp.utils.gaussians import unproject_gaussians, save_ply

    torch.set_num_threads(min(8, os.cpu_count() or 4))
    verify_model(runtime["model"])
    started = time.monotonic()
    device = torch.device(
        "mps"
        if torch.backends.mps.is_available()
        else ("cuda" if torch.cuda.is_available() else "cpu")
    )
    print(f"Loading full SHARP on {device}…", flush=True)
    weights = torch.load(runtime["model"], map_location="cpu", weights_only=True, mmap=True)
    model = create_predictor(PredictorParams())
    model.load_state_dict(weights)
    model.eval().to(device)
    del weights
    gc.collect()
    image = np.asarray(Image.open(image_path).convert("RGB"))
    height, width = image.shape[:2]
    focal = meta["focal_length_px"]
    with torch.inference_mode():
        tensor = torch.from_numpy(image.copy()).float().to(device).permute(2, 0, 1) / 255
        resized = F.interpolate(
            tensor[None], size=(1536, 1536), mode="bilinear", align_corners=True
        )
        factor = torch.tensor([focal / width], device=device, dtype=torch.float32)
        inference_start = time.monotonic()
        ndc = model(resized, factor)
        if device.type == "mps":
            torch.mps.synchronize()
        inference_seconds = time.monotonic() - inference_start
        intrinsics = torch.tensor(
            [[focal, 0, width / 2, 0], [0, focal, height / 2, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            device=device,
            dtype=torch.float32,
        )
        intrinsics[0] *= 1536 / width
        intrinsics[1] *= 1536 / height
        gaussian = unproject_gaussians(
            ndc.to(torch.device("cpu")), torch.eye(4), intrinsics.cpu(), (1536, 1536)
        )
        for name, values in gaussian._asdict().items():
            if not torch.isfinite(values).all():
                raise ValueError(f"Non-finite predicted {name}.")
        save_ply(gaussian, focal, (height, width), raw)
        count = gaussian.mean_vectors.shape[1]
    del model, ndc, gaussian, tensor, resized
    gc.collect()
    if device.type == "mps":
        torch.mps.empty_cache()
    stored = {
        **meta,
        "method": "Apple SHARP single-photo Gaussian inference",
        "model_sha256": MODEL_SHA,
        "sharp_commit": SHARP_COMMIT,
        "gaussian_count": count,
        "device": str(device),
        "torch_version": torch.__version__,
        "inference_seconds": inference_seconds,
        "reconstruction_seconds": time.monotonic() - started,
    }
    manifest.write_text(json.dumps(stored, indent=2) + "\n")
    return raw, stored
