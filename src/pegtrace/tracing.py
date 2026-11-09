"""Outline handling: user traces, automatic seed detection, orientation."""

from __future__ import annotations

import math

import numpy as np
import shapely
from PIL import Image, ImageFilter
from shapely import affinity
from shapely.geometry import Polygon

from .calibration import Calibration
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


def insert_vertex(verts, p, after: int, snap: float) -> tuple[list, int]:
    """Add vertex ``p`` to the closed polygon ``verts``.

    A click within ``snap`` of an edge splits that edge (refining an outline); any other
    click continues the outline right after vertex ``after`` (drawing). Returns the new
    vertex list and the index of the new vertex.
    """
    verts = [tuple(map(float, v)) for v in verts]
    p = (float(p[0]), float(p[1]))
    n = len(verts)
    idx = n if not (0 <= after < n) else after + 1
    if n >= 2:
        a = np.asarray(verts)
        b = np.roll(a, -1, axis=0)
        if n == 2:
            a, b = a[:1], b[:1]
        ab = b - a
        t = np.clip(((np.asarray(p) - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
        d = np.hypot(*(a + ab * t[:, None] - np.asarray(p)).T)
        i = int(np.argmin(d))
        if d[i] <= snap:
            idx = i + 1
    verts.insert(idx, p)
    return verts, idx


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


def _otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(float)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    mt = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        mu0 = m0 / w0
        mu1 = (mt - m0) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    between = np.nan_to_num(between)
    return float(centers[int(np.argmax(between))])


def autodetect(
    cal: Calibration,
    restrict_to_reference: bool = True,
    blur_mm: float = 0.8,
    work_px: int = 1000,
    min_area_mm2: float = 25.0,
) -> Polygon:
    """Find the object as the largest region that differs from the background.

    Background colour is sampled from a band just inside the reference
    rectangle (paper) when available, otherwise from the image border.
    Returns an empty polygon when nothing plausible is found.
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
    cols = left + (np.arange(nx) + 0.5) / ppm
    rows = top - (np.arange(ny) + 0.5) / ppm
    xx, yy = np.meshgrid(cols, rows)

    region = np.ones((ny, nx), bool)
    if cal.reference is not None and restrict_to_reference:
        rx0, ry0, rx1, ry1 = cal.reference
        inset = 0.02 * max(rx1 - rx0, ry1 - ry0)
        band = 0.06 * max(rx1 - rx0, ry1 - ry0)
        region = (xx > rx0 + inset) & (xx < rx1 - inset) & (yy > ry0 + inset) & (yy < ry1 - inset)
        inner = (xx > rx0 + band) & (xx < rx1 - band) & (yy > ry0 + band) & (yy < ry1 - band)
        sample = arr[region & ~inner]
    else:
        b = max(2, int(0.03 * min(nx, ny)))
        sample = np.concatenate([arr[:b].reshape(-1, 3), arr[-b:].reshape(-1, 3),
                                 arr[:, :b].reshape(-1, 3), arr[:, -b:].reshape(-1, 3)])
    if len(sample) == 0:
        return Polygon()
    bg = np.median(sample, axis=0)
    dist = np.linalg.norm(arr - bg, axis=2)
    dist[~region] = 0.0
    if dist.max() <= 0:
        return Polygon()
    d8 = Image.fromarray(np.clip(dist / dist.max() * 255, 0, 255).astype(np.uint8))
    d8 = d8.filter(ImageFilter.GaussianBlur(max(blur_mm * ppm, 0.5)))
    d = np.asarray(d8, dtype=float)
    vals = d[region]
    thr = _otsu(vals) if vals.size else 128.0
    thr = max(thr, 20.0)  # ignore tiny colour noise on blank paper
    mask = (d > thr) & region
    if not mask.any():
        return Polygon()
    z = np.pad(mask.astype(float), 1)  # pad so contours close
    lines = contour_generator(z=z).lines(0.5)
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
