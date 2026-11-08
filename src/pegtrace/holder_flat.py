"""Flat mode: the object hangs flat against the board in a shaped cradle.

Frame: x along the board, y up (against gravity), z out of the board. The
object outline ``P`` lies in the xy plane, resting against the back plate.

Key idea: ``U = sweep_up(Pc)`` is every point the (clearance-grown) outline
passes through while being lifted straight up and out. Walls never enter U,
so the object can always be removed upwards and the cavity has no overhangs
when printed upright.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point, Polygon

from .csg import Solid, extrude_z
from .geom2d import above, below, clean, sweep_down, sweep_up, union
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


def pocket_top(pc: Polygon, fp: FlatParams) -> float:
    _, y0, _, y1 = pc.bounds
    height = y1 - y0
    depth = fp.pocket_percent / 100 * height if fp.pocket_mode == "percent" else fp.pocket_mm
    return y0 + min(max(depth, 0.5), height)


def flat_regions(outline: Polygon, fp: FlatParams, pb: PegboardParams) -> FlatRegions:
    """All 2D regions of a flat holder (cheap; no 3D work)."""
    pc = outline.buffer(fp.clear_xy, quad_segs=12) if fp.clear_xy > 0 else outline
    h = pocket_top(pc, fp)
    u = sweep_up(pc)
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
    parts = {k: v for k, v in parts.items() if not v.is_empty()}
    solid = Solid.union_all(list(parts.values()))

    keepout = extrude_z(below(reg.keepout, reg.pocket_top + 1e3), bt, bt + depth)
    ghost = extrude_z(outline, bt, bt + fp.object_thickness)

    warnings: list[str] = []
    stab = check_flat(outline, reg.walls)
    warnings.extend(stab.messages)
    if reg.pocket_top - reg.grown.bounds[1] < 2 * fp.wall:
        warnings.append("Pocket is very shallow; increase the pocket depth.")
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
