"""Step 3: trace the object outline (poly_select, vertex editing, auto-detect)."""

from __future__ import annotations

import holoviews as hv
import numpy as np
import panel as pn
from shapely.geometry import Polygon

from ..plotting import equal_aspect, fast_taps, safe_patches
from ..state import AppState
from ..tracing import outline_stats
from .common import FILL_WINDOW, display_array, help_text, run_busy, show, status_alert


def cal_rgb(data) -> hv.RGB:
    """Calibrated image in mm (``data`` is a Calibration, as sent through a Pipe)."""
    cal = data
    if cal is None:
        return hv.RGB(np.full((2, 2, 3), 240, np.uint8), bounds=(0, 0, 1, 1))
    return hv.RGB(display_array(cal.image, 1400), bounds=cal.bounds)


class TraceStep:
    title = "3 · Trace"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.alert = status_alert()
        self._from_edit = False

        self.auto = pn.widgets.Button(name="Auto-detect outline", button_type="default")
        self.clear = pn.widgets.Button(name="Clear", button_type="default")
        self.done = pn.widgets.Button(name="Use this outline", button_type="primary")
        self.simplify = pn.widgets.FloatSlider.from_param(state.param.simplify_tol, name="Smooth / simplify (mm)")
        self.stats = pn.pane.Markdown("No outline yet.", margin=(5, 10))
        self.auto.on_click(self._on_auto)
        self.clear.on_click(lambda _: run_busy(self.plot_pane, lambda: state.set_outline(None)))
        self.done.on_click(self._on_done)

        self.poly_pipe = hv.streams.Pipe(data=[])
        self.polys = hv.DynamicMap(lambda data: hv.Polygons(data), streams=[self.poly_pipe]).opts(
            hv.opts.Polygons(fill_alpha=0.15, fill_color="#e15759", line_color="#e15759", line_width=2))
        self.edit = hv.streams.PolyEdit(source=self.polys, vertex_style={"color": "#e15759", "size": 8},
                                        shared=True, show_vertices=True)
        self.edit.add_subscriber(self._on_edit)
        self.lasso = None  # recreated with each image, see view()
        self.plot_pane = None  # see view()

        state.param.watch(self._on_outline, "outline")

    def _on_outline(self, event):
        p = event.new
        st = outline_stats(p)
        if p is None:
            self.stats.object = "No outline yet."
        else:
            self.stats.object = (f"**Outline:** {st['width']:.1f} × {st['height']:.1f} mm, "
                                 f"area {st['area'] / 100:.1f} cm², {st['vertices']} vertices")
        if self._from_edit:
            return
        self._send(np.zeros((0, 2)) if p is None else np.asarray(p.exterior.coords)[:-1])

    def _send(self, coords):
        self.poly_pipe.send([{"x": coords[:, 0], "y": coords[:, 1]}] if len(coords) else [])

    def _on_lasso(self, geometry):
        if geometry is None or len(geometry) < 3:
            return
        coords = np.asarray(geometry, float)
        # the selection vanishes when it closes: show it straight away, while the holder updates
        self._send(coords)

        def apply():
            self.state.set_outline(Polygon(coords))
            show(self.alert, "Outline traced. Drag the red vertices to refine it.", "success")

        run_busy(self.plot_pane, apply)

    def _on_edit(self, data):
        if not data or not data.get("xs"):
            return
        xs, ys = data["xs"][0], data["ys"][0]
        if len(xs) < 3:
            return
        poly = Polygon(np.column_stack([xs, ys]))
        cur = self.state.outline
        if cur is not None and poly.symmetric_difference(cur).area < 1e-6:
            return

        def apply():
            self._from_edit = True
            try:
                self.state.set_outline(poly, simplify=False)  # keep exactly what the user edited
            finally:
                self._from_edit = False

        run_busy(self.plot_pane, apply)

    def _on_auto(self, _):
        run_busy(self.plot_pane, self._autodetect)

    def _autodetect(self):
        try:
            ok = self.state.autodetect()
        except Exception as e:
            show(self.alert, str(e), "danger")
            return
        if ok:
            show(self.alert, "Outline detected. Check it, and fix any vertices by dragging them.", "success")
        else:
            show(self.alert, "No object found; trace it by hand with the polygon tool.", "warning")

    def _on_done(self, _):
        if self.state.outline is None:
            show(self.alert, "Trace the object first.", "warning")
            return
        if self.on_done:
            self.on_done()

    def view(self):
        controls = pn.Column(
            "### Trace the object",
            help_text("Use the **polygon select** tool: click around the object's outline, then press "
                      "**Enter** (or press and hold the mouse) to close it. Or press *Auto-detect*.\n\n"
                      "Once a polygon is created manually or via auto-detect, use the **poly edit** tool "
                      "(far right of the image) to edit the vertices (click and hold on the red "
                      "selection polygon to make the vertices appear)."),
            pn.Row(self.auto, self.clear), self.simplify, self.stats, self.done, self.alert,
            width=340,
        )
        # A fresh plot per calibration: HoloViews does not update the axis ranges of an
        # existing responsive plot, so streamed images would be cropped.
        @pn.depends(self.state.param.calibration)
        def plot(cal):
            rgb = cal_rgb(cal).opts(tools=["poly_select"], default_tools=["pan", "wheel_zoom", "reset"])
            self.lasso = hv.streams.Lasso(source=rgb)
            self.lasso.add_subscriber(self._on_lasso)
            return (rgb * self.polys).opts(
                hv.opts.Overlay(hooks=[equal_aspect, fast_taps, safe_patches], responsive=True, min_height=600, xlabel="x (mm)", ylabel="y (mm)",
                                active_tools=["poly_select"]))

        self.plot_pane = pn.pane.HoloViews(plot, sizing_mode="stretch_both", min_height=600, linked_axes=False)
        return pn.Row(controls, self.plot_pane,
                      sizing_mode="stretch_width", styles=FILL_WINDOW)
