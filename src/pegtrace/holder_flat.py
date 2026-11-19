"""Flat mode: the object hangs flat against the board, held in a band of walls.

Frame: x along the board, y up (against gravity), z out of the board. The
object outline ``P`` lies in the xy plane, resting against the back plate.

The holder is a band between two heights on the object, Top Y and Bottom Y (mm
above its lowest point). Inside the band, walls follow the object at the wall
thickness, with the back plate behind and a lip in front:

- Bottom Y at or below 0: the band reaches under the object and the space below it
  is filled in down to Bottom Y. A pocket: the object sits in it.
- Bottom Y above 0: the object hangs through the band. A ring: a wider part of the
  object above it rests on it. Supports under the ring slope back to the board, so
  it still prints upright without supports, and everything below hangs free.

Key idea: ``U = sweep_up(Pc)`` is every point the (clearance-grown) outline
passes through while being lifted straight up and out. Walls never enter U,
so the object can always be removed upwards and the cavity has no overhangs
when printed upright. (In a ring, only the part of the object in the band is
swept: the parts below it are threaded through by tilting the object.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point, Polygon

from .csg import Solid, extrude_x, extrude_z
from .geom2d import BIG, above, below, clean, polygons_of, rect, sweep_down, sweep_up, union
from .holder import HolderResult
from .params import FlatParams, PegboardParams
from .pegs import PegLayout, layout_pegs, peg_solids

MIN_BAND = 3.0  # mm: the least height between Top Y and Bottom Y
RING_HEIGHT = 10.0  # mm: the band height suggested for a ring
CHAMFER_SLOPE = 1.2  # rise per run of the ring's underside: about 50 degrees, printable without supports


@dataclass
class FlatRegions:
    outline: Polygon  # P
    grown: Polygon  # Pc
    keepout: Polygon  # U
    top: float  # top of the band
    bottom: float  # bottom of the band
    lip_top: float
    y_floor: float  # lowest point of the holder's body (a ring's sloped supports reach below the band)
    band: object  # everything in the band: walls and the object's place between them
    back: object
    walls: object
    lip: object
    pegs: PegLayout
    ring: bool = False  # the object hangs through the band
    rest: float | None = None  # ring: where the object's wide part meets it (None: nowhere)
    plate_below: float = 0.0  # ring: how far the back plate reaches below the sloped supports
    cleared: object = None  # the keep-out with gaps narrower than a wall closed up (walls stay out of it)
    wall: float = 0.0
    notes: tuple = ()  # how the settings were adjusted to make a holder

    @property
    def style(self) -> str:
        return "ring" if self.ring else "pocket"


def wall_around(keepout, wall: float):
    """The space walls must clear, and everything within ``wall`` of it.

    Walls are ``outer - cleared``, so they are at least ``wall`` thick everywhere:
    - they follow the keep-out (the space the object moves through), not the outline, which a
      wider part of the object would shave thinner as it sweeps past;
    - the keep-out is first closed by ``wall``: gaps and notches narrower than that become
      part of the cleared space instead of thin slivers or bridges of wall.
    """
    r = wall / 2
    filled = clean(keepout.buffer(r, quad_segs=12).buffer(-r, quad_segs=12).difference(keepout))
    # only real gaps: closing also shifts straight edges by a rounding error, a hairline that
    # would grow a wall where none belongs (under the bar of a T sitting on the ring, say)
    filled = clean(filled.buffer(-0.05).buffer(0.05))
    cleared = clean(keepout.union(filled)) if not filled.is_empty else keepout
    return cleared, cleared.buffer(wall, quad_segs=12)


THIN_TOL = 0.05  # mm: how much thinner than the setting a wall may be before it counts as thin


def without_thin_parts(walls, wall: float):
    """Remove what is still thinner than ``wall``: tapering horns where a curve of the
    keep-out meets the edge of the band or pocket, or a thin tip cut by the thumb notch.
    Thin parts are what an opening by ``wall / 2`` removes, except the small bits it shaves off
    every sharp corner (those stay, so corners stay square and print without overhangs)."""
    r = wall / 2 - THIN_TOL  # offsets drawn with chords fall a hair short of ``wall`` at curves
    opened = walls.buffer(-r, quad_segs=12).buffer(r, quad_segs=12)
    corner = 2 * (wall / 2) ** 2 * (1 - np.pi / 4)  # an acute corner sheds up to about this much
    thin = [p for p in polygons_of(walls.difference(opened)) if p.area > corner]
    if not thin:
        return walls
    # a hair's margin, and no specks left over: they would be loose bits in the print
    return clean(walls.difference(union(thin).buffer(1e-4)), min_area=corner)


def ring_rest(pc: Polygon, top: float, fp: FlatParams, height: float) -> float | None:
    """Where an object (clearance outline ``pc``) sliding down into a ring ``height`` tall whose
    top is at ``top`` comes to rest: the lowest point above the ring that sticks out past every hole in
    it (the object's cross-section within the ring; one per handle when there are several).
    None: it slides through."""
    _, y0, _, y1 = pc.bounds
    holes = polygons_of(above(below(pc, top), top - height))
    if not holes:
        return None
    s = max(1.0, fp.wall / 2)  # overhang needed to rest on the ring rather than slip past it
    strips = union([rect(h.bounds[0] - s, y0 - 1, h.bounds[2] + s, y1 + 1) for h in holes])
    over = clean(above(pc, top).difference(strips))
    return None if over.is_empty else float(max(over.bounds[1], top))


def suggest_ring_top(pc: Polygon, start: float, fp: FlatParams, height: float = RING_HEIGHT) -> float | None:
    """A ring top at or above ``start`` that the object rests on without sliding: move up to
    where it would come to rest until that settles (the holes can change on the way)."""
    top = start
    for _ in range(8):
        rest = ring_rest(pc, top, fp, height)
        if rest is None:
            return None
        if rest - top < 0.25:
            return top
        top = rest
    return top


def ring_top_below(pc: Polygon, start: float, fp: FlatParams, height: float, step: float = 0.5) -> float | None:
    """The highest ring top at or below ``start`` that the object rests on right away (for
    a ring set inside a wide part, which then slides through)."""
    y0 = pc.bounds[1]
    for t in np.arange(start, y0, -step):
        rest = ring_rest(pc, float(t), fp, height)
        if rest is not None and rest - t < 1.0:
            return float(t)
    return None


def band_limits(outline: Polygon, pc: Polygon, fp: FlatParams) -> tuple[float, float, list[str]]:
    """Top and bottom of the band in the holder frame, and notes on any setting that had to
    give way: the top stays on the object, the band at least MIN_BAND tall, and a pocket's
    floor at least a wall thick under the gap around the object (thinner, it would be dropped
    as too thin to print)."""
    y0 = outline.bounds[1]
    top = min(max(y0 + fp.top_y, y0 + 0.5), pc.bounds[3])
    bottom = y0 + fp.bottom_y
    notes = []
    if bottom > top - MIN_BAND:
        bottom = top - MIN_BAND
        notes.append(f"Bottom Y has to be at least {MIN_BAND:g} mm below Top Y, so the holder's bottom is at "
                     f"{bottom - y0:g} mm.")
    floor = pc.bounds[1] - fp.wall
    if floor < bottom - 1e-6 and bottom <= y0 + 1e-6:  # a pocket, but its floor would be too thin
        notes.append(f"Bottom Y {bottom - y0:g} mm leaves a floor thinner than a wall under the object, so "
                     f"the floor goes down to {floor - y0:.1f} mm.")
        bottom = floor
    return top, bottom, notes


def flat_regions(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> FlatRegions:
    """All 2D regions of a flat holder (cheap; no 3D work)."""
    pc = outline.buffer(fp.clear_xy, quad_segs=12) if fp.clear_xy > 0 else outline
    top, bottom, notes = band_limits(outline, pc, fp)
    ring = bottom > outline.bounds[1] + 1e-6
    band = rect(pc.bounds[0] - BIG, bottom, pc.bounds[2] + BIG, top)
    # The walls clear the object's place in the band and the way in from above. In a ring,
    # parts below the band are threaded through by tilting the object (handles that flare
    # apart, say), so unlike the part in the band they don't cut it open; the object itself
    # (pc) stays clear.
    inside = above(below(pc, top), bottom - 1.0)
    u = union([sweep_up(inside), pc])
    cleared, _ = wall_around(u, fp.wall)
    # only the cleared space inside the band makes walls (a part of the object just above it
    # would leave a sliver under itself, cut off by the top of the band); everything under
    # them in the band is filled in: a pocket's floor, and no overhangs to print
    held = clean(cleared.intersection(band))
    outer = clean(held.buffer(fp.wall, quad_segs=12).intersection(band))
    outer = clean(above(sweep_down(outer), bottom))
    walls = clean(outer.difference(cleared))

    lip = Polygon()
    base = max(bottom, pc.bounds[1])  # the lip's height counts from where the object enters the band
    lip_top = base + (top - base) * fp.lip_height_percent / 100
    if fp.lip:
        part = clean(above(below(pc, top), bottom))
        window = part.buffer(-fp.lip_overlap, quad_segs=12) if not part.is_empty else part
        lip = clean(below(outer, lip_top))
        if not window.is_empty:
            lip = clean(lip.difference(sweep_up(window)))

    # pegs: hooks as high as the band allows, never below its bottom
    r = pb.peg_d / 2
    xmin, _, xmax, _ = outer.bounds
    layout = layout_pegs(xmin, xmax, bottom + pb.tab_margin + r, top - pb.tab_margin - r, pb)
    zmax = fp.back_t + fp.object_thickness + fp.clear_z + fp.lip_t
    y_floor = bottom - CHAMFER_SLOPE * zmax if ring else bottom  # a ring: lowest point of its supports
    plate_bottom = y_floor - fp.plate_below if ring else bottom  # a ring: the 3D build slopes it like the supports
    tab = layout.tab(pb.tab_margin, plate_bottom)
    rr = min(4.0, pb.tab_margin)
    tab = tab.buffer(-rr).buffer(rr, quad_segs=8) if rr > 0 else tab  # round corners
    tab = above(sweep_down(tab), plate_bottom)
    back = union([outer, tab])

    if fp.notch:
        cx = outline.centroid.x
        walls = clean(walls.difference(Point(cx, top).buffer(fp.notch_d / 2, quad_segs=16)))
        if not lip.is_empty:
            lip = clean(lip.difference(Point(cx, lip_top).buffer(fp.notch_d / 2, quad_segs=16)))
    walls = without_thin_parts(walls, fp.wall)

    return FlatRegions(outline=outline, grown=pc, keepout=u, top=top, bottom=bottom, lip_top=lip_top,
                       y_floor=y_floor, band=outer, back=back, walls=walls, lip=lip, pegs=layout, ring=ring,
                       rest=ring_rest(pc, top, fp, top - bottom) if ring else None,
                       plate_below=fp.plate_below, cleared=cleared, wall=fp.wall, notes=tuple(notes))


def with_band(fp: FlatParams, top_y: float, bottom_y: float) -> FlatParams:
    """A copy of ``fp`` with another band."""
    vals = {k: v for k, v in fp.param.values().items() if k != "name"}
    vals.update(top_y=float(top_y), bottom_y=float(bottom_y))
    return type(fp)(**vals)


def _half_mm_down(v: float) -> float:
    return float(np.floor(v * 2 + 1e-9) / 2)


def ring_tops(pc: Polygon, fp: FlatParams, y_min: float, step: float = 1.0) -> list[float]:
    """Ring tops (at or above ``y_min``) that hold the object right where it is: a ring
    RING_HEIGHT tall there catches a wider part above it (see ``ring_rest``). Found by sliding
    a ring up from each level until the object rests on it."""
    tops: set[float] = set()
    for y in np.arange(y_min, pc.bounds[3], step):
        t = suggest_ring_top(pc, float(y), fp, RING_HEIGHT)
        if t is not None and ring_rest(pc, t, fp, RING_HEIGHT) is not None:
            tops.add(round(t * 4) / 4)
    return sorted(tops, reverse=True)


def find_ring(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> tuple[float, float, bool] | None:
    """The best ring for ``outline`` (in the holder frame): Top Y, Bottom Y, and whether it
    holds the object securely (see ``stability.is_secure``). None if no ring can hold it.

    A ring needs the object to get clearly wider going up: something above the ring sticks
    out past the part inside it by at least half a wall (and 1 mm). The ring must fit above
    the object's bottom, and the object must rest on it without sliding or tipping out.
    Secure rings win, then the highest (most of the object hanging below).
    """
    from .stability import check_flat, is_secure

    y0 = outline.bounds[1]
    pc = outline.buffer(fp.clear_xy, quad_segs=12) if fp.clear_xy > 0 else outline
    best = None
    for t in ring_tops(pc, fp, y0 + RING_HEIGHT + 1.5):
        top_y = _half_mm_down(t - y0)  # never above where it rests
        bottom_y = top_y - RING_HEIGHT
        if bottom_y <= 1.0:
            continue
        reg = flat_regions(outline, with_band(fp, top_y, bottom_y), pb)
        if reg.rest is None or reg.rest - reg.top >= 1.0:
            continue
        rep = check_flat(outline, reg.walls)
        if not rep.stable:
            continue
        if is_secure(rep):
            return top_y, bottom_y, True
        best = best or (top_y, bottom_y, False)
    return best


def suggest_band(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> tuple[float, float, str]:
    """Top Y and Bottom Y for ``outline`` (in the holder frame), and "ring" or "pocket":
    a ring if one can hold the object (see ``find_ring``), else a pocket around the bottom,
    as deep as it takes to hold the object securely, with a floor a wall thick under the gap."""
    from .stability import suggest_pocket_top

    ring = find_ring(outline, fp, pb)
    if ring is not None:
        return ring[0], ring[1], "ring"
    pc = outline.buffer(fp.clear_xy, quad_segs=12) if fp.clear_xy > 0 else outline
    floor = -float(np.ceil((fp.clear_xy + fp.wall) * 2 - 1e-9) / 2)
    top_y = suggest_pocket_top(outline, fp, pb, floor)
    if top_y is None:
        top_y = 0.4 * (pc.bounds[3] - pc.bounds[1]) - fp.clear_xy
    return max(_half_mm_down(top_y), 0.5), floor, "pocket"


def build_flat(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> HolderResult:
    from .stability import check_flat

    if outline is None or outline.is_empty:
        raise ValueError("no outline to build from")
    reg = flat_regions(outline, fp, pb)
    bt = fp.back_t
    depth = fp.object_thickness + fp.clear_z
    parts = {
        "back plate": extrude_z(reg.back, 0.0, bt),
        "walls": extrude_z(reg.walls, bt, bt + depth),
        "lip": extrude_z(reg.lip, bt + depth, bt + depth + fp.lip_t),
        "pegs": peg_solids(reg.pegs, pb),
    }
    if reg.ring:
        parts = _with_ring_chamfer(parts, reg, bt, depth, fp.lip_t)
    parts = {k: v for k, v in parts.items() if not v.is_empty()}
    solid = Solid.union_all(list(parts.values()))

    keepout = extrude_z(below(reg.keepout, reg.top + 1e3), bt, bt + depth)
    ghost = extrude_z(outline, bt, bt + fp.object_thickness)

    warnings: list[str] = list(reg.notes)
    stab = check_flat(outline, reg.walls)
    warnings.extend(stab.messages)
    if reg.ring:
        y0 = outline.bounds[1]
        height = reg.top - reg.bottom

        def as_setting(y):  # a level in the frame -> the Top Y setting, rounded down to 0.5 mm
            return f"{_half_mm_down(y - y0):g}"

        if reg.rest is None:
            low = ring_top_below(reg.grown, reg.top, fp, height)
            hint = (f" A wider part starts at {as_setting(low)} mm: try that as Top Y."
                    if low is not None else " Turn the object wide end up, or set Bottom Y below 0 for a pocket.")
            warnings.append("Nothing above Top Y sticks out past the part of the object inside the ring, so the "
                            "object would slide through." + hint)
        elif reg.rest - reg.top > 1.0:
            fit = suggest_ring_top(reg.grown, reg.top, fp, height) or reg.rest
            warnings.append(f"The object will slide down {reg.rest - reg.top:.0f} mm before its wider part rests "
                            f"on the ring. To hold it where it is, set Top Y to {as_setting(fit)} mm.")
    elif reg.top - reg.grown.bounds[1] < 2 * fp.wall:
        warnings.append("Pocket is very shallow; raise Top Y.")
    if len(reg.pegs.hooks) == 1 and not reg.pegs.pins:
        warnings.append("Only one hook and no pins: the holder can swivel. Enable pins or add columns.")
    if not fp.lip:
        warnings.append("No front lip: the object is only held by friction against tipping forward.")
    if not solid.is_valid():
        warnings.append("Geometry kernel reported an invalid solid.")
    elif solid.num_components() > 1:
        warnings.append("The holder is made of disconnected pieces; check wall/plate settings.")

    lo, hi = solid.bounds()
    info = {
        "size_mm": tuple(float(v) for v in (hi - lo)),
        "volume_cm3": solid.volume() / 1000.0,
        "pocket_depth_mm": reg.top - max(reg.bottom, reg.grown.bounds[1]),
        "style": reg.style,
        "hooks": len(reg.pegs.hooks),
        "pins": len(reg.pegs.pins),
        "stable": stab.stable,
        "tip_angle": stab.catch_angle,
    }
    regions = {
        "back plate": reg.back,
        "walls": reg.walls,
        "lip": reg.lip,
        "clearance": reg.grown,
        "keepout": below(reg.keepout, reg.top + 20),
    }
    return HolderResult(mode="flat", solid=solid, parts=parts, regions=regions, outline=outline,
                        ghost=ghost, keepout=keepout, pegs=reg.pegs, warnings=warnings, info=info)


def _with_ring_chamfer(parts: dict, reg: FlatRegions, bt: float, depth: float, lip_t: float) -> dict:
    """Give the ring an underside sloping back to the board, so it prints upright. The back
    plate's bottom follows the same slope, ``plate_below`` lower, so with 0 the whole underside
    is one flat face the holder can lie on to print at an angle."""
    zmax = bt + depth + lip_t
    bottom = reg.bottom
    yf = reg.y_floor
    x0, _, x1, _ = union([reg.back, below(reg.cleared, bottom)]).bounds  # supports may follow the object out
    x0, x1 = x0 - reg.wall - 1, x1 + reg.wall + 1
    k = CHAMFER_SLOPE

    def above_slope(drop):  # (z, y) half-plane above the line from (0, y_floor) to (zmax, bottom), lowered
        return extrude_x(Polygon([(-1, yf - k - drop), (zmax + 1, bottom + k - drop), (zmax + 1, BIG),
                                  (-1, BIG)]), x0, x1)

    wedge = above_slope(0.0)

    def down(g):
        return clean(above(sweep_down(g), yf - 1))

    ring = reg.band
    # Under the walls, minus the space the object hangs in. Where a part of the object leans
    # out under a wall, the support follows it out to a full wall's thickness, even past the
    # ring's edge, instead of tapering to a sliver. Never under the ring's openings, though:
    # parts there narrowing downwards would trap the wider parts above them.
    hanging = clean(below(reg.cleared, bottom))  # the object below the ring
    openings = down(clean(reg.cleared.intersection(rect(*ring.bounds[:2], *ring.bounds[2:]))))
    near = clean(below(hanging.buffer(reg.wall, quad_segs=12), bottom).difference(openings))
    support_walls = clean(union([down(reg.walls), near]).difference(reg.cleared))
    support_walls = without_thin_parts(support_walls, reg.wall)
    under = union([down(ring), support_walls])
    front = union([down(reg.lip), support_walls]) if not reg.lip.is_empty else Polygon()  # under the lip
    support = {
        "back plate": extrude_z(under, 0.0, bt),
        "walls": extrude_z(support_walls, bt, bt + depth),
        "lip": extrude_z(front, bt + depth, zmax),
    }
    out = dict(parts)
    out["back plate"] = out["back plate"] & above_slope(reg.plate_below)
    for k, extra in support.items():
        if extra.is_empty():
            continue
        extra = extra & wedge
        out[k] = out[k] + extra if k in out else extra
    return out
