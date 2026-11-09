"""Bokeh plot helpers shared by the UI and the previews."""

from __future__ import annotations

from bokeh.models import CustomJS, Range1d

# Re-fit the ranges so one data unit has the same length on both axes, showing all of `box`.
# Runs in the browser whenever the plot is resized or reset, or the box changes.
_FIT_JS = """
const fit = () => {
  let fw, fh;
  try { fw = plot.inner_width; fh = plot.inner_height; } catch (e) { return; }  // not laid out yet
  if (!(fw > 0 && fh > 0) || bx.start == null || by.start == null) return;
  const s = Math.max((bx.end - bx.start) / fw, (by.end - by.start) / fh);
  if (!(s > 0)) return;
  const cx = (bx.start + bx.end) / 2, cy = (by.start + by.end) / 2;
  plot.x_range.setv({start: cx - s * fw / 2, end: cx + s * fw / 2});
  plot.y_range.setv({start: cy - s * fh / 2, end: cy + s * fh / 2});
};
fit();
setTimeout(fit, 0);  // after a reset, the reset tool restores the ranges first
"""


def equal_aspect(plot, element) -> None:
    """HoloViews hook: keep 1:1 data aspect in a responsive plot.

    HoloViews' ``data_aspect`` only adjusts responsive plots after a server round trip
    reports the plot size, which never happens in a static page (and not reliably with
    ``panel serve``), so wide windows stretched the image. This fits the ranges in the
    browser instead.
    """
    fig = plot.state
    l, b, r, t = (float(v) for v in plot.get_extents(element, plot.current_ranges))
    holders = getattr(plot, "_equal_aspect", None)
    if holders is None:
        bx, by = Range1d(start=l, end=r), Range1d(start=b, end=t)
        cb = CustomJS(args=dict(plot=fig, bx=bx, by=by), code=_FIT_JS)
        fig.js_on_change("inner_width", cb)
        fig.js_on_change("inner_height", cb)
        fig.js_on_event("reset", cb)
        bx.js_on_change("end", cb)
        by.js_on_change("end", cb)
        plot._equal_aspect = (bx, by)
    else:
        bx, by = holders
        bx.update(start=l, end=r)
        by.update(start=b, end=t)


# Bokeh turns a second tap within 300 ms into a "doubletap", which the draw and edit tools
# ignore, so clicking points at a normal pace silently dropped every other one. Treat it as a tap.
_FAST_TAPS_JS = """
if (!globalThis.__pegtrace_fast_taps) {
  for (const [path, view] of [["point_draw_tool", "PointDrawToolView"], ["poly_draw_tool", "PolyDrawToolView"],
                              ["poly_edit_tool", "PolyEditToolView"]]) {
    Bokeh.require("models/tools/edit/" + path)[view].prototype._doubletap = function (ev) { this._tap(ev); };
  }
  globalThis.__pegtrace_fast_taps = true;
}
"""


def fast_taps(plot, element) -> None:
    """HoloViews hook for plots with draw/edit tools: every click counts."""
    if getattr(plot, "_fast_taps", False):
        return
    plot.state.js_on_change("inner_width", CustomJS(code=_FAST_TAPS_JS))
    plot._fast_taps = True


# One outline, drawn with PolyDrawTool and adjusted with PolyEditTool. Stock Bokeh makes you
# switch tools in the toolbar and press-and-hold the shape before its vertices show up; here
# the edit tool takes over (vertices showing) as soon as an outline exists, and the draw tool
# comes back when there is none.
_POLY_FLOW_JS = """
if (!globalThis.__pegtrace_poly_flow) {
  const draw = Bokeh.require("models/tools/edit/poly_draw_tool");
  const edit = Bokeh.require("models/tools/edit/poly_edit_tool");
  const sibling = (view, cls) => view.plot_view.model.toolbar.tools.find((t) => t instanceof cls);
  const n_vertices = (r) => {
    const xs = r.data_source.data.get?.("xs") ?? r.data_source.data.xs ?? [];
    return xs.length ? xs[xs.length - 1].length : 0;
  };
  // the draw tool hands over when a shape is finished (press, or Esc) or set from Python
  const after_draw = (view) => {
    const r = view.model.renderers[0];
    const e = sibling(view, edit.PolyEditTool);
    if (r != null && e != null && view.model.active && !view._drawing && n_vertices(r) >= 3) {
      e.active = true;
    }
  };
  const D = draw.PolyDrawToolView.prototype;
  const d_press = D._press, d_keyup = D._keyup, d_activate = D.activate;
  // later, not now: Esc goes to every tool, and the edit tool would hide its fresh vertices
  D._press = function (ev) { d_press.call(this, ev); setTimeout(() => after_draw(this), 0); };
  D._keyup = function (ev) { d_keyup.call(this, ev); setTimeout(() => after_draw(this), 0); };
  D.activate = function () {
    d_activate.call(this);
    const r = this.model.renderers[0];
    if (r != null && !this.__pegtrace_watch) {
      this.__pegtrace_watch = true;
      r.data_source.connect(r.data_source.properties.data.change, () => setTimeout(() => after_draw(this), 0));
    }
    after_draw(this);
  };
  // the edit tool shows the vertices straight away and keeps them in step with the data
  const E = edit.PolyEditToolView.prototype;
  E.activate = function () {
    const r = this.model.renderers[0];
    if (r == null) return;
    const show = () => {
      if (!this.model.active || this._drawing) return;
      const n = r.data_source.get_length() ?? 0;
      if (n_vertices(r) == 0) {
        this._set_vertices([], []);
        this._selected_renderer = null;
        this._cur_index = null;
        const d = sibling(this, draw.PolyDrawTool);
        if (d != null) d.active = true;
        return;
      }
      // HoloViews closes rings it sends (first point repeated last): one vertex, not two stacked
      const data = r.data_source.data, get = (k) => data.get?.(k) ?? data[k];
      const xs = get("xs"), ys = get("ys"), x = xs[n - 1], y = ys[n - 1], m = x.length;
      if (m > 3 && x[0] == x[m - 1] && y[0] == y[m - 1]) {
        xs[n - 1] = Array.from(x).slice(0, -1);
        ys[n - 1] = Array.from(y).slice(0, -1);
        r.data_source.change.emit();
      }
      this._cur_index = n - 1;
      this._update_vertices(r);
    };
    if (!this.__pegtrace_watch) {
      this.__pegtrace_watch = true;
      // later: the glyph has not taken in the new data yet, and repainting now (BokehJS 3.9)
      // indexes the old rows of the new, possibly empty, data
      r.data_source.connect(r.data_source.properties.data.change, () => setTimeout(show, 0));
    }
    show();
  };
  globalThis.__pegtrace_poly_flow = true;
}
// tools that were active before the patch above: run their (patched) activate once
const pv = Bokeh.index.find_one(cb_obj);
if (pv != null && !pv.__pegtrace_poly_flow) {
  pv.__pegtrace_poly_flow = true;
  const D = Bokeh.require("models/tools/edit/poly_draw_tool").PolyDrawTool;
  const E = Bokeh.require("models/tools/edit/poly_edit_tool").PolyEditTool;
  for (const tv of pv.tool_views.values()) {
    if (tv.model.active && (tv.model instanceof D || tv.model instanceof E)) tv.activate();
  }
}
"""


def poly_flow(plot, element) -> None:
    """HoloViews hook for the PolyDraw + PolyEdit outline (see ``_POLY_FLOW_JS``)."""
    if getattr(plot, "_poly_flow", False):
        return
    plot.state.js_on_change("inner_width", CustomJS(code=_POLY_FLOW_JS))
    plot._poly_flow = True
