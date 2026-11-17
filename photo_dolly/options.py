"""Render settings and validation without loading the scientific runtime."""

import math

DEFAULTS = {
    "strength": 1.25,
    "crop": 1.15,
    "crop_mode": "center",
    "half_seconds": 2.0,
    "fps": 60,
    "long_edge": 1080,
    "supersample": 1.5,
    "polish": "auto",
    "motion": "bounce",
    "easing": "smooth",
    "bpm": None,
    "beats": 1,
    "clip_seconds": None,
}
TIKTOK = {"half_seconds": 1.0, "easing": "bouncy"}
LIMITS = {
    "strength": (1.001, 3),
    "crop": (1, 2),
    "half_seconds": (0.2, 30),
    "fps": (1, 120),
    "long_edge": (128, 3840),
    "supersample": (1, 2),
    "bpm": (20, 400),
    "beats": (0.25, 16),
    "clip_seconds": (0.2, 120),
}
CHOICES = {
    "crop_mode": ("center", "anchor"),
    "polish": ("off", "conservative", "auto", "fill"),
    "motion": ("bounce", "forward"),
    "easing": ("smooth", "bouncy"),
}


def validate_options(options):
    for key, (low, high) in LIMITS.items():
        value = options[key]
        if value is None and key in ("bpm", "clip_seconds"):
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"{key} must be a finite number between {low} and {high}.")
        if key in ("fps", "long_edge"):
            if value != int(value):
                raise ValueError(f"{key} must be an integer.")
            options[key] = int(value)
    for key, choices in CHOICES.items():
        if options[key] not in choices:
            raise ValueError(f"{key} must be one of: " + ", ".join(choices))
    if options["bpm"]:
        options["half_seconds"] = 60 / options["bpm"] * options["beats"]
        if not 0.2 <= options["half_seconds"] <= 30:
            raise ValueError(
                "The BPM/beats combination must produce a leg between 0.2 and 30 seconds."
            )
    if options["clip_seconds"] is not None and options["motion"] != "bounce":
        raise ValueError("clip_seconds requires bounce motion; forward exports exactly one leg.")
    return options
