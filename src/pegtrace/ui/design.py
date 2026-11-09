"""Step 5: holder settings with live 2D views, warnings and a 3D view."""

from __future__ import annotations

import holoviews as hv
import panel as pn

from ..preview import front_view, scene_archive, side_view, top_view_plot
from ..state import AppState
from ..vtkjs import scene_pane
from .common import FILL_WINDOW, TABS_CSS, help_text, run_busy, show, status_alert

PEG_FIELDS = ["preset", "spacing", "hole_d", "board_t", "peg_clear", "board_clear", "hook_rise", "columns",
              "max_pegs", "stride", "add_pins", "pin_rows", "pin_length", "peg_profile", "tab_margin"]
RING_FIELDS = ["style", "ring_auto", "ring_height", "object_thickness", "pocket_mode", "pocket_percent",
               "pocket_mm", "clear_xy", "clear_z", "wall", "back_t", "lip_t"]
FLAT_FIELDS = ["style", "object_thickness", "pocket_mode", "pocket_percent", "pocket_mm", "clear_xy", "clear_z", "wall",
               "back_t", "lip", "lip_overlap", "lip_t", "lip_height_percent", "flat_bottom", "notch", "notch_d"]
SHELF_FIELDS = ["pocket_depth", "through", "floor_t", "clear_xy", "shelf_wall", "back_t", "rim_height", "rim_t",
                "gussets", "gusset_t", "object_height"]
PLA_DENSITY = 1.24  # g/cm³


def param_panel(obj, fields, **kw):
    return pn.Param(obj, parameters=fields, show_name=False, sizing_mode="stretch_width", **kw)


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
                                   "Orientation step picks that way up). With *Place ring automatically* off, "
                                   "the ring top is at the pocket depth. The front bar uses the lip thickness.")
        self.shelf_panel = param_panel(state.shelf, SHELF_FIELDS)
        state.param.watch(lambda e: self._update_3d(), "result")
        for w in (self.show_board, self.show_object):
            w.param.watch(lambda e: self._update_3d(force=True), "value")

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
                                show_object=self.show_object.value, dark=self.state.theme == "dark")
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
                return pn.Column(self.ring_panel, self.ring_help, sizing_mode="stretch_width")
            if mode == "flat":
                return pn.Column(self.flat_panel, self.suggest, sizing_mode="stretch_width")
            return pn.Column(self.shelf_panel, sizing_mode="stretch_width")

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
            return front_view(result, state.pegboard) if result is not None else placeholder()

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
            ("Pegboard and pegs", self.peg_panel),
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
