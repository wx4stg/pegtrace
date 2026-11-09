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


# Bokeh turns a second tap within 300 ms into a "doubletap", which PointDrawTool and
# PolySelectTool ignore, so clicking points at a normal pace silently dropped every other one.
# Treat it as a tap.
_FAST_TAPS_JS = """
if (!globalThis.__pegtrace_fast_taps) {
  for (const [path, view] of [["edit/point_draw_tool", "PointDrawToolView"],
                              ["gestures/poly_select_tool", "PolySelectToolView"]]) {
    Bokeh.require("models/tools/" + path)[view].prototype._doubletap = function (ev) { this._tap(ev); };
  }
  globalThis.__pegtrace_fast_taps = true;
}
"""


def fast_taps(plot, element) -> None:
    """HoloViews hook for plots with point draw or polygon select: every click counts."""
    if getattr(plot, "_fast_taps", False):
        return
    plot.state.js_on_change("inner_width", CustomJS(code=_FAST_TAPS_JS))
    plot._fast_taps = True
