"""Synthetic sample photo: a hammer-like tool on US Letter paper, in perspective.

Used by the tests and by ``scripts/make_sample.py``.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from shapely import affinity
from shapely.geometry import box

from .calibration import homography

PAPER = (215.9, 279.4)  # portrait US Letter
PHOTO_SIZE = (1600, 1200)
CORNERS_PX = [(430, 170), (1140, 215), (1265, 1060), (330, 1015)]  # TL, TR, BR, BL


def object_outline():
    """A hammer-like tool: long handle with a wide head, rounded corners."""
    handle = box(-11, -75, 11, 60)
    head = box(-45, 52, 45, 80)
    shape = handle.union(head).buffer(4, join_style="round").buffer(-2)
    shape = affinity.rotate(shape, 18, origin=(0, 0))
    return affinity.translate(shape, PAPER[0] / 2, PAPER[1] / 2)


def make_photo(seed: int = 1) -> tuple[Image.Image, dict]:
    """Return (photo, truth) where truth has paper size, corners and outline."""
    rng = np.random.default_rng(seed)
    w, h = PAPER
    ppm = 3.0
    x0, y0, x1, y1 = -120.0, -120.0, w + 120.0, h + 120.0
    cw, ch = int((x1 - x0) * ppm), int((y1 - y0) * ppm)

    def to_canvas(pts):
        return [((x - x0) * ppm, (y1 - y) * ppm) for x, y in pts]

    base = np.zeros((ch, cw, 3), float)
    base[:] = (150, 112, 74)
    stripes = 12 * np.sin(np.linspace(0, 60, cw))[None, :, None]
    canvas = Image.fromarray(np.clip(base + stripes + rng.normal(0, 6, base.shape), 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    draw.polygon(to_canvas([(0, 0), (w, 0), (w, h), (0, h)]), fill=(244, 243, 238))
    obj = object_outline()
    shadow = affinity.translate(obj, 2.0, -2.0)
    draw.polygon(to_canvas(shadow.exterior.coords), fill=(205, 204, 200))
    draw.polygon(to_canvas(obj.exterior.coords), fill=(52, 64, 92))

    hmat = homography(CORNERS_PX, [(0, h), (w, h), (w, 0), (0, 0)])
    a_inv = np.array([[ppm, 0, -x0 * ppm], [0, -ppm, y1 * ppm], [0, 0, 1]])
    m = a_inv @ hmat
    m /= m[2, 2]
    photo = canvas.transform(PHOTO_SIZE, Image.Transform.PERSPECTIVE, tuple(m.flatten()[:8]),
                             Image.Resampling.BICUBIC)
    arr = np.asarray(photo.filter(ImageFilter.GaussianBlur(0.8)), float)
    grad = np.linspace(-12, 10, PHOTO_SIZE[0])[None, :, None]  # uneven lighting
    arr = np.clip(arr + grad + rng.normal(0, 3, arr.shape), 0, 255).astype(np.uint8)
    truth = {
        "paper_mm": list(PAPER),
        "corners_px": [list(c) for c in CORNERS_PX],
        "object_mm": [list(map(float, p)) for p in obj.exterior.coords],
        "object_area_mm2": obj.area,
    }
    return Image.fromarray(arr), truth
