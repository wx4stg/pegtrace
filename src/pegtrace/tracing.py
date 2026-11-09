"""Outline handling: user traces, automatic seed detection, orientation."""

from __future__ import annotations

import math

import numpy as np
import shapely
from PIL import Image, ImageFilter
from shapely import affinity
from shapely.geometry import Polygon

from .calibration import Calibration, dilate, erode, otsu, value_saturation
from .geom2d import clean, fill_holes, largest_polygon


def polygon_from_xy(xs, ys) -> Polygon:
    """Build a usable outline from traced vertices (fixes self-intersections)."""
    xs = np.asarray(xs, dtype=float).ravel()
    ys = np.asarray(ys, dtype=float).ravel()
    if len(xs) < 3:
        return Polygon()
    return prepare_outline(Polygon(np.column_stack([xs, ys])))


def prepare_outline(poly, simplify_tol: float = 0.0) -> Polygon:
    """Valid, single, hole-free polygon, optionally simplified (tolerance in mm)."""
    p = largest_polygon(fill_holes(clean(poly)))
    if p.is_empty:
        return p
    if simplify_tol > 0:
        p = largest_polygon(clean(shapely.simplify(p, simplify_tol, preserve_topology=True)))
    return shapely.geometry.polygon.orient(p, 1.0)


def merge_close_vertices(poly: Polygon, min_edge: float) -> Polygon:
    """Merge vertices closer than ``min_edge`` (e.g. the 2-3 points a rounded corner
    leaves), so each corner is one point that is easy to grab.

    A short edge is replaced by the point where its neighbouring edges meet, so a
    rounded corner becomes the sharp corner around it. Short edges whose neighbours
    don't meet nearby (the end of a narrow tab) are kept.
    """
    if poly.is_empty or min_edge <= 0:
        return poly
    v = [np.asarray(c, float) for c in np.asarray(poly.exterior.coords)[:-1]]
    keep: set[tuple] = set()  # short edges that can't be merged, by their end points
    while len(v) > 3:
        n = len(v)
        cands = [(float(np.hypot(*(v[(i + 1) % n] - v[i]))), i) for i in range(n)]
        cands = [(d, i) for d, i in cands if d < min_edge
                 and (tuple(v[i]), tuple(v[(i + 1) % n])) not in keep]
        if not cands:
            break
        _, i = min(cands)
        p0, p1, p2, p3 = v[(i - 1) % n], v[i], v[(i + 1) % n], v[(i + 2) % n]
        d1, d2 = p1 - p0, p3 - p2
        den = d1[0] * d2[1] - d1[1] * d2[0]
        x = None
        if abs(den) > 1e-9:
            t = ((p2 - p0)[0] * d2[1] - (p2 - p0)[1] * d2[0]) / den
            x = p0 + t * d1
        if x is None or np.hypot(*(x - (p1 + p2) / 2)) > min_edge:
            keep.add((tuple(p1), tuple(p2)))
            continue
        j = (i + 1) % n
        v = [x if k == i else c for k, c in enumerate(v) if k != j]
    out = Polygon(v)
    if not out.is_valid or abs(out.area - poly.area) > 0.05 * poly.area:
        return poly
    return shapely.geometry.polygon.orient(out, 1.0)


def outline_stats(poly: Polygon) -> dict:
    if poly is None or poly.is_empty:
        return {"width": 0.0, "height": 0.0, "area": 0.0, "vertices": 0}
    x0, y0, x1, y1 = poly.bounds
    return {
        "width": x1 - x0,
        "height": y1 - y0,
        "area": poly.area,
        "vertices": len(poly.exterior.coords) - 1,
    }


_otsu = otsu  # kept for callers of the old name


def _grid_smooth(values: np.ndarray, region: tuple[int, int, int, int], cell: int, q: float,
                 valid: np.ndarray | None = None) -> np.ndarray:
    """A smooth map of the ``q``-th percentile of ``values`` over ``cell``-sized blocks of
    ``region`` (r0, r1, c0, c1), using only ``valid`` pixels (the paper). Blocks with too
    few of them are filled from their neighbours; then a 3x3 median and interpolation back
    to full size. Zero outside the region."""
    r0, r1, c0, c1 = region
    gy, gx = max((r1 - r0) // cell, 1), max((c1 - c0) // cell, 1)
    rs = np.linspace(r0, r1, gy + 1).astype(int)
    cs = np.linspace(c0, c1, gx + 1).astype(int)
    g = np.full((gy, gx), np.nan)
    for i in range(gy):
        for j in range(gx):
            blk = values[rs[i]:rs[i + 1], cs[j]:cs[j + 1]]
            if valid is not None:
                blk = blk[valid[rs[i]:rs[i + 1], cs[j]:cs[j + 1]]]
            if blk.size >= 0.15 * (rs[i + 1] - rs[i]) * (cs[j + 1] - cs[j]):
                g[i, j] = np.percentile(blk, q)
    if np.isnan(g).all():
        g[:] = np.percentile(values[r0:r1, c0:c1], q)
    while np.isnan(g).any():  # fill from neighbours, growing inwards
        p = np.pad(g, 1, constant_values=np.nan)
        nb = np.stack([p[i:i + gy, j:j + gx] for i in range(3) for j in range(3)])
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            fill = np.nanmean(nb, axis=0)
        g = np.where(np.isnan(g), fill, g)
    p = np.pad(g, 1, mode="edge")
    g = np.median(np.stack([p[i:i + gy, j:j + gx] for i in range(3) for j in range(3)]), axis=0)
    im = Image.fromarray(g.astype(np.float32), mode="F").resize((c1 - c0, r1 - r0), Image.Resampling.BILINEAR)
    out = np.zeros(values.shape, np.float32)
    out[r0:r1, c0:c1] = np.asarray(im)
    return out


def _object_score(v, sat, region, ppm, valid=None, cell_mm=12.0):
    """How much each pixel stands out from the paper around it (>= 1: clearly)."""
    cell = max(int(cell_mm * ppm), 4)
    paper_v = _grid_smooth(v, region, cell, 90, valid)
    paper_s = _grid_smooth(sat, region, cell, 20, valid)
    return np.maximum((1 - v / np.maximum(paper_v, 1)) / 0.35, (sat - paper_s) / 0.25)


def autodetect(
    cal: Calibration,
    restrict_to_reference: bool = True,
    blur_mm: float = 0.8,
    work_px: int = 1000,
    min_area_mm2: float = 25.0,
    threshold: float = 0.7,
    close_mm: float = 1.5,
) -> Polygon:
    """Find the object as the largest region that stands out from the paper around it.

    Inside the reference rectangle (paper) when there is one, otherwise in the whole image.
    The paper's brightness and saturation are estimated locally on a coarse grid, so a shadow
    across the paper is not mistaken for the object. A pixel belongs to the object when it is
    much darker than the paper nearby (by 35 % at a score of 1) or much more saturated (by
    0.25), and ``threshold`` is the score that counts. Returns an empty polygon when nothing
    plausible is found.
    """
    from contourpy import contour_generator

    img = cal.image.convert("RGB")
    k = min(1.0, work_px / max(img.size))
    if k < 1.0:
        img = img.resize((max(int(img.size[0] * k), 1), max(int(img.size[1] * k), 1)), Image.Resampling.BILINEAR)
    ppm = cal.px_per_mm * img.size[0] / cal.image.size[0]
    arr = np.asarray(img, dtype=float)
    ny, nx = arr.shape[:2]
    left, _, _, top = cal.bounds

    if cal.reference is not None and restrict_to_reference:
        rx0, ry0, rx1, ry1 = cal.reference
        inset = 0.02 * max(rx1 - rx0, ry1 - ry0)
        c0, c1 = int((rx0 + inset - left) * ppm), int(np.ceil((rx1 - inset - left) * ppm))
        r0, r1 = int((top - (ry1 - inset)) * ppm), int(np.ceil((top - (ry0 + inset)) * ppm))
        box_ = (max(r0, 0), min(r1, ny), max(c0, 0), min(c1, nx))
    else:
        box_ = (0, ny, 0, nx)
    r0, r1, c0, c1 = box_
    if r1 - r0 < 4 or c1 - c0 < 4:
        return Polygon()
    region = np.zeros((ny, nx), bool)
    region[r0:r1, c0:c1] = True

    v, sat = value_saturation(arr)
    # two passes: big cells find the obvious object, then small cells model the paper
    # (and its shadows) from the rest, so a wide object doesn't become its own "paper"
    rough = dilate(_object_score(v, sat, box_, ppm, cell_mm=40.0) > 1.0, max(int(ppm), 1))
    score = _object_score(v, sat, box_, ppm, valid=~rough)
    score[~region] = 0.0
    s8 = Image.fromarray(np.clip(score * 128, 0, 255).astype(np.uint8))
    s8 = s8.filter(ImageFilter.GaussianBlur(max(blur_mm * ppm, 0.5)))
    rc = max(int(close_mm * ppm / 2), 1)
    mask = erode(dilate((np.asarray(s8) > threshold * 128) & region, rc), rc)  # join shiny gaps
    if not mask.any():
        return Polygon()
    lines = contour_generator(z=np.pad(mask.astype(float), 1)).lines(0.5)  # pad so contours close
    best = Polygon()
    for line in lines:
        if len(line) < 4:
            continue
        c = line - 1.0  # undo padding; (col, row) index coords
        pts = np.column_stack([left + (c[:, 0] + 0.5) / ppm, top - (c[:, 1] + 0.5) / ppm])
        p = largest_polygon(clean(Polygon(pts)))
        if p.area > best.area:
            best = p
    if best.area < min_area_mm2:
        return Polygon()
    p = prepare_outline(best, simplify_tol=0.5 / max(ppm, 1e-6) + 0.2)
    return merge_close_vertices(p, min(6.0, 0.04 * math.hypot(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1])))


# ----------------------------------------------------------------- orientation
def orient_polygon(poly: Polygon, down_angle_deg: float) -> Polygon:
    """Rotate so the chosen direction points to -y; centre x on 0, bottom on y=0.

    ``down_angle_deg`` is the photo direction (mm frame, CCW from +x) that
    should become "down": 270 means the photo's own down stays down.
    """
    if poly.is_empty:
        return poly
    p = affinity.rotate(poly, 270.0 - down_angle_deg, origin="centroid")
    x0, y0, x1, _ = p.bounds
    return affinity.translate(p, -(x0 + x1) / 2, -y0)


def auto_down_angle(poly: Polygon) -> float:
    """Down direction that makes the long axis vertical, heavier end down."""
    if poly.is_empty:
        return 270.0
    mrr = poly.minimum_rotated_rectangle
    c = np.asarray(mrr.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    long_e = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    a = math.degrees(math.atan2(long_e[1], long_e[0])) % 360.0
    best, best_score = a, None
    for cand in (a % 360.0, (a + 180.0) % 360.0):
        p = orient_polygon(poly, cand)
        _, y0, _, y1 = p.bounds
        score = (p.centroid.y - y0) / max(y1 - y0, 1e-9)  # lower centroid is better
        if best_score is None or score < best_score:
            best, best_score = cand, score
    return round(best, 1)
