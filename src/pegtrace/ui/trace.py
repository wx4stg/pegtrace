"""Step 3: trace the object outline (click vertices, drag to edit, or auto-detect)."""

from __future__ import annotations

import holoviews as hv
import numpy as np
import panel as pn
from shapely.geometry import Polygon

from ..plotting import equal_aspect, fast_taps
from ..state import AppState
from ..tracing import insert_vertex, outline_stats
from .common import FILL_WINDOW, OUTLINE_OPTS, POINT_OPTS, display_array, help_text, show, status_alert


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
        self.verts: list[tuple[float, float]] = []  # outline vertices, in order
        self.last = -1  # most recently added vertex: the next click continues from here

        self.auto = pn.widgets.Button(name="Auto-detect outline", button_type="default")
        self.undo = pn.widgets.Button(name="Remove last point", button_type="default")
        self.clear = pn.widgets.Button(name="Clear", button_type="default")
        self.done = pn.widgets.Button(name="Use this outline", button_type="primary")
        self.simplify = pn.widgets.FloatSlider.from_param(state.param.simplify_tol, name="Smooth / simplify (mm)")
        self.stats = pn.pane.Markdown("No outline yet.", margin=(5, 10))
        self.auto.on_click(self._on_auto)
        self.undo.on_click(self._on_undo)
        self.clear.on_click(self._on_clear)
        self.done.on_click(self._on_done)

        # Same tools as the scale step (drag points, dashed outline), plus adding points:
        # click to add, drag to move, select and press Backspace to delete.
        self.vert_pipe = hv.streams.Pipe(data=[])
        self.path_pipe = hv.streams.Pipe(data=[])
        self.vertices = hv.DynamicMap(lambda data: hv.Points(data, ["x", "y"]), streams=[self.vert_pipe]).opts(
            hv.opts.Points(**POINT_OPTS))
        self.path = hv.DynamicMap(lambda data: hv.Path([data]) if len(data) > 1 else hv.Path([]),
                                  streams=[self.path_pipe]).opts(hv.opts.Path(**OUTLINE_OPTS))
        self.draw = hv.streams.PointDraw(source=self.vertices, add=True, drag=True)
        self.draw.add_subscriber(self._on_draw)

        state.param.watch(self._on_outline, "outline")

    # -- display ----------------------------------------------------------------------
    def _show_outline(self):
        """Dashed outline through the vertices, closed once there are three."""
        v = np.asarray(self.verts, float).reshape(-1, 2)
        if len(v) >= 3:
            v = np.vstack([v, v[:1]])
        self.path_pipe.send(v if len(v) >= 2 else [])

    def _send_vertices(self):
        self.vert_pipe.send(list(self.verts))

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
        self.last = len(self.verts) - 1
        self._send_vertices()
        self._show_outline()

    # -- editing ----------------------------------------------------------------------
    def _snap(self) -> float:
        """How close (mm) a click must be to an edge to split it rather than extend the outline."""
        if len(self.verts) < 2:
            return 0.0
        v = np.asarray(self.verts)
        return max(1.5, 0.025 * float(np.hypot(*(v.max(0) - v.min(0)))))

    def _on_draw(self, data):
        data = data or {}
        new = [(float(x), float(y)) for x, y in zip(data.get("x", []), data.get("y", []))]
        old = self.verts
        if new == old:
            return
        if len(new) == len(old) + 1 and (not old or np.allclose(new[:-1], old)):
            # a click: the browser appends the point; put it where it belongs
            self.verts, self.last = insert_vertex(old, new[-1], self.last, self._snap())
            if self.last != len(old):
                self._send_vertices()  # keep the browser's order in step with ours
        elif len(new) == len(old) - 1:
            # Backspace on a selected vertex
            k = next((i for i, (a, b) in enumerate(zip(new, old)) if a != b), len(new))
            self.verts = new
            self.last = k - 1 if k > 0 else len(new) - 1
        else:
            self.verts = new  # dragged
        self._show_outline()
        self._commit()

    def _on_clear(self, _):
        self.verts, self.last = [], -1
        self._send_vertices()
        self._show_outline()
        self._commit()

    def _on_undo(self, _):
        if not self.verts:
            return
        i = self.last if 0 <= self.last < len(self.verts) else len(self.verts) - 1
        del self.verts[i]
        self.last = i - 1 if i > 0 else len(self.verts) - 1
        self._send_vertices()
        self._show_outline()
        self._commit()

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
            show(self.alert, "Outline detected. Check it: drag vertices to fix them, click an edge to add one.", "success")
        else:
            show(self.alert, "No object found; click around it to trace it by hand.", "warning")

    def _on_done(self, _):
        if self.state.outline is None:
            show(self.alert, "Trace the object first.", "warning")
            return
        if self.on_done:
            self.on_done()

    def view(self):
        controls = pn.Column(
            "### Trace the object",
            help_text("Like the scale step: **drag** the red points. **Click** to add a point: around the "
                      "object to draw its outline (it closes itself), or **on the dashed line** to add one "
                      "there. To delete a point, click it and press **Backspace**, or use *Remove last "
                      "point*. *Auto-detect* finds the outline for you. Include everything that sticks out."),
            pn.Row(self.auto, self.undo), self.clear, self.simplify, self.stats, self.done, self.alert,
            width=340,
        )
        # A fresh plot per calibration: with data_aspect + responsive, HoloViews does not
        # update the axis ranges of an existing plot, so streamed images would be cropped.
        @pn.depends(self.state.param.calibration)
        def plot(cal):
            rgb = cal_rgb(cal).opts(default_tools=["pan", "wheel_zoom", "reset"])
            return (rgb * self.path * self.vertices).opts(
                hv.opts.Overlay(data_aspect=1, hooks=[equal_aspect, fast_taps], responsive=True, min_height=600,
                                xlabel="x (mm)", ylabel="y (mm)", active_tools=["point_draw"]))

        return pn.Row(controls, pn.pane.HoloViews(plot, sizing_mode="stretch_both", min_height=600,
                                                  linked_axes=False),
                      sizing_mode="stretch_width", styles=FILL_WINDOW)
