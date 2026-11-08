"""Peg layout on the pegboard grid and the peg / hook / pin solids.

Frame: x along the board, y up, z out of the board. The back face of the
holder sits on the board's front face at z = 0; pegs extend into -z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon

from .csg import Section, Solid
from .geom2d import rect
from .params import PegboardParams

EMBED = 0.6  # how far pegs reach into the back plate (mm)


@dataclass
class PegLayout:
    hooks: list[tuple[float, float]] = field(default_factory=list)
    pins: list[tuple[float, float]] = field(default_factory=list)
    radius: float = 3.0
    spacing: float = 25.4

    @property
    def points(self) -> list[tuple[float, float]]:
        return [*self.hooks, *self.pins]

    def tab(self, margin: float, y_floor: float) -> Polygon:
        """Back-plate rectangle covering every peg, extended down to ``y_floor``."""
        pts = self.points
        if not pts:
            return Polygon()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        e = margin + self.radius
        return rect(min(xs) - e, min(y_floor, min(ys) - e), max(xs) + e, max(ys) + e)


def layout_pegs(x_min: float, x_max: float, y_low: float, y_high: float, pb: PegboardParams) -> PegLayout:
    """Choose peg positions on the hole grid.

    ``x_min``/``x_max`` is the horizontal extent the holder already occupies,
    ``y_low`` the lowest allowed peg centre and ``y_high`` the preferred hook
    row. All pegs land on exact multiples of the hole spacing relative to each
    other.
    """
    r = pb.peg_d / 2
    pitch = pb.spacing * pb.stride
    width = max(x_max - x_min - 2 * (pb.tab_margin + r), 0.0)
    if pb.columns > 0:
        n = pb.columns
    else:
        n = min(pb.max_pegs, int(math.floor(width / pitch + 1e-9)) + 1)
    n = max(n, 1)
    xc = (x_min + x_max) / 2
    xs = [xc + (i - (n - 1) / 2) * pitch for i in range(n)]

    hook_y = max(y_high, y_low)
    pins: list[tuple[float, float]] = []
    if pb.add_pins:
        drop = pb.pin_rows * pb.spacing
        hook_y = max(hook_y, y_low + drop)
        pins = [(x, hook_y - drop) for x in xs]
    hooks = [(x, hook_y) for x in xs]
    return PegLayout(hooks=hooks, pins=pins, radius=r, spacing=pb.spacing)


def peg_profile(r: float, kind: str) -> Polygon:
    """Peg cross-section in the (x, y) plane.

    ``teardrop`` has 45 degree upper flanks (prints without support when the
    holder prints upright) and is cut flat at the top so it still fits the hole.
    """
    circle = Point(0, 0).buffer(r, quad_segs=16)
    if kind != "teardrop":
        return circle
    tip = Point(0, r * math.sqrt(2))
    tear = circle.union(tip).convex_hull
    return tear.intersection(rect(-2 * r, -2 * r, 2 * r, r))


def _horizontal_peg(x: float, y: float, z_back: float, profile: Polygon, chamfer: float = 0.0) -> Solid:
    """Peg along z from ``z_back`` (< 0) to EMBED, cross-section ``profile``."""
    sec = Section.from_shapely(profile)
    length = EMBED - z_back
    if chamfer <= 0 or chamfer >= length:
        body = sec.extrude(length).translate(0, 0, z_back)
    else:
        body = sec.extrude(length - chamfer).translate(0, 0, z_back + chamfer)
        tip = sec.extrude(chamfer, scale_top=0.65).mirror((0, 0, 1)).translate(0, 0, z_back + chamfer)
        body = body + tip
    return body.translate(x, y, 0)


def peg_solids(layout: PegLayout, pb: PegboardParams) -> Solid:
    r = layout.radius
    prof = peg_profile(r, pb.peg_profile)
    z_inner = -(pb.board_t + pb.board_clear)  # hook's inner face
    z_hook = z_inner - r  # hook rod axis
    seg = 32
    parts: list[Solid] = []
    for x, y in layout.hooks:
        parts.append(_horizontal_peg(x, y, z_hook, prof))
        parts.append(Solid.sphere(r, seg).translate(x, y, z_hook))
        if pb.hook_rise > 0:
            rod = Solid.cylinder(pb.hook_rise, r, r, seg).rotate(-90, 0, 0)  # axis -> +y
            parts.append(rod.translate(x, y, z_hook))
            parts.append(Solid.sphere(r, seg).translate(x, y + pb.hook_rise, z_hook))
    pin_len = pb.pin_length if pb.pin_length > 0 else 0.75 * pb.board_t
    for x, y in layout.pins:
        parts.append(_horizontal_peg(x, y, -pin_len, prof, chamfer=min(1.0, pin_len / 3)))
    return Solid.union_all(parts)
