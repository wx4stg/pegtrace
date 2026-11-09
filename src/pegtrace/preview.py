"""HoloViews 2D views and the .vtkjs 3D scene for a holder."""

from __future__ import annotations

import math

import holoviews as hv
import numpy as np
from shapely.geometry import Point

from .csg import Solid, elevation, section_x, top_view
from .geom2d import polygons_of, union
from .holder import HolderResult
from .params import PegboardParams
from .plotting import equal_aspect
from .vtkjs import MeshActor, hex_to_rgb, scene_bytes

PART_COLORS = {
    "back plate": "#8d99a6",
    "walls": "#3f72af",
    "lip": "#f28e2b",
    "shelf": "#3f72af",
    "rim": "#f28e2b",
    "gussets": "#59a14f",
    "pegs": "#e15759",
}
OBJECT_COLOR = "#2ca02c"
BOARD_COLOR = "#c8a97e"
DRAW_ORDER = ["back plate", "shelf", "walls", "gussets", "rim", "lip", "pegs"]


def polys_data(geom) -> list[dict]:
    """shapely geometry -> data for hv.Polygons (holes supported)."""
    out = []
    for p in polygons_of(geom):
        ext = np.asarray(p.exterior.coords)
        holes = [np.asarray(h.coords) for h in p.interiors]
        out.append({"x": ext[:, 0], "y": ext[:, 1], "holes": [holes]})
    return out


def outline_path(geom) -> hv.Path:
    paths = [np.asarray(p.exterior.coords) for p in polygons_of(geom)]
    return hv.Path(paths)


def _ordered(parts: dict[str, Solid]):
    keys = sorted(parts, key=lambda k: DRAW_ORDER.index(k) if k in DRAW_ORDER else 99)
    return [(k, parts[k]) for k in keys]


def hole_grid(result: HolderResult, pb: PegboardParams, bounds, margin: float | None = None):
    """Pegboard holes aligned with the holder's pegs, covering ``bounds``."""
    pts = result.pegs.points
    if not pts:
        return None
    ox, oy = pts[0]
    s = pb.spacing
    m = s if margin is None else margin
    x0, y0, x1, y1 = bounds
    i0, i1 = math.floor((x0 - m - ox) / s), math.ceil((x1 + m - ox) / s)
    j0, j1 = math.floor((y0 - m - oy) / s), math.ceil((y1 + m - oy) / s)
    holes = [Point(ox + i * s, oy + j * s).buffer(pb.hole_d / 2, quad_segs=6)
             for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]
    return union(holes)


def front_view(result: HolderResult, pb: PegboardParams, height: int = 520) -> hv.Overlay:
    """Looking at the board: holder silhouette per part over the hole grid."""
    layers = []
    shapes = {k: elevation(s) for k, s in _ordered(result.parts)}
    allg = union(shapes.values())
    if not allg.is_empty:
        holes = hole_grid(result, pb, allg.bounds)
        if holes is not None:
            layers.append(hv.Polygons(polys_data(holes), label="pegboard holes").opts(
                color="#d9d9d9", line_alpha=0, alpha=0.8))
    for k, g in shapes.items():
        if g.is_empty:
            continue
        alpha = 0.55 if k in ("lip", "rim") else 0.9
        layers.append(hv.Polygons(polys_data(g), label=k).opts(
            color=PART_COLORS.get(k, "#888888"), alpha=alpha, line_color="#333333", line_width=0.5))
    if result.mode == "flat":
        layers.append(outline_path(result.outline).relabel("object").opts(
            color=OBJECT_COLOR, line_width=2, line_dash="dashed"))
    else:
        layers.append(outline_path(elevation(result.ghost)).relabel("object").opts(
            color=OBJECT_COLOR, line_width=2, line_dash="dashed"))
    hooks = np.array(result.pegs.hooks) if result.pegs.hooks else np.zeros((0, 2))
    pins = np.array(result.pegs.pins) if result.pegs.pins else np.zeros((0, 2))
    layers.append(hv.Points(hooks, label="hooks").opts(color="#111111", line_color="white", marker="triangle", size=10))
    layers.append(hv.Points(pins, label="pins").opts(color="#111111", line_color="white", marker="circle", size=7))
    return hv.Overlay(layers).opts(
        hv.opts.Overlay(title="Front (looking at the board)", data_aspect=1, hooks=[equal_aspect], responsive=True,
                        min_height=height, xlabel="x (mm)", ylabel="y (mm)", legend_position="right",
                        show_grid=False, tools=["hover"], active_tools=["wheel_zoom"]))


def side_view(result: HolderResult, pb: PegboardParams, height: int = 520) -> hv.Overlay:
    """Vertical cut through the middle of the object, board on the left."""
    lo, hi = result.solid.bounds()
    if result.mode == "flat":
        xc = result.outline.centroid.x
    else:
        xc = (lo[0] + hi[0]) / 2
    cut = section_x(result.solid, xc)
    gcut = section_x(result.ghost, xc)
    board = hv.Polygons([{"x": [-pb.board_t, 0, 0, -pb.board_t], "y": [lo[1] - 15, lo[1] - 15, hi[1] + 15, hi[1] + 15]}],
                        label="pegboard").opts(color=BOARD_COLOR, alpha=0.6, line_alpha=0)
    layers = [board]
    if not gcut.is_empty:
        layers.append(hv.Polygons(polys_data(gcut), label="object").opts(color=OBJECT_COLOR, alpha=0.25, line_alpha=0))
    layers.append(hv.Polygons(polys_data(cut), label="holder").opts(color="#3f72af", alpha=0.9, line_color="#222222",
                                                                   line_width=0.5))
    # a tall, shallow cut would make a sliver of a plot: widen the z range to a sensible aspect
    y0, y1 = lo[1] - 15, hi[1] + 15
    z0, z1 = lo[2] - 5, hi[2] + 5
    want = 0.75 * (y1 - y0)
    if z1 - z0 < want:
        zc = (z0 + z1) / 2
        z0, z1 = zc - want / 2, zc + want / 2
    return hv.Overlay(layers).opts(
        hv.opts.Overlay(title=f"Side section at x = {xc:.0f} mm", data_aspect=1, hooks=[equal_aspect], responsive=True, min_height=height,
                        xlabel="z, out of the board (mm)", ylabel="y (mm)", legend_position="right",
                        xlim=(z0, z1), ylim=(y0, y1)))


def top_view_plot(result: HolderResult, height: int = 520) -> hv.Overlay:
    """Looking down (shelf mode), board along the bottom edge."""
    layers = []
    for k, s in _ordered(result.parts):
        g = top_view(s)
        if g.is_empty:
            continue
        alpha = 0.55 if k in ("rim",) else 0.9
        layers.append(hv.Polygons(polys_data(g), label=k).opts(
            color=PART_COLORS.get(k, "#888888"), alpha=alpha, line_color="#333333", line_width=0.5))
    layers.append(outline_path(result.outline).relabel("object").opts(color=OBJECT_COLOR, line_width=2,
                                                                       line_dash="dashed"))
    return hv.Overlay(layers).opts(
        hv.opts.Overlay(title="Top (board along the bottom)", data_aspect=1, hooks=[equal_aspect], responsive=True, min_height=height,
                        xlabel="x (mm)", ylabel="z, out of the board (mm)", legend_position="right"))


def board_solid(result: HolderResult, pb: PegboardParams) -> Solid:
    """A patch of pegboard behind the holder (for the 3D view)."""
    lo, hi = result.solid.bounds()
    pts = result.pegs.points
    if not pts:
        return Solid.empty()
    ox, oy = pts[0]
    s = pb.spacing
    x0 = ox + s * math.floor((lo[0] - s - ox) / s) - s / 2
    x1 = ox + s * math.ceil((hi[0] + s - ox) / s) + s / 2
    y0 = oy + s * math.floor((lo[1] - s - oy) / s) - s / 2
    y1 = oy + s * math.ceil((hi[1] + s - oy) / s) + s / 2
    from .csg import extrude_z
    from .geom2d import rect

    holes = hole_grid(result, pb, (x0, y0, x1, y1), margin=0)
    region = rect(x0, y0, x1, y1).difference(holes) if holes is not None else rect(x0, y0, x1, y1)
    return extrude_z(region, -pb.board_t, 0.0)


def scene_archive(result: HolderResult, pb: PegboardParams | None = None, show_board: bool = True,
                  show_object: bool = True, dark: bool = False) -> bytes:
    actors = []
    for k, s in _ordered(result.parts):
        v, t = s.to_mesh()
        actors.append(MeshActor(k, v, t, color=hex_to_rgb(PART_COLORS.get(k, "#888888"))))
    if show_object and not result.ghost.is_empty():
        v, t = result.ghost.to_mesh()
        actors.append(MeshActor("object", v, t, color=hex_to_rgb(OBJECT_COLOR), opacity=0.3))
    if show_board and pb is not None:
        b = board_solid(result, pb)
        if not b.is_empty():
            v, t = b.to_mesh()
            actors.append(MeshActor("pegboard", v, t, color=hex_to_rgb(BOARD_COLOR), opacity=0.35))
    bg = (0.09, 0.1, 0.12) if dark else (1.0, 1.0, 1.0)
    return scene_bytes(actors, background=bg)
