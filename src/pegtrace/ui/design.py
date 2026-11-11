"""Step 5: holder settings, a 2D and 3D preview of the holder, and warnings."""

from __future__ import annotations

import holoviews as hv
import numpy as np
import panel as pn
import param

from ..plotting import equal_aspect
from ..preview import front_view, scene_archive, side_view, top_view_plot
from ..state import AppState
from ..vtkjs import scene_pane
from .common import FILL_WINDOW, TABS_CSS, help_text, run_busy, show, status_alert
from .diagrams import SKETCHES

PEG_FIELDS = ["preset", "spacing", "hole_d", "board_t", "peg_clear", "board_clear", "hook_rise", "hook_bend", "columns",
              "max_pegs", "stride", "add_pins", "pin_rows", "pin_length", "peg_profile", "tab_margin"]
RING_FIELDS = ["style", "ring_top", "ring_height", "object_thickness", "clear_xy", "clear_z", "wall", "back_t",
               "plate_below", "lip_t"]
FLAT_FIELDS = ["style", "object_thickness", "pocket_mode", "pocket_percent", "pocket_mm", "clear_xy", "clear_z", "wall",
               "back_t", "lip", "lip_overlap", "lip_t", "lip_height_percent", "flat_bottom", "notch", "notch_d"]
SHELF_FIELDS = ["pocket_depth", "through", "floor_t", "clear_xy", "shelf_wall", "back_t", "rim_height", "rim_t",
                "gussets", "gusset_t", "object_height"]
PLA_DENSITY = 1.24  # g/cm³


def param_panel(obj, fields, **kw):
    """Widgets for ``fields`` of ``obj``; numbers get a slider plus a box to type the value."""
    widgets = {}
    for f in fields:
        p = obj.param[f]
        if isinstance(p, param.Integer):
            widgets[f] = pn.widgets.EditableIntSlider
        elif isinstance(p, param.Number):
            widgets[f] = pn.widgets.EditableFloatSlider
    return pn.Param(obj, parameters=fields, widgets=widgets, show_name=False, sizing_mode="stretch_width", **kw)


def diagram(kind: str) -> pn.Card:
    """A labelled sketch of what the settings below it change (see diagrams.py)."""
    sketch = pn.pane.HTML(f'<div style="color: var(--panel-on-background-color, #212529)">{SKETCHES[kind]()}</div>',
                          sizing_mode="stretch_width", margin=(0, 5))
    return pn.Card(sketch, title="Diagram: what these settings change", collapsed=False,
                   sizing_mode="stretch_width", margin=(5, 5))


class DesignStep:
    title = "5 · Design"
    TAB_3D = 3

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.alert = status_alert()
        self.suggest = pn.widgets.Button(name="Suggest pocket depth", button_type="default")
        self.suggest.on_click(self._on_suggest)
        self.live3d = pn.widgets.Checkbox(name="Update 3D view live", value=True)
        self.show_board = pn.widgets.Checkbox(name="Show pegboard", value=True)
        self.show_object = pn.widgets.Checkbox(name="Show object", value=True)
        self.refresh = pn.widgets.Button(name="Refresh 3D", button_type="default")
        self.refresh.on_click(lambda _: self._update_3d(force=True))
        # VTKJS views don't redraw when only data_url changes, so each update swaps in a new pane
        self.scene_box = pn.Column(sizing_mode="stretch_both", min_height=560)
        self.scene = None
        self.views = None
        self._pending_3d = False
        self._dirty_3d = True
        self.preview = None  # the summary and views, see view()
        # Settings only mark the holder out of date (building takes seconds on the static site)
        self.update = pn.widgets.Button(name="Update holder", button_type="primary", disabled=not state.stale)
        self.update.on_click(lambda _: self._rebuild())
        state.param.watch(lambda e: setattr(self.update, "disabled", not e.new), "stale")
        self.next = pn.widgets.Button(name="Continue to export", button_type="primary")
        self.next.on_click(lambda _: self._rebuild(then=on_done) if state.stale else on_done() if on_done else None)
        self.peg_panel = param_panel(state.pegboard, PEG_FIELDS)
        self.flat_panel = param_panel(state.flat, FLAT_FIELDS)
        self.ring_panel = param_panel(state.flat, RING_FIELDS)
        self.ring_help = help_text("**Ring**: a band around a narrow part of the object, just below a wider "
                                   "part that rests on it. Hang the object wide end up (*Auto* on the "
                                   "Orientation step picks that way up). Set *Ring top* to the height on the "
                                   "object where the wide part should sit, or click that height in the "
                                   "**Front** view; the dashed red line shows it. The front bar uses the lip "
                                   "thickness.")
        # the ring top on the front view: moves with the setting at once (no rebuild needed),
        # and a click on the view sets it
        # The ring top on the front view: a plain Bokeh line moved straight from Python, so
        # it follows the setting at once (no rebuild) without HoloViews redrawing the plot
        # (which made BokehJS 3.9 lose the legend). A click on the view sets it.
        self.ring_marks = None  # (Span, Label) of the current front plot
        self.ring_tap = None  # recreated with each front view
        state.flat.param.watch(lambda e: self._move_ring_marks(), ["ring_top", "style"])
        state.param.watch(lambda e: self._move_ring_marks(), ["mode", "outline", "direction"])
        state.param.watch(lambda e: self._fit_ring_slider(), ["outline", "direction"])
        self._fit_ring_slider()
        self.shelf_panel = param_panel(state.shelf, SHELF_FIELDS)
        state.param.watch(lambda e: self._update_3d(), "result")
        for w in (self.show_board, self.show_object):
            w.param.watch(lambda e: self._update_3d(force=True), "value")

    def _ring_on(self) -> bool:
        return self.state.mode == "flat" and self.state.flat.style == "ring"

    def _ring_hook(self, plot, element):
        """HoloViews hook: add the ring top line and its label to a new front plot."""
        from bokeh.models import Label, Span

        if getattr(plot, "_ring_marks", None) is None:
            span = Span(location=0, dimension="width", line_color="#e15759", line_dash="dashed", line_width=2)
            label = Label(x=0, y=0, text="ring top", text_color="#e15759", text_font_size="10pt",
                          x_offset=4, y_offset=2)
            plot.state.add_layout(span)
            plot.state.add_layout(label)
            plot._ring_marks = (span, label)
        self.ring_marks = plot._ring_marks
        self._move_ring_marks()

    def _move_ring_marks(self):
        if self.ring_marks is None:
            return
        span, label = self.ring_marks
        o = self.state.oriented_outline()
        on = self._ring_on() and o is not None
        y = float(self.state.flat.ring_top)  # the oriented object's lowest point is y = 0
        span.update(location=y, visible=on)
        label.update(x=float(o.bounds[2]) if o is not None else 0.0, y=y, visible=on)

    def _on_front_tap(self, x=None, y=None):
        if y is None or not self._ring_on():
            return
        self.state.flat.ring_top = min(max(round(float(y) * 2) / 2, 0.5), 1000.0)

    def _fit_ring_slider(self):
        """The ring top slider spans the object's height."""
        o = self.state.oriented_outline()
        if o is None:
            return
        self.ring_panel._widgets["ring_top"].end = max(1.0, float(np.ceil(o.bounds[3] - o.bounds[1])))

    def _update_3d(self, force=False):
        """Refresh the 3D view, but only while its tab is showing, and debounced: replacing
        VTK panes in quick succession races their initialisation in the browser."""
        if self.views is None or self.views.active != self.TAB_3D:
            self._dirty_3d = True
            return
        if not (force or self.live3d.value):
            return
        if self._pending_3d:
            return
        self._pending_3d = True
        pn.state.add_periodic_callback(self._apply_3d, period=300, count=1)

    def _apply_3d(self):
        self._pending_3d = False
        self._dirty_3d = False
        r = self.state.result
        if r is None:
            self.scene = None
            self.scene_box.objects = []
            return
        archive = scene_archive(r, self.state.pegboard, show_board=self.show_board.value,
                                show_object=self.show_object.value)
        self.scene = scene_pane(archive, sizing_mode="stretch_both", min_height=560, orientation_widget=True,
                                enable_keybindings=True)
        self.scene_box.objects = [self.scene]

    def _rebuild(self, then=None):
        """Build the holder with the current settings, with a spinner over the views."""
        def work():
            self.state.rebuild()
            if then:
                then()

        run_busy(self.preview, work)

    def _on_suggest(self, _):
        pct = self.state.suggest_pocket()
        if pct is None:
            show(self.alert, "No pocket depth up to 95 % holds this shape securely; check the direction.", "warning")
        else:
            show(self.alert, f"Pocket depth set to {pct:.0f} % of the object's height.", "success")
            self._rebuild()

    def view(self):
        state = self.state

        @pn.depends(state.param.mode, state.flat.param.style)
        def holder_settings(mode, style):
            if mode == "flat" and style == "ring":
                return pn.Column(diagram("ring"), self.ring_panel, self.ring_help, sizing_mode="stretch_width")
            if mode == "flat":
                return pn.Column(diagram("pocket"), self.flat_panel, self.suggest, sizing_mode="stretch_width")
            return pn.Column(diagram("shelf"), self.shelf_panel, sizing_mode="stretch_width")

        @pn.depends(state.param.result, state.param.error)
        def summary(result, error):
            items = []
            if error:
                items.append(pn.pane.Alert(error, alert_type="danger"))
            if result is None:
                if not error:
                    items.append(help_text("Trace an outline and pick a direction to see the holder."))
                return pn.Column(*items, sizing_mode="stretch_width")
            info = result.info
            sx, sy, sz = info["size_mm"]
            grams = info["volume_cm3"] * PLA_DENSITY
            items.append(pn.pane.Markdown(
                f"**Size:** {sx:.0f} × {sy:.0f} × {sz:.0f} mm &nbsp; **Volume:** {info['volume_cm3']:.1f} cm³ "
                f"(≈ {grams:.0f} g PLA at 100 % infill) &nbsp; **Hooks:** {info['hooks']} &nbsp; "
                f"**Pins:** {info['pins']}", margin=(0, 10)))
            for w in result.warnings:
                items.append(pn.pane.Alert(w, alert_type="warning", margin=(2, 10)))
            if not result.warnings:
                items.append(pn.pane.Alert("No problems found.", alert_type="success", margin=(2, 10)))
            return pn.Column(*items, sizing_mode="stretch_width")

        def placeholder():
            return hv.Text(0, 0, "No holder yet").opts(xaxis=None, yaxis=None, responsive=True, min_height=400)

        @pn.depends(state.param.result)
        def front(result):
            if result is None:
                return placeholder()
            el = front_view(result, state.pegboard).opts(hv.opts.Overlay(hooks=[equal_aspect, self._ring_hook]))
            self.ring_tap = hv.streams.Tap(source=el, transient=True)  # click to set the ring top
            self.ring_tap.add_subscriber(self._on_front_tap)
            return el

        @pn.depends(state.param.result)
        def side(result):
            return side_view(result, state.pegboard) if result is not None else placeholder()

        @pn.depends(state.param.result)
        def top(result):
            if result is None or result.mode != "shelf":
                return hv.Text(0, 0, "Top view is for shelf mode").opts(xaxis=None, yaxis=None, responsive=True,
                                                                        min_height=400)
            return top_view_plot(result)

        views = self.views = pn.Tabs(
            ("Front", pn.pane.HoloViews(front, sizing_mode="stretch_both", min_height=560, linked_axes=False)),
            ("Side section", pn.pane.HoloViews(side, sizing_mode="stretch_both", min_height=560, linked_axes=False)),
            ("Top", pn.pane.HoloViews(top, sizing_mode="stretch_both", min_height=560, linked_axes=False)),
            ("3D", pn.Column(pn.Row(self.live3d, self.show_board, self.show_object, self.refresh),
                             self.scene_box, sizing_mode="stretch_both")),
            sizing_mode="stretch_both", dynamic=False, stylesheets=[TABS_CSS],
        )
        views.param.watch(lambda e: self._update_3d(force=True) if e.new == self.TAB_3D and self._dirty_3d
                          else None, "active")
        settings = pn.Accordion(
            ("Holder", pn.panel(holder_settings)),
            ("Pegboard and pegs", pn.Column(diagram("pegs"), self.peg_panel, sizing_mode="stretch_width")),
            active=[0, 1], sizing_mode="stretch_width",
        )
        @pn.depends(state.param.stale)
        def stale_note(stale):
            if not stale:
                return pn.Spacer(height=0)
            return pn.pane.Alert("Settings changed. Press **Update holder** to see them.", alert_type="info",
                                 margin=(0, 5))

        controls = pn.Column("### Holder settings", self.update, pn.panel(stale_note), settings, self.alert,
                             self.next, width=360, scroll=True, sizing_mode="stretch_height")
        self.preview = pn.Column(pn.panel(summary), views, sizing_mode="stretch_both")
        return pn.Row(controls, self.preview, sizing_mode="stretch_width", styles=FILL_WINDOW)
