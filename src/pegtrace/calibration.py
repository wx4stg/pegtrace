"""Scale / perspective calibration from a reference object in the photo.

Pixel coordinates are (u, v) with v pointing down (PIL convention). Millimetre
coordinates are (x, y) with y pointing up.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image


def homography(src, dst) -> np.ndarray:
    """3x3 homography H with dst ~ H @ src (normalised DLT, >= 4 points)."""
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != dst.shape or src.shape[0] < 4:
        raise ValueError("need at least 4 matching point pairs")

    def norm(p):
        c = p.mean(axis=0)
        s = np.sqrt(2) / max(np.mean(np.linalg.norm(p - c, axis=1)), 1e-12)
        return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])

    ts, td = norm(src), norm(dst)
    sp = apply_h(ts, src)
    dp = apply_h(td, dst)
    rows = []
    for (x, y), (u, v) in zip(sp, dp):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    hn = vt[-1].reshape(3, 3)
    h = np.linalg.inv(td) @ hn @ ts
    return h / h[2, 2]


def apply_h(h: np.ndarray, pts) -> np.ndarray:
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    ph = np.column_stack([pts, np.ones(len(pts))]) @ h.T
    return ph[:, :2] / ph[:, 2:3]


def order_corners(pts) -> np.ndarray:
    """Order 4 image points clockwise on screen, starting nearest the top-left."""
    pts = np.asarray(pts, dtype=float)
    if pts.shape != (4, 2):
        raise ValueError("need exactly 4 corner points")
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])  # v down -> clockwise on screen
    ordered = pts[np.argsort(ang)]
    start = int(np.argmin(ordered.sum(axis=1)))  # smallest u+v ~ top-left
    return np.roll(ordered, -start, axis=0)


@dataclass
class Calibration:
    """Result of calibration: an image whose pixels map linearly to mm."""

    method: str
    image: Image.Image  # rectified (rectangle) or original (two-point) image
    bounds: tuple[float, float, float, float]  # (left, bottom, right, top) in mm
    px_per_mm: float
    h_px_to_mm: np.ndarray  # maps ORIGINAL photo pixels to mm
    reference: tuple[float, float, float, float] | None = None  # paper rect in mm
    notes: list[str] = field(default_factory=list)

    def px_to_mm(self, pts) -> np.ndarray:
        return apply_h(self.h_px_to_mm, pts)

    def image_array(self) -> np.ndarray:
        return np.asarray(self.image.convert("RGB"))

    def grid_to_mm(self, cols, rows) -> np.ndarray:
        """Calibrated-image pixel (col, row) centres -> mm."""
        left, _, _, top = self.bounds
        cols = np.asarray(cols, dtype=float)
        rows = np.asarray(rows, dtype=float)
        return np.column_stack([left + (cols + 0.5) / self.px_per_mm, top - (rows + 0.5) / self.px_per_mm])


def rectify_rectangle(
    img: Image.Image,
    corners_px,
    size_mm: tuple[float, float],
    px_per_mm: float = 4.0,
    margin_frac: float = 0.35,
    max_px: int = 4000,
) -> Calibration:
    """Perspective-correct ``img`` using the 4 corners of a known rectangle.

    ``size_mm`` may be given in either order; the longer side is matched to the
    longer side seen in the photo.
    """
    c = order_corners(corners_px)  # TL, TR, BR, BL on screen
    horiz = (np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[3])) / 2
    vert = (np.linalg.norm(c[3] - c[0]) + np.linalg.norm(c[2] - c[1])) / 2
    lo, hi = sorted(map(float, size_mm))
    w, h = (hi, lo) if horiz >= vert else (lo, hi)
    dst = np.array([[0, h], [w, h], [w, 0], [0, 0]], dtype=float)
    hmat = homography(c, dst)

    # output extent: reference rect plus margin, limited to the photo's footprint
    m = margin_frac * max(w, h)
    x0, y0, x1, y1 = -m, -m, w + m, h + m
    iw, ih = img.size
    img_corners = np.array([[0, 0], [iw, 0], [iw, ih], [0, ih]], dtype=float)
    ph = np.column_stack([img_corners, np.ones(4)]) @ hmat.T
    if np.all(ph[:, 2] > 0):  # whole photo is in front of the camera horizon
        fp = ph[:, :2] / ph[:, 2:3]
        x0, y0 = max(x0, fp[:, 0].min()), max(y0, fp[:, 1].min())
        x1, y1 = min(x1, fp[:, 0].max()), min(y1, fp[:, 1].max())
    notes = []
    ppm = float(px_per_mm)
    if max(x1 - x0, y1 - y0) * ppm > max_px:
        ppm = max_px / max(x1 - x0, y1 - y0)
        notes.append(f"resolution reduced to {ppm:.2f} px/mm to fit {max_px} px")
    nx = max(int(round((x1 - x0) * ppm)), 1)
    ny = max(int(round((y1 - y0) * ppm)), 1)
    x1 = x0 + nx / ppm
    y0 = y1 - ny / ppm

    # output pixel (u, v) -> mm -> source pixel
    a = np.array([[1 / ppm, 0, x0], [0, -1 / ppm, y1], [0, 0, 1]])
    mtx = np.linalg.inv(hmat) @ a
    mtx = mtx / mtx[2, 2]
    out = img.convert("RGB").transform(
        (nx, ny), Image.Transform.PERSPECTIVE, tuple(mtx.flatten()[:8]), Image.Resampling.BICUBIC,
        fillcolor=(128, 128, 128),
    )
    return Calibration(
        method="rectangle",
        image=out,
        bounds=(x0, y0, x1, y1),
        px_per_mm=ppm,
        h_px_to_mm=hmat,
        reference=(0.0, 0.0, w, h),
        notes=notes,
    )


def scale_two_points(img: Image.Image, p1, p2, distance_mm: float, max_px: int = 4000) -> Calibration:
    """Uniform scale from two points a known distance apart (no perspective fix)."""
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    d_px = float(np.linalg.norm(p2 - p1))
    if d_px <= 0 or distance_mm <= 0:
        raise ValueError("points must be distinct and distance positive")
    s = distance_mm / d_px  # mm per original px
    iw, ih = img.size
    out = img.convert("RGB")
    if max(iw, ih) > max_px:
        k = max_px / max(iw, ih)
        out = out.resize((max(int(iw * k), 1), max(int(ih * k), 1)), Image.Resampling.LANCZOS)
    ppm = out.size[0] / (iw * s)
    hmat = np.array([[s, 0, 0], [0, -s, ih * s], [0, 0, 1]])
    return Calibration(
        method="two-point",
        image=out,
        bounds=(0.0, 0.0, iw * s, ih * s),
        px_per_mm=ppm,
        h_px_to_mm=hmat,
        notes=["two-point scale assumes the camera looked straight down"],
    )
