"""Flat mode: the object hangs flat against the board in a shaped cradle.

Frame: x along the board, y up (against gravity), z out of the board. The
object outline ``P`` lies in the xy plane, resting against the back plate.

Key idea: ``U = sweep_up(Pc)`` is every point the (clearance-grown) outline
passes through while being lifted straight up and out. Walls never enter U,
so the object can always be removed upwards and the cavity has no overhangs
when printed upright.

Ring style: instead of a pocket around the bottom of the object, a band of
walls (plus the back plate and a closed front bar) circles a narrow part of
the object just below a wider part, which rests on it. Everything below the
ring hangs free. The underside of the ring is chamfered at 45 degrees back to
the board so it still prints upright without supports. The user sets the ring's
top: the height on the object where the wide part should rest.
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


@dataclass
class FlatRegions:
    outline: Polygon  # P
    grown: Polygon  # Pc
    keepout: Polygon  # U
    pocket_top: float  # h
    lip_top: float
    y_floor: float
    back: object
    walls: object
    lip: object
    pegs: PegLayout
    style: str = "pocket"
    ring_bottom: float | None = None  # ring style: bottom of the band
    ring_rest: float | None = None  # ring style: where the object's wide part meets the ring (None: nowhere)
    plate_below: float = 0.0  # ring style: how far the back plate reaches below the sloped supports
    cleared: object = None  # the keep-out with gaps narrower than a wall closed up (walls stay out of it)
    wall: float = 0.0


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


def pocket_top(pc: Polygon, fp: FlatParams) -> float:
    _, y0, _, y1 = pc.bounds
    height = y1 - y0
    depth = fp.pocket_percent / 100 * height if fp.pocket_mode == "percent" else fp.pocket_mm
    return y0 + min(max(depth, 0.5), height)


CHAMFER_SLOPE = 1.2  # rise per run of the ring's underside: about 50 degrees, printable without supports


def ring_level(pc: Polygon, fp: FlatParams) -> tuple[float, float] | None:
    """Best height for the top of a ring around ``pc`` (clearance outline), and its score.
    Auto orientation uses the score to pick the way up for the ring style; the ring itself
    goes where the user puts it (``FlatParams.ring_top``).

    At each level y the ring must let everything below y pass through it (the x extent
    of ``pc`` below y), and something just above y must stick out past that on both
    sides to rest on the ring. The score is that overhang relative to the ring's width,
    so narrow necks under wide parts win; ties go to the highest level.
    """
    x0, y0, x1, y1 = pc.bounds
    height = y1 - y0
    step = max(height / 200, 0.25)
    reach = max(2 * fp.wall, 3.0)  # how far above the ring to look for something to rest on
    min_support = max(1.0, fp.wall / 2)
    best = None
    for y in np.arange(y0 + step, y1 - step, step):
        lower = below(pc, y)
        slab = pc.intersection(rect(x0 - 1, y, x1 + 1, y + reach))
        if lower.is_empty or slab.is_empty:
            continue
        lo_x0, _, lo_x1, _ = lower.bounds
        sl_x0, _, sl_x1, _ = slab.bounds
        support = min(lo_x0 - sl_x0, sl_x1 - lo_x1)
        if support < min_support:
            continue
        score = support / max(lo_x1 - lo_x0, 1e-6)
        if best is None or score >= best[1] * 0.98:
            best = (float(y), score if best is None else max(score, best[1]))
    return best


def ring_rest(pc: Polygon, top: float, fp: FlatParams) -> float | None:
    """Where an object (clearance outline ``pc``) sliding down into a ring whose top is at
    ``top`` comes to rest: the lowest point above the ring that sticks out past every hole in
    it (the object's cross-section within the ring; one per handle when there are several).
    None: it slides through."""
    _, y0, _, y1 = pc.bounds
    holes = polygons_of(above(below(pc, top), top - fp.ring_height))
    if not holes:
        return None
    s = max(1.0, fp.wall / 2)  # overhang needed to rest on the ring rather than slip past it
    strips = union([rect(h.bounds[0] - s, y0 - 1, h.bounds[2] + s, y1 + 1) for h in holes])
    over = clean(above(pc, top).difference(strips))
    return None if over.is_empty else float(max(over.bounds[1], top))


def suggest_ring_top(pc: Polygon, start: float, fp: FlatParams) -> float | None:
    """A ring top at or above ``start`` that the object rests on without sliding: move up to
    where it would come to rest until that settles (the holes can change on the way)."""
    top = start
    for _ in range(8):
        rest = ring_rest(pc, top, fp)
        if rest is None:
            return None
        if rest - top < 0.25:
            return top
        top = rest
    return top


def ring_top_below(pc: Polygon, start: float, fp: FlatParams, step: float = 0.5) -> float | None:
    """The highest ring top at or below ``start`` that the object rests on right away (for
    a ring set inside a wide part, which then slides through)."""
    y0 = pc.bounds[1]
    for t in np.arange(start, y0, -step):
        rest = ring_rest(pc, float(t), fp)
        if rest is not None and rest - t < 1.0:
            return float(t)
    return None


def _ring_regions(outline: Polygon, pc: Polygon, u, fp: FlatParams, pb: PegboardParams) -> FlatRegions:
    y0, y1 = outline.bounds[1], outline.bounds[3]
    top = min(max(y0 + fp.ring_top, y0 + 0.5), y1)
    bottom = top - fp.ring_height
    band = rect(pc.bounds[0] - BIG, bottom, pc.bounds[2] + BIG, top)
    # The walls only clear the object's cross-section where it sits in the ring. Parts below
    # it are threaded through by tilting the object (handles that flare apart, say), so
    # unlike a pocket they don't cut the ring open; the object itself (pc) stays clear.
    inside = above(below(pc, top), bottom - 1.0)
    u = union([sweep_up(inside), pc])
    cleared, _ = wall_around(u, fp.wall)
    # only the cleared space inside the band makes walls (a part of the object just above it
    # would leave a sliver under itself, cut off by the top of the band)
    ring = clean(clean(cleared.intersection(band)).buffer(fp.wall, quad_segs=12).intersection(band))
    walls = without_thin_parts(clean(ring.difference(cleared)), fp.wall)
    zmax = fp.back_t + fp.object_thickness + fp.clear_z + fp.lip_t
    y_floor = bottom - CHAMFER_SLOPE * zmax  # lowest point of the chamfer under the ring

    r = pb.peg_d / 2
    xmin, _, xmax, _ = ring.bounds
    layout = layout_pegs(xmin, xmax, bottom + pb.tab_margin + r, top - pb.tab_margin - r, pb)
    plate_bottom = y_floor - fp.plate_below  # at the board; the 3D build slopes it like the supports
    tab = layout.tab(pb.tab_margin, plate_bottom)
    rr = min(4.0, pb.tab_margin)
    tab = tab.buffer(-rr).buffer(rr, quad_segs=8) if rr > 0 else tab
    tab = above(sweep_down(tab), plate_bottom)
    back = union([ring, tab])
    return FlatRegions(outline=outline, grown=pc, keepout=u, pocket_top=top, lip_top=top, y_floor=y_floor,
                       back=back, walls=walls, lip=ring, pegs=layout, style="ring", ring_bottom=bottom,
                       ring_rest=ring_rest(pc, top, fp), plate_below=fp.plate_below, cleared=cleared,
                       wall=fp.wall)


def flat_regions(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> FlatRegions:
    """All 2D regions of a flat holder (cheap; no 3D work)."""
    pc = outline.buffer(fp.clear_xy, quad_segs=12) if fp.clear_xy > 0 else outline
    u = sweep_up(pc)
    if fp.style == "ring":
        return _ring_regions(outline, pc, u, fp, pb)
    h = pocket_top(pc, fp)
    pl = below(pc, h)
    cleared, wout = wall_around(u, fp.wall)
    cradle = clean(below(wout, h))
    y_floor = cradle.bounds[1]
    walls = clean(cradle.difference(cleared))

    lip = Polygon()
    y0 = pc.bounds[1]
    lip_top = y0 + (h - y0) * fp.lip_height_percent / 100
    if fp.lip:
        window = sweep_up(pl.buffer(-fp.lip_overlap, quad_segs=12))
        lip = clean(below(wout, lip_top).difference(window))

    # pegs: hooks as high as the pocket allows, never below the floor
    r = pb.peg_d / 2
    xmin, _, xmax, _ = cradle.bounds
    y_low = y_floor + pb.tab_margin + r
    y_high = h - pb.tab_margin - r
    layout = layout_pegs(xmin, xmax, y_low, y_high, pb)
    tab = layout.tab(pb.tab_margin, y_floor)
    rr = min(4.0, pb.tab_margin)
    tab = tab.buffer(-rr).buffer(rr, quad_segs=8) if rr > 0 else tab  # round corners
    back = union([cradle, tab])

    if fp.flat_bottom:
        back = above(sweep_down(back), y_floor)
        walls = clean(above(sweep_down(walls), y_floor).difference(cleared))
        if not lip.is_empty:
            lip = above(sweep_down(lip), y_floor)

    if fp.notch:
        cx = outline.centroid.x
        notch = Point(cx, h).buffer(fp.notch_d / 2, quad_segs=16)
        walls = clean(walls.difference(notch))
        if not lip.is_empty:
            lip = clean(lip.difference(Point(cx, lip_top).buffer(fp.notch_d / 2, quad_segs=16)))
    walls = without_thin_parts(walls, fp.wall)

    return FlatRegions(outline=outline, grown=pc, keepout=u, pocket_top=h, lip_top=lip_top,
                       y_floor=y_floor, back=back, walls=walls, lip=lip, pegs=layout)


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
    if reg.style == "ring":
        parts = _with_ring_chamfer(parts, reg, bt, depth, fp.lip_t)
    parts = {k: v for k, v in parts.items() if not v.is_empty()}
    solid = Solid.union_all(list(parts.values()))

    keepout = extrude_z(below(reg.keepout, reg.pocket_top + 1e3), bt, bt + depth)
    ghost = extrude_z(outline, bt, bt + fp.object_thickness)

    warnings: list[str] = []
    stab = check_flat(outline, reg.walls)
    warnings.extend(stab.messages)
    if reg.style == "ring":
        y0 = outline.bounds[1]

        def as_setting(y):  # a level in the frame -> the Ring top setting, rounded down to 0.5 mm
            return f"{np.floor((y - y0) * 2) / 2:g}"

        if reg.ring_rest is None:
            low = ring_top_below(reg.grown, reg.pocket_top, fp)
            hint = (f" A wider part starts at {as_setting(low)} mm: try that as the ring top."
                    if low is not None else " Turn the object wide end up, or use the pocket style.")
            warnings.append("Nothing above the ring top sticks out past the part inside the ring, so the "
                            "object would slide through." + hint)
        elif reg.ring_rest - reg.pocket_top > 1.0:
            fit = suggest_ring_top(reg.grown, reg.pocket_top, fp) or reg.ring_rest
            warnings.append(f"The object will slide down {reg.ring_rest - reg.pocket_top:.0f} mm before its "
                            f"wider part rests on the ring. To hold it where it is, set the ring top to "
                            f"{as_setting(fit)} mm.")
    elif reg.pocket_top - reg.grown.bounds[1] < 2 * fp.wall:
        warnings.append("Pocket is very shallow; increase the pocket depth.")
    if len(reg.pegs.hooks) == 1 and not reg.pegs.pins:
        warnings.append("Only one hook and no pins: the holder can swivel. Enable pins or add columns.")
    if not fp.lip and reg.style != "ring":
        warnings.append("No front lip: the object is only held by friction against tipping forward.")
    if not solid.is_valid():
        warnings.append("Geometry kernel reported an invalid solid.")
    elif solid.num_components() > 1:
        warnings.append("The holder is made of disconnected pieces; check wall/plate settings.")

    lo, hi = solid.bounds()
    info = {
        "size_mm": tuple(float(v) for v in (hi - lo)),
        "volume_cm3": solid.volume() / 1000.0,
        "pocket_depth_mm": reg.pocket_top - reg.grown.bounds[1],
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
        "keepout": below(reg.keepout, reg.pocket_top + 20),
    }
    return HolderResult(mode="flat", solid=solid, parts=parts, regions=regions, outline=outline,
                        ghost=ghost, keepout=keepout, pegs=reg.pegs, warnings=warnings, info=info)


def _with_ring_chamfer(parts: dict, reg: FlatRegions, bt: float, depth: float, lip_t: float) -> dict:
    """Give the ring an underside sloping back to the board, so it prints upright. The back
    plate's bottom follows the same slope, ``plate_below`` lower, so with 0 the whole underside
    is one flat face the holder can lie on to print at an angle."""
    zmax = bt + depth + lip_t
    bottom = reg.ring_bottom
    yf = reg.y_floor
    x0, _, x1, _ = reg.back.bounds
    k = CHAMFER_SLOPE

    def above_slope(drop):  # (z, y) half-plane above the line from (0, y_floor) to (zmax, bottom), lowered
        return extrude_x(Polygon([(-1, yf - k - drop), (zmax + 1, bottom + k - drop), (zmax + 1, BIG),
                                  (-1, BIG)]), x0 - 1, x1 + 1)

    wedge = above_slope(0.0)

    def down(g):
        return clean(above(sweep_down(g), yf - 1))

    ring = reg.lip
    # Under the walls, minus the space the object hangs in. Where a leaning part of the object
    # cuts into that, the support also reaches out to a full wall's thickness from it (still
    # under the ring), so it doesn't taper to a sliver.
    hanging = clean(below(reg.cleared, bottom))  # the object below the ring
    near = clean(hanging.buffer(reg.wall, quad_segs=12).intersection(below(down(ring), bottom)))
    support_walls = clean(union([down(reg.walls), near]).difference(reg.cleared))
    support_walls = without_thin_parts(support_walls, reg.wall)
    support = {
        "back plate": extrude_z(down(ring), 0.0, bt),
        "walls": extrude_z(support_walls, bt, bt + depth),
        "lip": extrude_z(down(ring), bt + depth, zmax),
    }
    out = dict(parts)
    out["back plate"] = out["back plate"] & above_slope(reg.plate_below)
    for k, extra in support.items():
        if extra.is_empty():
            continue
        extra = extra & wedge
        out[k] = out[k] + extra if k in out else extra
    return out
