"""Step 3: trace the object outline (draw a polygon, edit its vertices, or auto-detect)."""

from __future__ import annotations

import holoviews as hv
import numpy as np
import panel as pn
from shapely.geometry import Polygon

from ..plotting import equal_aspect, fast_taps, poly_flow
from ..state import AppState
from ..tracing import outline_stats
from .common import FILL_WINDOW, display_array, help_text, show, status_alert


def cal_rgb(data) -> hv.RGB:
    """Calibrated image in mm (``data`` is a Calibration, as sent through a Pipe)."""
    cal = data
    if cal is None:
        return hv.RGB(np.full((2, 2, 3), 240, np.uint8), bounds=(0, 0, 1, 1))
    return hv.RGB(display_array(cal.image, 1400), bounds=cal.bounds)


VERTEX_STYLE = dict(fill_color="#e15759", size=12, line_color="white", line_width=2)
OUTLINE_STYLE = dict(fill_color="#e15759", fill_alpha=0.08, line_color="#e15759", line_width=2, line_dash="dashed")


def ring_vertices(xs, ys, tol: float = 1e-3) -> list[tuple[float, float]]:
    """Vertices of a polygon drawn in the browser, without repeats: while drawing, Bokeh keeps
    a copy of the last point under the cursor, and finishing or inserting can add another."""
    out: list[tuple[float, float]] = []
    for x, y in zip(xs, ys):
        p = (float(x), float(y))
        if not (np.isfinite(p[0]) and np.isfinite(p[1])):
            continue
        if out and abs(p[0] - out[-1][0]) <= tol and abs(p[1] - out[-1][1]) <= tol:
            continue
        out.append(p)
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) <= tol and abs(out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


class TraceStep:
    title = "3 · Trace"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.alert = status_alert()
        self._from_edit = False
        self.verts: list[tuple[float, float]] = []  # outline vertices, in order

        self.auto = pn.widgets.Button(name="Auto-detect outline", button_type="default")
        self.clear = pn.widgets.Button(name="Clear", button_type="default")
        self.done = pn.widgets.Button(name="Use this outline", button_type="primary")
        self.simplify = pn.widgets.FloatSlider.from_param(state.param.simplify_tol, name="Smooth / simplify (mm)")
        self.stats = pn.pane.Markdown("No outline yet.", margin=(5, 10))
        self.auto.on_click(self._on_auto)
        self.clear.on_click(self._on_clear)
        self.done.on_click(self._on_done)

        # Bokeh's polygon tools: PolyDraw draws the outline (one at a time), PolyEdit moves,
        # inserts and deletes its vertices. The browser draws everything itself; Python
        # only hears about the result (see plotting.poly_flow for the hand-over between them).
        self.poly_pipe = hv.streams.Pipe(data=[])
        self.poly = hv.DynamicMap(lambda data: hv.Polygons([data] if len(data) else []),
                                  streams=[self.poly_pipe]).opts(hv.opts.Polygons(**OUTLINE_STYLE))
        self.draw = hv.streams.PolyDraw(source=self.poly, num_objects=1, drag=False, show_vertices=True,
                                        vertex_style=VERTEX_STYLE)
        self.edit = hv.streams.PolyEdit(source=self.poly, vertex_style=VERTEX_STYLE, shared=True)
        self.draw.add_subscriber(self._on_draw)
        self.edit.add_subscriber(self._on_draw)

        state.param.watch(self._on_outline, "outline")

    # -- display ----------------------------------------------------------------------
    def _send(self):
        self.poly_pipe.send(np.asarray(self.verts, float).reshape(-1, 2) if self.verts else [])

    def _on_outline(self, event):
        p = event.new
        st = outline_stats(p)
        if p is None:
            self.stats.object = "No outline yet."
        else:
            self.stats.object = (f"**Outline:** {st['width']:.1f} × {st['height']:.1f} mm, "
                                 f"area {st['area'] / 100:.1f} cm², {st['vertices']} vertices")
        if self._from_edit:  # the browser already shows these vertices
            return
        self.verts = [] if p is None else [tuple(c) for c in np.asarray(p.exterior.coords)[:-1]]
        self._send()

    # -- editing ----------------------------------------------------------------------
    def _on_draw(self, data):
        data = data or {}
        xs, ys = data.get("xs") or [], data.get("ys") or []
        verts = ring_vertices(xs[-1], ys[-1]) if len(xs) else []
        if verts == self.verts:
            return
        self.verts = verts
        self._commit()

    def _on_clear(self, _):
        self.verts = []
        # Commit first: clearing the outline changes the layout of later steps, and BokehJS 3.9
        # repaints on layout changes straight away, before a polygon emptied earlier in the same
        # update has re-indexed its data ("Out of bounds: 0 <= 0 < 0").
        self._commit()
        self._send()

    def _commit(self):
        """Hand the vertices to the app state as the outline (3 or more points)."""
        self._from_edit = True
        try:
            if len(self.verts) < 3:
                if self.state.raw_outline is not None:
                    self.state.set_outline(None)
                return
            self.state.set_outline(Polygon(self.verts), simplify=False)
        finally:
            self._from_edit = False

    def _on_auto(self, _):
        try:
            ok = self.state.autodetect()
        except Exception as e:
            show(self.alert, str(e), "danger")
            return
        if ok:
            show(self.alert, "Outline detected. Check it, and drag points to fix it.", "success")
        else:
            show(self.alert, "No object found; draw around it by hand.", "warning")

    def _on_done(self, _):
        if self.state.outline is None:
            show(self.alert, "Trace the object first.", "warning")
            return
        if self.on_done:
            self.on_done()

    def view(self):
        controls = pn.Column(
            "### Trace the object",
            help_text("**Draw:** press and hold to place the first point, click around the object to add "
                      "more, then press **Esc** (or press and hold for the last point) to finish. "
                      "*Auto-detect* draws it for you. Include everything that sticks out."),
            help_text("**Adjust:** drag the red points. To add points, press and hold a point, click "
                      "where the new ones go, and press **Esc**. To delete one, click it and press "
                      "**Backspace**. To start over, press *Clear*."),
            pn.Row(self.auto, self.clear), self.simplify, self.stats, self.done, self.alert,
            width=340,
        )
        # A fresh plot per calibration: with data_aspect + responsive, HoloViews does not
        # update the axis ranges of an existing plot, so streamed images would be cropped.
        @pn.depends(self.state.param.calibration)
        def plot(cal):
            rgb = cal_rgb(cal).opts(default_tools=["pan", "wheel_zoom", "reset"])
            return (rgb * self.poly).opts(
                hv.opts.Overlay(data_aspect=1, hooks=[equal_aspect, fast_taps, poly_flow], responsive=True,
                                min_height=600, xlabel="x (mm)", ylabel="y (mm)", active_tools=["poly_draw"]))

        return pn.Row(controls, pn.pane.HoloViews(plot, sizing_mode="stretch_both", min_height=600,
                                                  linked_axes=False),
                      sizing_mode="stretch_width", styles=FILL_WINDOW)
