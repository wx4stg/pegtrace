"""Pure 2D geometry helpers built on shapely and numpy (no 3D backend)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry

BIG = 1e4  # 10 m: far larger than any holder


def polygons_of(geom: BaseGeometry | None) -> list[Polygon]:
    """Return the non-empty polygon parts of any geometry."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [p for p in geom.geoms if not p.is_empty]
    if hasattr(geom, "geoms"):
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(polygons_of(g))
        return out
    return []


def clean(geom: BaseGeometry | None, min_area: float = 1e-6) -> BaseGeometry:
    """Make valid, keep only polygonal parts above ``min_area``."""
    if geom is None or geom.is_empty:
        return Polygon()
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    parts = [p for p in polygons_of(geom) if p.area > min_area]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def largest_polygon(geom: BaseGeometry | None) -> Polygon:
    parts = polygons_of(clean(geom))
    if not parts:
        return Polygon()
    return max(parts, key=lambda p: p.area)


def fill_holes(geom: BaseGeometry) -> BaseGeometry:
    parts = [Polygon(p.exterior) for p in polygons_of(geom)]
    return clean(shapely.union_all(parts)) if parts else Polygon()


def sweep(geom: BaseGeometry, dx: float, dy: float) -> BaseGeometry:
    """Minkowski sum of ``geom`` with the segment from (0, 0) to (dx, dy).

    This is the region swept out by ``geom`` translating along that vector.
    """
    geom = clean(geom)
    if geom.is_empty:
        return geom
    pieces: list[BaseGeometry] = [geom, affinity.translate(geom, dx, dy)]
    d = np.array([dx, dy])
    for poly in polygons_of(geom):
        for ring in [poly.exterior, *poly.interiors]:
            c = np.asarray(ring.coords)
            a, b = c[:-1], c[1:]
            e = b - a
            cross = e[:, 0] * dy - e[:, 1] * dx
            keep = np.abs(cross) > 1e-12
            a, b = a[keep], b[keep]
            if len(a) == 0:
                continue
            quads = np.stack([a, b, b + d, a + d], axis=1)
            pieces.extend(shapely.polygons(quads))
    return clean(shapely.union_all(pieces))


def sweep_up(geom: BaseGeometry, length: float = BIG) -> BaseGeometry:
    return sweep(geom, 0.0, length)


def sweep_down(geom: BaseGeometry, length: float = BIG) -> BaseGeometry:
    return sweep(geom, 0.0, -length)


def below(geom: BaseGeometry, y: float) -> BaseGeometry:
    """Part of ``geom`` with y <= ``y``."""
    return clean(geom.intersection(box(-BIG, -BIG, BIG, y)))


def above(geom: BaseGeometry, y: float) -> BaseGeometry:
    """Part of ``geom`` with y >= ``y``."""
    return clean(geom.intersection(box(-BIG, y, BIG, BIG)))


def rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def union(geoms: Iterable[BaseGeometry]) -> BaseGeometry:
    gs = [g for g in geoms if g is not None and not g.is_empty]
    return clean(shapely.union_all(gs)) if gs else Polygon()


def to_contours(geom: BaseGeometry) -> list[np.ndarray]:
    """Shapely geometry -> list of Nx2 contours (CCW outer, CW holes)."""
    contours: list[np.ndarray] = []
    for poly in polygons_of(clean(geom)):
        poly = shapely.geometry.polygon.orient(poly, sign=1.0)
        contours.append(np.asarray(poly.exterior.coords)[:-1].astype(float))
        for hole in poly.interiors:
            contours.append(np.asarray(hole.coords)[:-1].astype(float))
    return contours


def from_contours(contours) -> BaseGeometry:
    """List of rings (Positive/EvenOdd nesting) -> shapely geometry."""
    rings = [np.asarray(c, dtype=float) for c in contours if len(c) >= 3]
    if not rings:
        return Polygon()
    result: BaseGeometry = Polygon()
    for r in rings:
        result = result.symmetric_difference(clean(Polygon(r)))
    return clean(result)
