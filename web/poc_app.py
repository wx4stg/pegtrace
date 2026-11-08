"""Static-page proof of concept: Panel + HoloViews + Manifold (JS backend in
the browser) + a .vtkjs 3D view + poly_select tracing."""

import time

import holoviews as hv
import numpy as np
import panel as pn
from shapely.geometry import box

pn.extension("vtk")
hv.extension("bokeh")

from pegtrace.csg import BACKEND, Solid  # noqa: E402
from pegtrace.holder_flat import build_flat  # noqa: E402
from pegtrace.params import FlatParams, PegboardParams  # noqa: E402
from pegtrace.vtkjs import MeshActor, hex_to_rgb, scene_bytes, scene_pane  # noqa: E402

hole = pn.widgets.FloatSlider(name="sphere radius", start=1, end=8, value=6)


@pn.depends(hole)
def volume(r):
    v = (Solid.cube((10, 10, 10), center=True) - Solid.sphere(r, 48)).volume()
    return f"**csg backend:** `{BACKEND}` &nbsp; cube minus sphere(r={r:.1f}) volume = **{v:.2f}** mm³"


# full flat-holder build through the active csg backend
hammer = box(-45, 0, 45, 28).union(box(-11, 20, 11, 160))
t0 = time.perf_counter()
result = build_flat(hammer, FlatParams(), PegboardParams())
build_s = time.perf_counter() - t0
colors = {"back plate": "#9aa5b1", "walls": "#4c78a8", "lip": "#f58518", "pegs": "#e45756"}
actors = [MeshActor(k, *s.to_mesh(), color=hex_to_rgb(colors.get(k, "#888888"))) for k, s in result.parts.items()]
actors.append(MeshActor("object", *result.ghost.to_mesh(), color=hex_to_rgb("#54a24b"), opacity=0.35))
vtk_view = scene_pane(scene_bytes(actors), height=420, sizing_mode="stretch_width",
                         orientation_widget=True, enable_keybindings=True)
summary = pn.pane.Markdown(
    f"**flat holder:** built in {build_s * 1000:.0f} ms, valid={result.solid.is_valid()}, "
    f"components={result.solid.num_components()}, volume={result.solid.volume() / 1000:.1f} cm³, "
    f"warnings={result.warnings}"
)

# poly_select -> Lasso stream (the tracing mechanism)
img = np.random.default_rng(0).integers(0, 255, (60, 80, 3), dtype=np.uint8)
rgb = hv.RGB(img, bounds=(0, 0, 80, 60)).opts(tools=["poly_select"], default_tools=["pan", "wheel_zoom", "reset"],
                                              active_tools=["poly_select"], height=300, width=400)
lasso = hv.streams.Lasso(source=rgb)
traced = pn.pane.Markdown("no polygon yet")


def on_lasso(geometry):
    if geometry is not None:
        traced.object = f"**traced polygon:** {len(geometry)} vertices, first {np.round(geometry[0], 2).tolist()}"


lasso.add_subscriber(on_lasso)

app = pn.Column(
    "# PegTrace static PoC",
    hole, pn.pane.Markdown(volume),
    summary, vtk_view,
    pn.Row(pn.pane.HoloViews(rgb), traced),
    sizing_mode="stretch_width",
)
if __name__.startswith("bokeh"):  # `panel serve`; the static page renders `app` itself
    app.servable(title="PegTrace PoC")
