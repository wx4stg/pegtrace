"""Step 4: pick the mount style and which way is down / toward the board."""

from __future__ import annotations

import holoviews as hv
import panel as pn

from ..geom2d import rect
from ..preview import OBJECT_COLOR, polys_data
from ..state import AppState
from ..tracing import orient_polygon
from .common import arrow, help_text

MODE_LABELS = {"Flat against the board": "flat", "Shelf (top-down footprint)": "shelf"}


class OrientStep:
    title = "4 · Orientation"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.mode = pn.widgets.RadioButtonGroup(options=list(MODE_LABELS), value="Flat against the board",
                                                button_type="default")
        self.mode.param.watch(lambda e: setattr(state, "mode", MODE_LABELS[e.new]), "value")
        state.param.watch(self._sync_mode, "mode")
        self.angle = pn.widgets.FloatSlider.from_param(state.param.direction, name="Direction (degrees)")
        self.buttons = pn.Row(*[self._dir_button(lbl, ang) for lbl, ang in
                                (("↓", 270), ("←", 180), ("→", 0), ("↑", 90))])
        self.auto = pn.widgets.Button(name="Auto: long axis vertical", button_type="default")
        self.auto.on_click(lambda _: state.auto_direction())
        self.next = pn.widgets.Button(name="Continue to design", button_type="primary")
        self.next.on_click(lambda _: on_done() if on_done else None)

    def _dir_button(self, label, angle):
        b = pn.widgets.Button(name=label, width=50, button_type="default")
        b.on_click(lambda _: setattr(self.state, "direction", float(angle)))
        return b

    def _sync_mode(self, event):
        label = next(k for k, v in MODE_LABELS.items() if v == event.new)
        if self.mode.value != label:
            self.mode.value = label

    def view(self):
        state = self.state

        @pn.depends(state.param.outline, state.param.direction, state.param.mode)
        def photo_view(outline, direction, mode):
            if outline is None:
                return hv.Text(0, 0, "Trace an outline first").opts(xaxis=None, yaxis=None)
            x0, y0, x1, y1 = outline.bounds
            c = outline.centroid
            size = max(x1 - x0, y1 - y0)
            arr = arrow(c.x, c.y, direction, size * 0.45)
            label = "down" if mode == "flat" else "toward the board"
            return (hv.Polygons(polys_data(outline)).opts(color=OBJECT_COLOR, alpha=0.35, line_color=OBJECT_COLOR)
                    * hv.Polygons(polys_data(arr)).opts(color="#e15759", line_alpha=0)
                    ).opts(title=f"In the photo: arrow = {label}", data_aspect=1, responsive=True, min_height=420,
                           xlabel="x (mm)", ylabel="y (mm)")

        @pn.depends(state.param.outline, state.param.direction, state.param.mode)
        def frame_view(outline, direction, mode):
            if outline is None:
                return hv.Text(0, 0, "").opts(xaxis=None, yaxis=None)
            o = orient_polygon(outline, direction)
            x0, y0, x1, y1 = o.bounds
            w, h = x1 - x0, y1 - y0
            if mode == "flat":
                board = rect(x0 - 0.3 * w - 10, y0 - 6, x1 + 0.3 * w + 10, y0 - 3)
                title, xl, yl = "As it will hang (front view)", "x (mm)", "y, up (mm)"
                arr = arrow(x1 + 0.25 * w + 8, y0 + 0.75 * h, 270, 0.4 * h)
                note = hv.Text(x1 + 0.25 * w + 8, y0 + 0.82 * h, "gravity").opts(text_font_size="9pt")
            else:
                board = rect(x0 - 0.3 * w - 10, y0 - 9, x1 + 0.3 * w + 10, y0 - 3)
                title, xl, yl = "Footprint on the shelf (top view)", "x (mm)", "z, out of the board (mm)"
                arr = arrow(x1 + 0.25 * w + 8, y0 + 0.75 * h, 270, 0.4 * h)
                note = hv.Text(x1 + 0.25 * w + 8, y0 + 0.82 * h, "board").opts(text_font_size="9pt")
            return (hv.Polygons(polys_data(board)).opts(color="#c8a97e", line_alpha=0)
                    * hv.Polygons(polys_data(o)).opts(color=OBJECT_COLOR, alpha=0.35, line_color=OBJECT_COLOR)
                    * hv.Polygons(polys_data(arr)).opts(color="#888888", line_alpha=0) * note
                    ).opts(title=title, data_aspect=1, responsive=True, min_height=420, xlabel=xl, ylabel=yl)

        controls = pn.Column(
            "### Mount style",
            self.mode,
            help_text("**Flat**: the object hangs against the board in a cradle and lifts out upward. "
                      "**Shelf**: the outline is a pocket in a shelf sticking out from the board "
                      "(use a photo taken from above the object as it should sit)."),
            "### Direction",
            help_text("Set the arrow: in **Flat** mode it points *down*; in **Shelf** mode it points "
                      "*toward the board*."),
            self.buttons, self.angle, self.auto, self.next,
            width=340,
        )
        return pn.Row(controls,
                      pn.Row(pn.pane.HoloViews(photo_view, sizing_mode="stretch_both", linked_axes=False),
                             pn.pane.HoloViews(frame_view, sizing_mode="stretch_both", linked_axes=False), sizing_mode="stretch_both"),
                      sizing_mode="stretch_width")
