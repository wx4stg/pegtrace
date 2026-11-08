"""Shelf mode: a shelf sticks out of the board with a pocket shaped like the
object's footprint (photo taken from above, like a gridfinity insert).

The outline arrives oriented so the side that should face the board is -v
(``orient_polygon`` with the user's "toward board" direction). In 3D the
outline's (x, v) plane becomes the horizontal (x, z) plane: x along the
board, z out of the board, y up.
"""

from __future__ import annotations

from shapely import affinity
from shapely.geometry import Polygon

from .csg import Solid, extrude_x, extrude_y, extrude_z
from .geom2d import above, clean, rect, sweep_down, union
from .holder import HolderResult
from .params import PegboardParams, ShelfParams
from .pegs import layout_pegs, peg_solids


def build_shelf(outline: Polygon, sp: ShelfParams, pb: PegboardParams) -> HolderResult:
    if outline is None or outline.is_empty:
        raise ValueError("no outline to build from")
    bt = sp.back_t
    # place the outline so the shelf's board-side edge touches the back plate
    pc0 = outline.buffer(sp.clear_xy, quad_segs=12) if sp.clear_xy > 0 else outline
    outer0 = pc0.buffer(sp.shelf_wall, quad_segs=12)
    shift = bt - outer0.bounds[1]
    obj = affinity.translate(outline, 0, shift)  # (x, z) footprint
    pc = affinity.translate(pc0, 0, shift)
    outer = affinity.translate(outer0, 0, shift)
    shelf_region = above(sweep_down(outer), 0.0)  # reaches back into the plate

    slab_t = sp.pocket_depth + (0.0 if sp.through else sp.floor_t)
    pocket_bottom = -1.0 if sp.through else sp.floor_t
    xl, _, xr, zmax = shelf_region.bounds
    rim_h = sp.rim_height if sp.rim_height > 0 else 0.0
    rim_region = clean(pc.buffer(sp.rim_t, quad_segs=12).difference(pc).intersection(shelf_region))

    # pegs: hooks above the shelf (and rim), pins below them
    r = pb.peg_d / 2
    m = pb.tab_margin
    layout = layout_pegs(xl, xr, m + r, slab_t + rim_h + m + r, pb)
    top_y = max(p[1] for p in layout.points) + m + r
    back = union([rect(xl, 0, xr, top_y), layout.tab(m, 0.0)])
    rr = min(4.0, m)
    back = above(sweep_down(back.buffer(-rr).buffer(rr, quad_segs=8)), 0.0)  # round top, flat bottom

    keepout = extrude_y(pc, pocket_bottom, slab_t + rim_h + 1e3)
    parts: dict[str, Solid] = {
        "back plate": extrude_z(back, 0.0, bt),
        "shelf": extrude_y(shelf_region, 0.0, slab_t),
        "rim": extrude_y(rim_region, slab_t, slab_t + rim_h) if rim_h > 0 else Solid.empty(),
        "pegs": peg_solids(layout, pb),
    }
    if sp.gussets:
        depth = zmax - bt
        g_d = 0.85 * depth
        g_h = min(top_y - slab_t, g_d)
        if g_h > 1 and g_d > 1:
            tri = Polygon([(bt - 0.2, slab_t - 0.2), (bt - 0.2, slab_t + g_h), (bt + g_d, slab_t - 0.2)])
            prism = extrude_y(shelf_region, 0.0, top_y + 1.0)  # only where shelf is below
            g = min(sp.gusset_t, (xr - xl) / 4)
            gus = extrude_x(tri, xl, xl + g) + extrude_x(tri, xr - g, xr)
            parts["gussets"] = (gus & prism) - keepout
    parts = {k: v for k, v in parts.items() if not v.is_empty()}
    # cut the pocket from everything that could reach into it
    for k in ("shelf", "rim"):
        if k in parts:
            parts[k] = parts[k] - keepout
    solid = Solid.union_all(list(parts.values()))

    ghost = extrude_y(obj, max(pocket_bottom, 0.0), max(pocket_bottom, 0.0) + sp.object_height)

    warnings: list[str] = []
    if not layout.pins:
        warnings.append("Shelf holders lever outward; enable anti-tilt pins.")
    if len(layout.hooks) == 1:
        warnings.append("Only one hook column: the shelf can swivel. Use a wider shelf or set columns.")
    if sp.through:
        warnings.append("Through-hole: the object must have a wider part above the shelf to hang from.")
    if depth_ratio := (zmax - bt) / max(top_y, 1e-6):
        if depth_ratio > 3 and pb.add_pins:
            warnings.append("Deep shelf relative to its back plate; consider more pin rows or a bigger plate.")
    if not solid.is_valid():
        warnings.append("Geometry kernel reported an invalid solid.")
    elif solid.num_components() > 1:
        warnings.append("The holder is made of disconnected pieces; check shelf settings.")

    lo, hi = solid.bounds()
    info = {
        "size_mm": tuple(float(v) for v in (hi - lo)),
        "volume_cm3": solid.volume() / 1000.0,
        "pocket_depth_mm": sp.pocket_depth,
        "shelf_depth_mm": zmax - bt,
        "hooks": len(layout.hooks),
        "pins": len(layout.pins),
    }
    regions = {"shelf": shelf_region, "pocket": pc, "rim": rim_region, "back plate": back}
    return HolderResult(mode="shelf", solid=solid, parts=parts, regions=regions, outline=obj,
                        ghost=ghost, keepout=keepout, pegs=layout, warnings=warnings, info=info)
