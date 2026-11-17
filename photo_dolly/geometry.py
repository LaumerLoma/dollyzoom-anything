"""Anchor calibration, suitability estimates, and conservative 3D cleanup."""

from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial.transform import Rotation
from plyfile import PlyData, PlyElement

SH0 = 0.28209479177387814


def weighted_quantile(values, weights, q):
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    return float(np.interp(q, (np.cumsum(weights) - 0.5 * weights) / weights.sum(), values))


class Scene:
    def __init__(self, path, meta):
        self.path, self.meta = Path(path), meta
        self.vertices = PlyData.read(path)["vertex"].data
        self.xyz = np.column_stack([self.vertices[k] for k in ("x", "y", "z")]).astype(np.float64)
        if not np.isfinite(self.xyz).all() or (self.xyz[:, 2] <= 0).any():
            raise ValueError("The scene contains invalid or behind-camera positions.")
        self.alpha = 1 / (1 + np.exp(-np.clip(self.vertices["opacity"], -30, 30)))
        self.uv = (
            self.xyz[:, :2]
            / self.xyz[:, 2, None]
            * meta["focal_length_px"]
            / np.array([meta["image_width"], meta["image_height"]])
            + 0.5
        )
        self.side = int(np.sqrt(len(self.vertices) // 2))
        self.gridded = self.side**2 * 2 == len(self.vertices)

    def anchor(self, uv):
        uv = np.asarray(uv, dtype=float)
        if uv.shape != (2,) or not ((uv >= 0) & (uv <= 1)).all():
            raise ValueError(
                "Anchor coordinates must be two numbers in [0,1], measured from the oriented photo’s top left."
            )
        distance2 = ((self.uv - uv) ** 2).sum(1)
        eligible = (self.alpha > 0.35) & (distance2 < 0.008**2)
        indices = np.flatnonzero(eligible)
        if len(indices) < 12:
            indices = np.argpartition(distance2 + (self.alpha < 0.35) * 100, 64)[:64]
        depths = self.xyz[indices, 2]
        weights = self.alpha[indices] * np.exp(-distance2[indices] / (0.004**2)) + 1e-12
        front = weighted_quantile(depths, weights, 0.25)
        support = depths < front * 1.4
        depth = weighted_quantile(depths[support], weights[support], 0.5)
        lo = weighted_quantile(depths[support], weights[support], 0.1)
        hi = weighted_quantile(depths[support], weights[support], 0.9)
        return {
            "uv": uv.tolist(),
            "depth": depth,
            "world": [
                float(
                    (uv[0] - 0.5) * self.meta["image_width"] / self.meta["focal_length_px"] * depth
                ),
                float(
                    -(uv[1] - 0.5)
                    * self.meta["image_height"]
                    / self.meta["focal_length_px"]
                    * depth
                ),
                -depth,
            ],
            "local_depth_spread_fraction": (hi - lo) / depth,
            "other_depth_layer_weight_fraction": float(
                weights[depths > depth * 1.8].sum() / weights.sum()
            ),
            "samples": int(support.sum()),
            "depth_quantiles": [lo, depth, hi],
        }

    def assess(self, uv, strength=1.25, crop=1.15, crop_mode="center"):
        anchor = self.anchor(uv)
        valid = self.alpha > 0.5
        z = self.xyz[valid, 2]
        weights = self.alpha[valid]
        near = weighted_quantile(z, weights, 0.02)
        near = min(near, anchor["depth"])
        far = weighted_quantile(z, weights, 0.85)
        low = weighted_quantile(z, weights, 0.1)
        high = weighted_quantile(z, weights, 0.9)
        distance = anchor["depth"] * (strength - 1)
        background_growth = strength * far / (far + distance)
        nearest_scale = strength * near / (near + distance)
        spread = anchor["local_depth_spread_fraction"]
        reasons = []
        cautions = list(self.meta.get("image_flags", []))
        rating = "highly suitable"
        # Small but valid foreground subjects can occupy less than 10% of rays.
        # Include the chosen anchor and near quantile rather than calling that flat.
        variation = (high - min(low, near, anchor["depth"])) / max(high, 1e-8)
        if variation < 0.04 or background_growth < 1.01:
            rating = "unsuitable"
            reasons.append(
                "Predicted depth is almost flat relative to this anchor; the move would resemble an ordinary zoom."
            )
        elif nearest_scale < 0.3:
            rating = "unsuitable"
            reasons.append(
                "This anchor is far behind nearby objects; the requested move exposes too much unobserved background."
            )
        elif background_growth < 1.04 or nearest_scale < 0.55 or spread > 0.4:
            rating = "weak"
            reasons.append(
                "The requested anchor or move has limited useful depth contrast or unstable nearby geometry."
            )
        elif (
            background_growth < 1.10
            or nearest_scale < 0.75
            or spread > 0.16
            or min(self.meta["image_width"], self.meta["image_height"]) < 1200
        ):
            rating = "workable"
            reasons.append("There is useful depth, but a restrained move is preferable.")
        else:
            reasons.append(
                "The chosen anchor is well separated from the background and has locally consistent depth."
            )
        if spread > 0.16:
            cautions.append(
                "Depth varies around the anchor. Choose a point inside a solid surface for a steadier lock."
            )
        if anchor["other_depth_layer_weight_fraction"] > 0.35:
            cautions.append(
                "The predicted layers disagree near the selected point; inspect its silhouette in the preview."
            )
        framed = 0.5 + (np.asarray(uv) - 0.5) * crop
        if crop_mode == "center" and ((framed < 0.04) | (framed > 0.96)).any():
            cautions.append(
                "A centered crop puts the anchor near an edge. Use --crop-mode anchor or a smaller crop."
            )
        if self.meta.get("focal_source") == "30 mm fallback":
            cautions.append(
                "No 35 mm equivalent focal length was available; 30 mm was assumed. Override --focal-mm if known."
            )
        if min(self.meta["image_width"], self.meta["image_height"]) < 256:
            rating = "unsuitable"
            cautions.append("The source is too small for a detailed result.")
        if (
            self.meta.get("sharpness_laplacian_variance_at_768px", 100) < 4
            and rating == "highly suitable"
        ):
            rating = "workable"
        max_safe = 1.6
        if anchor["depth"] * 0.75 > near:
            max_safe = min(
                max_safe, 0.75 * (anchor["depth"] - near) / (0.75 * anchor["depth"] - near)
            )
        foreground_threshold = anchor["depth"] * 2.2
        if self.gridded:
            foreground = (
                self.xyz[:, 2].reshape(2, self.side, self.side)
                < min(foreground_threshold, near * 2.2)
            ).any(0)
            if (
                0.003 < foreground.mean() < 0.45
                and max(
                    foreground[0].mean(),
                    foreground[-1].mean(),
                    foreground[:, 0].mean(),
                    foreground[:, -1].mean(),
                )
                > 0.02
            ):
                cautions.append(
                    "The foreground reaches a photo boundary. Reconstructed edges may need tighter framing in the preview."
                )
        return {
            "rating": rating,
            "anchor": anchor,
            "reasons": reasons,
            "cautions": cautions,
            "predicted_background_growth_factor": float(background_growth),
            "near_foreground_scale_factor": float(nearest_scale),
            "depth_near": near,
            "depth_far": far,
            "depth_variation_fraction": float(variation),
            "suggested_max_strength": float(max(1.01, max_safe)),
            "foreground_threshold": foreground_threshold,
            "basis": "Image properties and predicted-depth heuristics, not a calibrated probability or a measured 3D scan.",
            "visual_review_note": "Transparency, reflections and incorrect inferred geometry still need visual inspection.",
        }


def polish(scene, image_path, target, assessment, mode="auto"):
    original = scene.vertices
    data = original.copy()
    xyz = scene.xyz
    if mode == "off":
        PlyData([PlyElement.describe(data, "vertex")], text=False, byte_order="<").write(target)
        return {"mode": "off", "gaussian_count": len(data), "background_completion": False}
    threshold = assessment["foreground_threshold"]
    selected = np.flatnonzero(xyz[:, 2] < threshold)
    # Avoid treating an entire landscape as one foreground object.
    if len(selected) > len(data) * 0.45:
        selected = np.flatnonzero(xyz[:, 2] < assessment["depth_near"] * 1.5)
    if len(selected):
        points = xyz[selected]
        q = np.column_stack([data[f"rot_{i}"][selected] for i in range(4)])
        rot = Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_matrix()
        scales = np.exp(
            np.column_stack([data[f"scale_{i}"][selected] for i in range(3)]).astype(float)
        )
        cov = (rot * scales[:, None, :] ** 2) @ rot.transpose(0, 2, 1)
        ray = points / np.linalg.norm(points, axis=1, keepdims=True)
        transform = np.eye(3)[None] - 0.82 * ray[:, :, None] * ray[:, None, :]
        refined = transform @ cov @ transform.transpose(0, 2, 1)
        eigen, axes = np.linalg.eigh(refined)
        if eigen.min() <= 0:
            raise ValueError("Covariance refinement became non-positive.")
        axes[np.linalg.det(axes) < 0, :, 0] *= -1
        quat = Rotation.from_matrix(axes).as_quat()[:, [3, 0, 1, 2]]
        for i in range(3):
            data[f"scale_{i}"][selected] = np.log(np.sqrt(eigen[:, i]))
        for i in range(4):
            data[f"rot_{i}"][selected] = quat[:, i]
    image = np.asarray(Image.open(image_path).convert("RGB")).astype(np.float32) / 255
    height, width = image.shape[:2]
    u, v = scene.uv.T
    visible_count = 0
    extra_count = 0
    ghost_count = 0
    fill_reason = "Conservative geometry/color cleanup only."
    if scene.gridded:
        side = scene.side
        zgrid = xyz[:, 2].reshape(2, -1)
        nearest = zgrid.argmin(0) * side**2 + np.arange(side**2)
        visible = nearest[
            (scene.alpha[nearest] > 0.95)
            & (u[nearest] >= 0)
            & (u[nearest] <= 1)
            & (v[nearest] >= 0)
            & (v[nearest] <= 1)
        ]
        sampled = np.column_stack(
            [
                ndimage.map_coordinates(
                    image[..., c],
                    [v[visible] * height - 0.5, u[visible] * width - 0.5],
                    order=1,
                    mode="nearest",
                )
                for c in range(3)
            ]
        )
        rgb = np.column_stack([data[f"f_dc_{c}"][visible] for c in range(3)]) * SH0 + 0.5
        for c in range(3):
            data[f"f_dc_{c}"][visible] = (0.8 * rgb[:, c] + 0.2 * sampled[:, c] - 0.5) / SH0
        visible_count = len(visible)
        foreground = (xyz[:, 2].reshape(2, side, side) < threshold).any(0)
        footprint = ndimage.binary_dilation(
            ndimage.binary_closing(foreground, iterations=2), iterations=max(2, round(side / 96))
        )
        small = (
            np.asarray(
                Image.fromarray((image * 255).astype(np.uint8)).resize(
                    (side, side), Image.Resampling.LANCZOS
                )
            ).astype(float)
            / 255
        )
        ring = ndimage.binary_dilation(footprint, iterations=5) & ~footprint
        texture = (
            float(np.median(np.abs(ndimage.laplace(small.mean(2)))[ring])) if ring.any() else 1
        )
        ratio = assessment["depth_far"] / max(threshold, 1e-6)
        allow_fill = mode == "fill" or (
            mode == "auto" and 0.003 < footprint.mean() < 0.35 and ratio > 2 and texture < 0.035
        )
        if allow_fill:
            far_threshold = threshold * 1.3
            depth_reference = xyz[:, 2].reshape(2, side, side).max(0)
            # Restrict completion to rows with enough adjacent observed background.
            known = (~footprint) & (depth_reference > far_threshold)
            safe_rows = known.sum(1) > max(8, side * 0.05)
            footprint[~safe_rows] = False
            filled = small.copy()
            filled_depth = depth_reference.copy()
            columns = np.arange(side)
            for row in np.flatnonzero(footprint.any(1)):
                for channel in range(3):
                    filled[row, :, channel] = np.interp(
                        columns, columns[known[row]], small[row, known[row], channel]
                    )
                filled_depth[row] = np.interp(
                    columns, columns[known[row]], depth_reference[row, known[row]]
                )
            filled = ndimage.gaussian_filter(filled, sigma=(1.2, 1.2, 0))
            filled_depth = ndimage.gaussian_filter(filled_depth, sigma=2)
            ix = np.clip((u * side).astype(int), 0, side - 1)
            iy = np.clip((v * side).astype(int), 0, side - 1)
            ghosts = (
                (xyz[:, 2] > far_threshold)
                & (u >= 0)
                & (u < 1)
                & (v >= 0)
                & (v < 1)
                & footprint[iy, ix]
            )
            for c in range(3):
                data[f"f_dc_{c}"][ghosts] = (filled[iy[ghosts], ix[ghosts], c] - 0.5) / SH0
            by, bx = np.where(footprint)
            bz = filled_depth[by, bx]
            bu, bv = (bx + 0.5) / side, (by + 0.5) / side
            extra = np.zeros(len(bx), dtype=data.dtype)
            extra["x"] = (bu - 0.5) * width / scene.meta["focal_length_px"] * bz
            extra["y"] = (bv - 0.5) * height / scene.meta["focal_length_px"] * bz
            extra["z"] = bz
            extra["scale_0"] = np.log(bz * width / (scene.meta["focal_length_px"] * side) * 0.68)
            extra["scale_1"] = np.log(bz * height / (scene.meta["focal_length_px"] * side) * 0.68)
            extra["scale_2"] = np.log(bz * 0.0002)
            extra["rot_0"] = 1
            extra["opacity"] = np.log(0.98 / 0.02)
            for c in range(3):
                extra[f"f_dc_{c}"] = (filled[by, bx, c] - 0.5) / SH0
            data = np.concatenate([data, extra])
            extra_count = len(extra)
            ghost_count = int(ghosts.sum())
            fill_reason = "Estimated smooth continuation of adjacent observed colors/depths behind an isolated foreground; not newly observed geometry."
        else:
            fill_reason = "Background completion skipped: insufficient isolation, large foreground, or textured surroundings."
    PlyData([PlyElement.describe(data, "vertex")], text=False, byte_order="<").write(target)
    saved = PlyData.read(target)["vertex"].data
    for key in ("x", "y", "z"):
        assert np.array_equal(saved[key][: len(original)], original[key])
    for key in ("x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"):
        assert np.isfinite(saved[key]).all()
    return {
        "mode": mode,
        "gaussian_count": len(data),
        "original_gaussian_count": len(original),
        "depth_gaussians_refined": len(selected),
        "visible_colors_refined": visible_count,
        "background_ghosts_recolored": ghost_count,
        "background_gaussians_added": extra_count,
        "background_completion": extra_count > 0,
        "background_note": fill_reason,
        "original_positions_unchanged": True,
        "representation": "Full-rank anisotropic 3D Gaussians",
    }
