"""Normalize orientation/color without changing the original photo."""

from pathlib import Path
import hashlib
import json
import io
import numpy as np
from PIL import Image, ImageOps, ImageCms
from scipy import ndimage


def prepare_image(source, directory, focal_mm=None):
    source, directory = Path(source).resolve(), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    with Image.open(source) as opened:
        exif = opened.getexif()
        photo_ifd = exif.get_ifd(0x8769)
        equivalent = focal_mm or photo_ifd.get(41989) or None
        if equivalent and float(equivalent) <= 0:
            equivalent = None
        profile = opened.info.get("icc_profile")
        image = ImageOps.exif_transpose(opened).convert("RGB")
        if profile:
            try:
                image = ImageCms.profileToProfile(
                    image,
                    ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                    ImageCms.createProfile("sRGB"),
                    outputMode="RGB",
                )
            except (OSError, ValueError):
                pass
        image.load()
    width, height = image.size
    if min(width, height) < 64:
        raise ValueError("The photo is too small to reconstruct (minimum side below 64 pixels).")
    equivalent = float(equivalent or 30)
    focal_px = equivalent * np.hypot(width, height) / np.hypot(36, 24)
    # New image objects exclude inherited EXIF, comments, authors and locations.
    pixels = np.asarray(image)
    Image.fromarray(pixels).save(directory / "input.png")
    preview = Image.fromarray(pixels)
    preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    preview.save(directory / "preview.jpg", quality=94)
    small = image.copy()
    small.thumbnail((768, 768), Image.Resampling.LANCZOS)
    gray = np.asarray(small.convert("L")).astype(float)
    sharpness = float(np.var(ndimage.laplace(gray)))
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    flags = []
    if min(width, height) < 1200:
        flags.append("Limited source resolution: fine detail may soften in the video.")
    if max(width / height, height / width) > 2.5:
        flags.append("Extreme aspect ratio: monocular depth estimation may be less reliable.")
    if sharpness < 8:
        flags.append("The image is smooth or blurred; inspect whether the chosen subject is sharp.")
    report = {
        "input_name": source.name,
        "source_sha256": digest,
        "image_width": width,
        "image_height": height,
        "focal_length_px": float(focal_px),
        "focal_mm_35mm_equivalent": equivalent,
        "focal_source": "override"
        if focal_mm
        else ("EXIF" if photo_ifd.get(41989) else "30 mm fallback"),
        "vertical_fov_degrees": float(np.degrees(2 * np.arctan(height / (2 * focal_px)))),
        "sharpness_laplacian_variance_at_768px": sharpness,
        "image_flags": flags,
    }
    (directory / "image.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
