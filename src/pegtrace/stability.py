"""Will the object stay in a flat-mode cradle?

All checks are 2D, in the holder frame (y up). The object outline ``P`` (no
clearance) is dropped onto the walls, then we test whether gravity can tip it
out around its contact points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon

from .geom2d import clean

AREA_TOL = 0.05  # mm^2 of overlap that counts as contact
MAX_TILT = 30


@dataclass
class StabilityReport:
    stable: bool
    rest_drop: float = 0.0  # how far the object falls from its traced position
    contacts: list[tuple[float, float]] = field(default_factory=list)
    catch_angle: float | None = None  # degrees it can tilt before being caught
    messages: list[str] = field(default_factory=list)


def _overlap(a: Polygon, b) -> float:
    return a.intersection(b).area


def rest_position(outline: Polygon, walls, max_drop: float = 50.0) -> tuple[Polygon, float]:
    """Drop the outline straight down until it touches the walls."""
    if _overlap(outline, walls) > AREA_TOL:
        return outline, 0.0
    lo, hi = 0.0, max_drop
    if _overlap(affinity.translate(outline, 0, -hi), walls) <= AREA_TOL:
        return affinity.translate(outline, 0, -hi), hi  # nothing below: falls through
    for _ in range(30):
        mid = (lo + hi) / 2
        if _overlap(affinity.translate(outline, 0, -mid), walls) > AREA_TOL:
            hi = mid
        else:
            lo = mid
    return affinity.translate(outline, 0, -lo), lo


def contact_points(poly: Polygon, walls, tol: float = 0.15) -> np.ndarray:
    ring = shapely.segmentize(poly.exterior, 0.5)
    pts = np.asarray(ring.coords)[:-1]
    d = shapely.distance(shapely.points(pts), walls)
    return pts[d < tol]


SECURE_TILT = 10  # degrees: a bump this big must not dislodge the object


def _catch_angle(rest: Polygon, walls, pivot, sign: float) -> float | None:
    """Degrees the object can rotate about ``pivot`` before hitting the walls."""
    base = _overlap(rest, walls)
    for deg in range(1, MAX_TILT + 1):
        tilted = affinity.rotate(rest, sign * deg, origin=tuple(pivot))
        if _overlap(tilted, walls) > base + 0.5:
            return float(deg)
    return None


def check_flat(outline: Polygon, walls) -> StabilityReport:
    """Static balance plus resistance to being bumped sideways."""
    walls = clean(walls)
    if walls.is_empty:
        return StabilityReport(False, messages=["No walls to hold the object."])
    rest, drop = rest_position(outline, walls)
    contacts = contact_points(rest, walls)
    if len(contacts) == 0:
        return StabilityReport(False, rest_drop=drop,
                               messages=["Object does not rest on the holder (falls through)."])
    cx = rest.centroid.x
    left = contacts[np.argmin(contacts[:, 0])]
    right = contacts[np.argmax(contacts[:, 0])]
    tilt_right = _catch_angle(rest, walls, right, -1.0)  # clockwise about right contact
    tilt_left = _catch_angle(rest, walls, left, 1.0)  # counter-clockwise about left contact
    report = StabilityReport(True, rest_drop=drop, contacts=[tuple(p) for p in contacts])
    report.catch_angle = None if tilt_left is None or tilt_right is None else max(tilt_left, tilt_right)

    balanced = left[0] - 0.5 <= cx <= right[0] + 0.5
    falling = None if balanced else (tilt_right if cx > right[0] else tilt_left)
    if not balanced and falling is None:
        report.stable = False
        report.messages.append(
            f"Object tips out of the pocket under its own weight (rotates more than {MAX_TILT} degrees "
            "freely); increase the pocket depth.")
        return report
    if not balanced and falling > SECURE_TILT:
        report.messages.append(
            f"Object leans about {falling:.0f} degrees before the walls catch it; a deeper pocket holds it snugly.")
    if report.catch_angle is None:
        report.messages.append(
            f"A sideways bump could knock the object out (it can rotate more than {MAX_TILT} degrees); "
            "consider a deeper pocket.")
    return report


def is_secure(rep: StabilityReport) -> bool:
    return rep.stable and rep.catch_angle is not None and rep.catch_angle <= SECURE_TILT


def suggest_pocket_percent(outline: Polygon, fp, pb, start: int = 10, stop: int = 95, step: int = 5) -> float | None:
    """Smallest pocket depth (% of height) that keeps the object secure (see ``is_secure``)."""
    from .holder_flat import flat_regions

    trial = fp.param.values()
    trial["pocket_mode"] = "percent"
    tmp = type(fp)(**{k: v for k, v in trial.items() if k != "name"})
    pc = outline.buffer(fp.clear_xy)
    height = pc.bounds[3] - pc.bounds[1]
    min_depth = max(3 * fp.wall, 10.0)  # absolute minimum for a practical cradle
    for pct in range(start, stop + 1, step):
        if pct / 100 * height < min_depth and pct < stop:
            continue
        tmp.pocket_percent = pct
        reg = flat_regions(outline, tmp, pb)
        if is_secure(check_flat(outline, reg.walls)):
            return float(pct)
    return None
