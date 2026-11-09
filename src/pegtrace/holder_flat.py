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
the board so it still prints upright without supports.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point, Polygon

from .csg import Solid, extrude_x, extrude_z
from .geom2d import BIG, above, below, clean, rect, sweep_down, sweep_up, union
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
    ring_found: bool = True  # ring style: an automatic ring level was found


def pocket_top(pc: Polygon, fp: FlatParams) -> float:
    _, y0, _, y1 = pc.bounds
    height = y1 - y0
    depth = fp.pocket_percent / 100 * height if fp.pocket_mode == "percent" else fp.pocket_mm
    return y0 + min(max(depth, 0.5), height)


CHAMFER_SLOPE = 1.2  # rise per run of the ring's underside: about 50 degrees, printable without supports


def ring_level(pc: Polygon, fp: FlatParams) -> tuple[float, float] | None:
    """Best height for the top of a ring around ``pc`` (clearance outline), and its score.

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


def _ring_regions(outline: Polygon, pc: Polygon, u, fp: FlatParams, pb: PegboardParams) -> FlatRegions:
    found = ring_level(pc, fp) if fp.ring_auto else None
    top = found[0] if found else pocket_top(pc, fp)
    bottom = top - fp.ring_height
    band = rect(pc.bounds[0] - BIG, bottom, pc.bounds[2] + BIG, top)
    ring = clean(below(pc, top).buffer(fp.wall, quad_segs=12).intersection(band))
    walls = clean(ring.difference(u))
    zmax = fp.back_t + fp.object_thickness + fp.clear_z + fp.lip_t
    y_floor = bottom - CHAMFER_SLOPE * zmax  # lowest point of the chamfer under the ring

    r = pb.peg_d / 2
    xmin, _, xmax, _ = ring.bounds
    layout = layout_pegs(xmin, xmax, bottom + pb.tab_margin + r, top - pb.tab_margin - r, pb)
    tab = layout.tab(pb.tab_margin, y_floor)
    rr = min(4.0, pb.tab_margin)
    tab = tab.buffer(-rr).buffer(rr, quad_segs=8) if rr > 0 else tab
    tab = above(sweep_down(tab), y_floor)  # square bottom: it stands on the bed
    back = union([ring, tab])
    return FlatRegions(outline=outline, grown=pc, keepout=u, pocket_top=top, lip_top=top, y_floor=y_floor,
                       back=back, walls=walls, lip=ring, pegs=layout, style="ring", ring_bottom=bottom,
                       ring_found=found is not None or not fp.ring_auto)


def flat_regions(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> FlatRegions:
    """All 2D regions of a flat holder (cheap; no 3D work)."""
    pc = outline.buffer(fp.clear_xy, quad_segs=12) if fp.clear_xy > 0 else outline
    u = sweep_up(pc)
    if fp.style == "ring":
        return _ring_regions(outline, pc, u, fp, pb)
    h = pocket_top(pc, fp)
    pl = below(pc, h)
    wout = pl.buffer(fp.wall, quad_segs=12)
    cradle = below(wout, h)
    y_floor = cradle.bounds[1]
    walls = clean(cradle.difference(u))

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
        walls = clean(above(sweep_down(walls), y_floor).difference(u))
        if not lip.is_empty:
            lip = above(sweep_down(lip), y_floor)

    if fp.notch:
        cx = outline.centroid.x
        notch = Point(cx, h).buffer(fp.notch_d / 2, quad_segs=16)
        walls = clean(walls.difference(notch))
        if not lip.is_empty:
            lip = clean(lip.difference(Point(cx, lip_top).buffer(fp.notch_d / 2, quad_segs=16)))

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
        if not reg.ring_found:
            warnings.append("No narrow part with a wider part above it was found, so the ring sits at the "
                            "pocket depth. Turn the object so its wide end is up, or use the pocket style.")
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
    """Give the ring an underside sloping back to the board, so it prints upright."""
    zmax = bt + depth + lip_t
    bottom = reg.ring_bottom
    yf = reg.y_floor
    x0, _, x1, _ = reg.back.bounds
    # (z, y) half-plane above the line from (0, y_floor) to (zmax, bottom)
    k = CHAMFER_SLOPE
    wedge = extrude_x(Polygon([(-1, yf - k), (zmax + 1, bottom + k), (zmax + 1, BIG), (-1, BIG)]), x0 - 1, x1 + 1)

    def down(g):
        return clean(above(sweep_down(g), yf - 1))

    ring = reg.lip
    support = {
        "back plate": extrude_z(down(ring), 0.0, bt),
        "walls": extrude_z(clean(down(reg.walls).difference(reg.keepout)), bt, bt + depth),
        "lip": extrude_z(down(ring), bt + depth, zmax),
    }
    out = dict(parts)
    for k, extra in support.items():
        if extra.is_empty():
            continue
        extra = extra & wedge
        out[k] = out[k] + extra if k in out else extra
    return out
