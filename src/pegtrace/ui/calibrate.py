"""Step 2: mark the scale reference (paper corners or two ruler points)."""

from __future__ import annotations

import holoviews as hv
import numpy as np
import panel as pn

from ..calibration import order_corners
from ..plotting import equal_aspect
from ..state import CUSTOM, RECT, RULER, AppState
from .common import FILL_WINDOW, help_text, photo_rgb, show, status_alert

POINT_OPTS = dict(color="#e15759", size=12, line_color="white", line_width=2)


class CalibrateStep:
    title = "2 · Scale"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.alert = status_alert()
        self._from_draw = False

        self.method = pn.widgets.RadioButtonGroup.from_param(state.param.cal_method, button_type="default")
        self.paper = pn.widgets.Select.from_param(state.param.paper, name="Reference size")
        self.custom_w = pn.widgets.FloatInput.from_param(state.param.custom_w, name="Width (mm)", width=140)
        self.custom_h = pn.widgets.FloatInput.from_param(state.param.custom_h, name="Height (mm)", width=140)
        self.ruler_mm = pn.widgets.FloatInput.from_param(state.param.ruler_mm, name="Distance between points (mm)")
        self.ppm = pn.widgets.FloatSlider.from_param(state.param.px_per_mm, name="Resolution (px per mm)")
        self.find = pn.widgets.Button(name="Find paper automatically", button_type="default")
        self.apply = pn.widgets.Button(name="Apply scale", button_type="primary")
        self.find.on_click(self._on_find)
        self.apply.on_click(self._on_apply)

        self.corner_pipe = hv.streams.Pipe(data=[])
        self.ruler_pipe = hv.streams.Pipe(data=[])
        self.quad_pipe = hv.streams.Pipe(data=[])
        corners = hv.DynamicMap(lambda data: hv.Points(data, ["x", "y"]), streams=[self.corner_pipe]).opts(
            hv.opts.Points(**POINT_OPTS))
        ruler = hv.DynamicMap(lambda data: hv.Points(data, ["x", "y"]), streams=[self.ruler_pipe]).opts(
            hv.opts.Points(**{**POINT_OPTS, "color": "#4e79a7"}))
        quad = hv.DynamicMap(lambda data: hv.Path([data]) if len(data) > 1 else hv.Path([]),
                             streams=[self.quad_pipe]).opts(hv.opts.Path(color="#e15759", line_width=2,
                                                                         line_dash="dashed"))
        self.corner_draw = hv.streams.PointDraw(source=corners, num_objects=4, add=True, drag=True)
        self.ruler_draw = hv.streams.PointDraw(source=ruler, num_objects=2, add=True, drag=True)
        self.corner_draw.add_subscriber(self._on_corner_draw)
        self.ruler_draw.add_subscriber(self._on_ruler_draw)
        self.corners_layer = quad * corners
        self.ruler_layer = ruler

        state.param.watch(self._on_photo, "photo")
        state.param.watch(self._on_points, ["corners_px", "ruler_px"])

    # display <-> photo pixels: y flips
    def _to_display(self, pts):
        h = self.state.photo.size[1] if self.state.photo is not None else 0
        return [(float(x), float(h - y)) for x, y in pts]

    def _from_display(self, data):
        h = self.state.photo.size[1] if self.state.photo is not None else 0
        xs, ys = data.get("x", []), data.get("y", [])
        return [(float(x), float(h - y)) for x, y in zip(xs, ys)]

    def _send_quad(self, pts):
        if len(pts) == 4:
            c = order_corners(np.asarray(pts))
            disp = self._to_display(np.vstack([c, c[:1]]))
            self.quad_pipe.send(np.asarray(disp))
        else:
            self.quad_pipe.send([])

    def _on_photo(self, event):
        self._on_points()

    def _on_points(self, *events):
        if self._from_draw:  # the browser already shows these points
            return
        self.corner_pipe.send(self._to_display(self.state.corners_px))
        self.ruler_pipe.send(self._to_display(self.state.ruler_px))
        self._send_quad(self.state.corners_px)

    def _on_corner_draw(self, data):
        pts = self._from_display(data or {})
        self._from_draw = True
        try:
            self.state.corners_px = pts
        finally:
            self._from_draw = False
        self._send_quad(pts)

    def _on_ruler_draw(self, data):
        self._from_draw = True
        try:
            self.state.ruler_px = self._from_display(data or {})
        finally:
            self._from_draw = False

    def _on_find(self, _):
        if self.state.photo is None:
            show(self.alert, "Load a photo first.", "warning")
            return
        self.state.guess_reference()
        show(self.alert, self.state.message, "info")

    def _on_apply(self, _):
        try:
            cal = self.state.calibrate()
        except Exception as e:
            show(self.alert, str(e), "danger")
            return
        l, b, r, t = cal.bounds
        notes = (" " + " ".join(cal.notes)) if cal.notes else ""
        show(self.alert, f"Scale applied: image covers {r - l:.0f} × {t - b:.0f} mm "
                         f"at {cal.px_per_mm:.1f} px/mm.{notes}", "success")
        if self.on_done:
            self.on_done()

    def view(self):
        @pn.depends(self.state.param.cal_method, self.state.param.paper)
        def settings(method, paper):
            if method == RECT:
                rows = [help_text("Drag the **red points** onto the four corners of the paper (any order). "
                                  "Click to add a point if one is missing."),
                        self.paper]
                if paper == CUSTOM:
                    rows.append(pn.Row(self.custom_w, self.custom_h))
                rows.append(self.find)
            else:
                rows = [help_text("Drag the **two blue points** onto ruler marks a known distance apart. "
                                  "Without a rectangle there is no perspective correction, so shoot "
                                  "straight down."),
                        self.ruler_mm]
            return pn.Column(*rows, sizing_mode="stretch_width")

        # A fresh plot per photo (see TraceStep.view); the editable point layers are reused.
        @pn.depends(self.state.param.cal_method, self.state.param.photo)
        def plot(method, photo):
            layer = self.corners_layer if method == RECT else self.ruler_layer
            obj = (photo_rgb(photo).opts(default_tools=["pan", "wheel_zoom", "reset"]) * layer).opts(
                hv.opts.Overlay(data_aspect=1, hooks=[equal_aspect], responsive=True, min_height=560, xaxis=None, yaxis=None,
                                active_tools=["point_draw"]))
            return pn.pane.HoloViews(obj, sizing_mode="stretch_both", min_height=560, linked_axes=False)

        controls = pn.Column("### Scale reference", self.method, settings, self.ppm, self.apply, self.alert,
                             width=340)
        return pn.Row(controls, plot, sizing_mode="stretch_width", styles=FILL_WINDOW)
