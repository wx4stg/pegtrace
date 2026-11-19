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
FLAT_FIELDS = ["top_y", "bottom_y", "object_thickness", "clear_xy", "clear_z", "wall", "back_t", "plate_below",
               "lip", "lip_overlap", "lip_t", "lip_height_percent", "notch", "notch_d"]
BAND_COLORS = {"top_y": "#e15759", "bottom_y": "#4e79a7"}
BAND_LABELS = {"top_y": "Top Y", "bottom_y": "Bottom Y"}
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
        self.suggest = pn.widgets.Button(name="Suggest Top Y and Bottom Y", button_type="default")
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
        self.flat_help = help_text(
            "**Top Y** and **Bottom Y** are heights on the object, in mm above its lowest point; the dashed "
            "lines in the **Front** view show them, and a click there moves the nearer one. With Bottom Y "
            "**above 0** the object hangs through the holder: a **ring** around a narrow part, with a wider "
            "part above resting on it (set Top Y just under the wide part). At or **below 0** the space under "
            "the object is filled in: a **pocket** it sits in. A new outline or direction gets a suggestion: a "
            "ring when the object gets wider going up and a ring can hold it, else a pocket.")
        # The band's lines on the front view: plain Bokeh lines moved straight from Python, so
        # they follow the settings at once (no rebuild) without HoloViews redrawing the plot
        # (which made BokehJS 3.9 lose the legend). A click on the view moves the nearer one.
        self.band_marks = None  # {setting: (Span, Label)} of the current front plot
        self.band_tap = None  # recreated with each front view
        state.flat.param.watch(lambda *_: self._move_band_marks(), ["top_y", "bottom_y"])
        state.param.watch(lambda *_: self._move_band_marks(), ["mode", "outline", "direction"])
        state.param.watch(lambda *_: self._fit_band_sliders(), ["outline", "direction"])
        self._fit_band_sliders()
        self.shelf_panel = param_panel(state.shelf, SHELF_FIELDS)
        state.param.watch(lambda e: self._update_3d(), "result")
        for w in (self.show_board, self.show_object):
            w.param.watch(lambda e: self._update_3d(force=True), "value")

    def _band_on(self) -> bool:
        return self.state.mode == "flat"

    def _band_hook(self, plot, element):
        """HoloViews hook: add the Top Y and Bottom Y lines and labels to a new front plot."""
        from bokeh.models import Label, Span

        if getattr(plot, "_band_marks", None) is None:
            marks = {}
            for key, color in BAND_COLORS.items():
                span = Span(location=0, dimension="width", line_color=color, line_dash="dashed", line_width=2)
                label = Label(x=0, y=0, text=BAND_LABELS[key], text_color=color, text_font_size="10pt",
                              x_offset=4, y_offset=2 if key == "top_y" else -16)
                plot.state.add_layout(span)
                plot.state.add_layout(label)
                marks[key] = (span, label)
            plot._band_marks = marks
        self.band_marks = plot._band_marks
        self._move_band_marks()

    def _move_band_marks(self):
        if self.band_marks is None:
            return
        o = self.state.oriented_outline()
        on = self._band_on() and o is not None
        for key, (span, label) in self.band_marks.items():
            y = float(getattr(self.state.flat, key))  # the oriented object's lowest point is y = 0
            span.update(location=y, visible=on)
            label.update(x=float(o.bounds[2]) if o is not None else 0.0, y=y, visible=on)

    def _on_front_tap(self, x=None, y=None):
        """A click on the front view moves the nearer of Top Y and Bottom Y there."""
        if y is None or not self._band_on():
            return
        fp = self.state.flat
        y = round(float(y) * 2) / 2
        if abs(y - fp.top_y) <= abs(y - fp.bottom_y):
            fp.top_y = min(max(y, 0.5), 1000.0)
        else:
            fp.bottom_y = min(max(y, -100.0), 1000.0)

    def _fit_band_sliders(self):
        """The Top Y and Bottom Y sliders span the object's height (Bottom Y a little below it)."""
        o = self.state.oriented_outline()
        if o is None:
            return
        h = max(1.0, float(np.ceil(o.bounds[3] - o.bounds[1])))
        self.flat_panel._widgets["top_y"].end = h
        self.flat_panel._widgets["bottom_y"].param.update(start=-20.0, end=h)

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
        kind = self.state.suggest_band()
        if kind is None:
            show(self.alert, "Trace an outline first.", "warning")
            return
        fp = self.state.flat
        what = ("a ring: the object gets wider going up" if kind == "ring"
                else "a pocket: the object doesn't get wider going up enough to hang it in a ring")
        show(self.alert, f"Top Y {fp.top_y:g} mm, Bottom Y {fp.bottom_y:g} mm: {what}.", "success")
        self._rebuild()

    def view(self):
        state = self.state

        @pn.depends(state.param.mode)
        def holder_settings(mode):
            if mode == "flat":
                return pn.Column(diagram("flat"), self.flat_help, self.suggest, self.flat_panel,
                                 sizing_mode="stretch_width")
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
                (f"**{info['style'].capitalize()}** &nbsp; " if "style" in info else "") +
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
            el = front_view(result, state.pegboard).opts(hv.opts.Overlay(hooks=[equal_aspect, self._band_hook]))
            self.band_tap = hv.streams.Tap(source=el, transient=True)  # click to move Top Y or Bottom Y
            self.band_tap.add_subscriber(self._on_front_tap)
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
