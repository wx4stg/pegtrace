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


def otsu(values: np.ndarray) -> float:
    """Otsu's threshold: the split of ``values`` with the largest between-class variance."""
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(float)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = np.nan_to_num(w0 * w1 * (m0 / w0 - (m0[-1] - m0) / w1) ** 2)
    return float(centers[int(np.argmax(between))])


def _window_any(m: np.ndarray, r: int, axis: int) -> np.ndarray:
    """True where any pixel within ``r`` along ``axis`` is True (a 1-D box dilation)."""
    c = np.cumsum(np.pad(m.astype(np.int32), [(r + 1, r) if a == axis else (0, 0) for a in range(2)]), axis=axis)
    n = m.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) > 0


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a (2r+1)-square, in linear time (Pillow's MaxFilter is quadratic)."""
    return _window_any(_window_any(m, r, 0), r, 1) if r > 0 else m


def erode(m: np.ndarray, r: int) -> np.ndarray:
    return ~dilate(~m, r)


def value_saturation(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """HSV value (0-255) and saturation (0-1) of an RGB float array."""
    v = arr.max(axis=2)
    return v, (v - arr.min(axis=2)) / np.maximum(v, 1.0)


def _reduce_to_quad(pts: np.ndarray) -> np.ndarray:
    """The 4 vertices of a convex polygon that keep the most area (Visvalingam-style)."""
    pts = [tuple(p) for p in pts]
    while len(pts) > 4:
        n = len(pts)
        areas = []
        for i in range(n):
            (ax, ay), (bx, by), (cx, cy) = pts[i - 1], pts[i], pts[(i + 1) % n]
            areas.append(abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)))
        del pts[int(np.argmin(areas))]
    return np.asarray(pts, float)


def _fit_line(pts: np.ndarray):
    """Total least squares line through ``pts``: (point, unit direction)."""
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c)
    return c, vt[0]


def _intersect(l1, l2):
    (p, d), (q, e) = l1, l2
    m = np.array([d, -e]).T
    if abs(np.linalg.det(m)) < 1e-9:
        return None
    t = np.linalg.solve(m, q - p)
    return p + t[0] * d


def _quad_from_lines(lines) -> np.ndarray | None:
    corners = [_intersect(lines[i - 1], lines[i]) for i in range(4)]
    return None if any(c is None for c in corners) else np.asarray(corners)


def _fit_sides(quad: np.ndarray, boundary: np.ndarray, tol: float) -> np.ndarray:
    """Refit each side of ``quad`` to the ``boundary`` points near it (middle 80 % of the
    side, away from the corners, where the hull shortcut runs) and intersect them."""
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        d = b - a
        length = np.linalg.norm(d)
        if length < 1e-9:
            return quad
        d = d / length
        rel = boundary - a
        t = rel @ d
        dist = np.abs(rel @ np.array([-d[1], d[0]]))
        sel = boundary[(t > 0.1 * length) & (t < 0.9 * length) & (dist < tol)]
        lines.append(_fit_line(sel) if len(sel) >= 5 else (a, d))
    # lines[i] is the side from corner i to i+1, so corner i is where sides i-1 and i meet
    q = _quad_from_lines(lines)
    return quad if q is None else q


def _snap_sides(quad: np.ndarray, field: np.ndarray, reach: float, step: float = 2.0) -> np.ndarray:
    """Move each side of ``quad`` (pixel coords of ``field``) onto the strongest edge of
    ``field`` within ``reach`` px along its normal, by a robust line fit to those edge points."""
    gy, gx = np.gradient(field)
    h, w = field.shape
    offs = np.arange(-reach, reach + 0.5, 0.5)
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        d = b - a
        length = np.linalg.norm(d)
        d = d / max(length, 1e-9)
        nrm = np.array([-d[1], d[0]])
        found = []
        for t in np.arange(0.1 * length, 0.9 * length, step):
            p = a + t * d
            xs = np.clip(np.round(p[0] + offs * nrm[0]).astype(int), 0, w - 1)
            ys = np.clip(np.round(p[1] + offs * nrm[1]).astype(int), 0, h - 1)
            g = np.abs(gx[ys, xs] * nrm[0] + gy[ys, xs] * nrm[1])
            k = int(np.argmax(g))
            if g[k] > 0:
                found.append(p + offs[k] * nrm)
        if len(found) < 5:
            lines.append((a, d))
            continue
        pts = np.asarray(found)
        for _ in range(3):  # drop points far from the line (the object, a stray shadow)
            c, e = _fit_line(pts)
            r = np.abs((pts - c) @ np.array([-e[1], e[0]]))
            keep = r <= max(2.5 * np.median(r), 1.0)
            if keep.all() or keep.sum() < 5:
                break
            pts = pts[keep]
        lines.append(_fit_line(pts))
    q = _quad_from_lines(lines)
    if q is None or np.abs(q - quad).max() > 2 * reach:
        return quad
    return q


def _hough_lines(field: np.ndarray, n: int = 16, spread_deg: int = 2):
    """The ``n`` strongest straight edges of ``field`` as (theta, rho): the line
    x cos(theta) + y sin(theta) = rho. Each edge pixel votes near its gradient direction."""
    gy, gx = np.gradient(field)
    mag = np.hypot(gx, gy)
    thr = max(np.percentile(mag, 92), 1e-6)
    ys, xs = np.nonzero(mag > thr)
    if len(xs) == 0:
        return []
    w = mag[ys, xs]
    th = np.degrees(np.arctan2(gy[ys, xs], gx[ys, xs])) % 180.0
    diag = int(np.ceil(np.hypot(*field.shape)))
    acc = np.zeros((180, 2 * diag + 1))
    for dt in range(-spread_deg, spread_deg + 1):
        t = (np.round(th).astype(int) + dt) % 180
        rad = np.radians(t)
        rho = np.round(xs * np.cos(rad) + ys * np.sin(rad)).astype(int) + diag
        np.add.at(acc, (t, rho), w)
    lines = []
    acc = acc.copy()
    for _ in range(n):
        t, r = np.unravel_index(int(np.argmax(acc)), acc.shape)
        if acc[t, r] <= 0:
            break
        lines.append((np.radians(t), float(r - diag)))
        for dt in range(-6, 7):  # suppress the neighbourhood (theta wraps with rho flipping sign)
            tt = t + dt
            rr = r if 0 <= tt < 180 else 2 * diag - r
            acc[tt % 180, max(rr - 12, 0):rr + 13] = 0
    return lines


def _line(theta_rho):
    th, rho = theta_rho
    nrm = np.array([np.cos(th), np.sin(th)])
    return nrm * rho, np.array([-nrm[1], nrm[0]])


def _quads_from_lines(lines, shape, min_sep: float):
    """Quadrilaterals from two pairs of roughly parallel lines that cross at sensible angles."""
    out = []
    pairs = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            (t1, r1), (t2, r2) = lines[i], lines[j]
            d = abs((np.degrees(t1 - t2) + 90) % 180 - 90)
            if d < 25:  # roughly parallel (perspective tilts opposite sides a little)
                p1, _ = _line(lines[i])
                p2, e2 = _line(lines[j])
                sep = abs((p1 - p2) @ np.array([-e2[1], e2[0]]))
                if sep > min_sep:
                    pairs.append((lines[i], lines[j]))
    h, w = shape
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            (la, lb), (lc, ld) = pairs[a], pairs[b]
            d = abs((np.degrees(la[0] - lc[0]) + 90) % 180 - 90)
            if d < 50:  # the two pairs must cross
                continue
            q = _quad_from_lines([_line(la), _line(lc), _line(lb), _line(ld)])
            if q is None or not (np.all(q[:, 0] > -0.05 * w) and np.all(q[:, 0] < 1.05 * w)
                                 and np.all(q[:, 1] > -0.05 * h) and np.all(q[:, 1] < 1.05 * h)):
                continue
            out.append(q)
    return out


def _side_support(quad: np.ndarray, gx: np.ndarray, gy: np.ndarray, thr: float) -> float:
    """How well the weakest side of ``quad`` lies on a sharp edge with the paper (higher
    ``field``) inside: the fraction of points along it with an inward step above ``thr``."""
    h, w = gx.shape
    c = quad.mean(axis=0)
    worst = 1.0
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        d = b - a
        length = np.linalg.norm(d)
        if length < 10:
            return 0.0
        d = d / length
        nrm = np.array([-d[1], d[0]])
        if (c - a) @ nrm < 0:
            nrm = -nrm  # point inwards
        ts = np.arange(0.05 * length, 0.95 * length, 1.5)
        pts = a + ts[:, None] * d
        best = np.zeros(len(ts))
        for off in (-1.5, -0.5, 0.5, 1.5):  # allow the line to be a pixel or so off
            q = pts + off * nrm
            xi = np.clip(np.round(q[:, 0]).astype(int), 0, w - 1)
            yi = np.clip(np.round(q[:, 1]).astype(int), 0, h - 1)
            best = np.maximum(best, gx[yi, xi] * nrm[0] + gy[yi, xi] * nrm[1])
        inside = (pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)
        worst = min(worst, float(np.mean((best > thr) & inside)))
    return worst


def find_rectangle_corners(img: Image.Image, work_px: int = 600, min_frac: float = 0.05,
                           aspect: float | None = None, snap_px: int = 1600) -> np.ndarray | None:
    """Guess the 4 corners (photo pixels, TL/TR/BR/BL) of a sheet of paper or card.

    Paper is brighter and more neutral (less saturated) than a table, but not everywhere:
    in a shadow it can be darker than lit table and tinted by warm light. What holds
    everywhere is its outline: four straight, sharp edges with the paper on the brighter,
    more neutral side, unlike a shadow's soft edge. So candidates come from straight edges
    (a Hough transform) and from brightness/saturation masks, and each is scored by how much
    of its weakest side runs along such an edge, and by ``aspect`` (long / short side) if
    given. The winner's sides are snapped to the edges in the full-resolution photo.
    Returns None when nothing plausible is found.
    """
    from contourpy import contour_generator
    from PIL import ImageFilter
    from shapely.geometry import MultiPoint, Polygon

    rgb = img.convert("RGB")
    k = min(1.0, work_px / max(img.size))
    small = rgb if k >= 1.0 else rgb.resize((max(int(img.size[0] * k), 1), max(int(img.size[1] * k), 1)),
                                            Image.Resampling.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(1.0))
    v, sat = value_saturation(np.asarray(small, dtype=float))
    field = v / 255.0 - sat  # high on paper: bright and neutral
    gy, gx = np.gradient(field)
    mag = np.hypot(gx, gy)
    step_thr = 0.25 * np.percentile(mag, 99.5)  # a sharp edge: a good part of the strongest steps

    cands = _quads_from_lines(_hough_lines(field), v.shape, min_sep=0.15 * min(v.shape))
    # mask candidates: neutral regions and bright regions at several thresholds
    bright = v > 0.35 * np.percentile(v, 99)
    masks = [(sat < t) & bright for t in (0.08, 0.12, 0.16, 0.22, otsu(sat))]
    masks += [v > t for t in (otsu(v), *np.percentile(v, (40, 55, 70)))]
    for mask in masks:
        z = np.pad(dilate(erode(mask, 2), 2).astype(float), 1)  # cut thin bridges
        for line in contour_generator(z=z).lines(0.5):
            if len(line) < 8:
                continue
            region = Polygon(line - 1.0).buffer(0)
            if region.is_empty:
                continue
            if region.geom_type != "Polygon":
                region = max(region.geoms, key=lambda g: g.area)
            if region.area < min_frac * v.size:
                continue
            region = Polygon(region.exterior).buffer(0)  # objects on the paper leave holes
            if region.geom_type != "Polygon":
                region = max(region.geoms, key=lambda g: g.area)
            hull = np.asarray(MultiPoint(np.asarray(region.exterior.coords)).convex_hull.exterior.coords)[:-1]
            if len(hull) >= 4:
                cands.append(_fit_sides(_reduce_to_quad(hull), np.asarray(region.exterior.coords),
                                        tol=max(3.0, 0.01 * max(v.shape))))

    best, best_score = None, 0.0
    for quad in cands:
        qp = Polygon(quad)
        if not qp.is_valid or qp.area < min_frac * v.size or not qp.equals(qp.convex_hull):
            continue
        score = _side_support(quad, gx, gy, step_thr)
        if aspect is not None:
            sides = np.linalg.norm(np.roll(quad, -1, axis=0) - quad, axis=1)
            a, b = sides[0] + sides[2], sides[1] + sides[3]
            r = max(a, b) / max(min(a, b), 1e-9)
            score *= float(np.exp(-abs(np.log(r / max(aspect, 1 / aspect))) / 0.35))
        score *= (qp.area / v.size) ** 0.05  # all else equal, the bigger sheet
        if score > best_score:
            best, best_score = quad, score
    if best is None or best_score < 0.5:
        return None
    # snap to the edges at up to snap_px (a phone photo at full size is slow and no better)
    ks = min(1.0, snap_px / max(img.size))
    big = rgb if ks >= 1.0 else rgb.resize((max(int(img.size[0] * ks), 1), max(int(img.size[1] * ks), 1)),
                                           Image.Resampling.BILINEAR)
    fv, fs = value_saturation(np.asarray(big.filter(ImageFilter.GaussianBlur(1.0)), dtype=float))
    quad = order_corners(best * ks / k)
    return order_corners(_snap_sides(quad, fv / 255.0 - fs, reach=max(4.0, 3.0 * ks / k)) / ks)
