"""Small helpers shared by the UI steps."""

from __future__ import annotations

import math

import holoviews as hv
import numpy as np
import panel as pn
from PIL import Image
from shapely.geometry import LineString, Polygon

DISPLAY_PX = 1200
# Editable points and the outline through them, shared by the scale and trace steps
POINT_OPTS = dict(color="#e15759", size=12, line_color="white", line_width=2)
OUTLINE_OPTS = dict(color="#e15759", line_width=2, line_dash="dashed")
# Rows holding a big plot fill the window below the header and step tabs (min heights still apply).
FILL_WINDOW = {"height": "calc(100vh - 100px)"}

# Style Bokeh's tab headers with Panel's colours.
TABS_CSS = """
.bk-header .bk-tab { color: var(--panel-on-background-color); }
.bk-header .bk-tab.bk-active { color: var(--panel-on-background-color); background-color: var(--panel-background-color);
  border-color: var(--panel-border-color); font-weight: 600; }
"""


def display_array(img: Image.Image, max_px: int = DISPLAY_PX) -> np.ndarray:
    """Downscaled RGB array for display (bokeh images are sent uncompressed)."""
    if max(img.size) > max_px:
        img = img.copy()
        img.thumbnail((max_px, max_px), Image.Resampling.BILINEAR)
    return np.asarray(img.convert("RGB"))


def photo_rgb(img: Image.Image | None) -> hv.RGB:
    """Photo in pixel units with y up: display (x, y) == photo pixel (x, H - y)."""
    if img is None:
        return hv.RGB(np.full((2, 2, 3), 240, np.uint8), bounds=(0, 0, 1, 1))
    w, h = img.size
    return hv.RGB(display_array(img), bounds=(0, 0, w, h))


def arrow(x: float, y: float, angle_deg: float, length: float, width: float | None = None) -> Polygon:
    """Arrow polygon from (x, y) pointing along ``angle_deg`` (CCW from +x)."""
    width = width or length * 0.08
    a = math.radians(angle_deg)
    d = np.array([math.cos(a), math.sin(a)])
    n = np.array([-d[1], d[0]])
    tip = np.array([x, y]) + d * length
    head = length * 0.28
    shaft = LineString([(x, y), tuple(tip - d * head * 0.9)]).buffer(width / 2, cap_style="flat")
    tri = Polygon([tuple(tip), tuple(tip - d * head + n * head * 0.55), tuple(tip - d * head - n * head * 0.55)])
    return shaft.union(tri)


def help_text(md: str) -> pn.pane.Markdown:
    return pn.pane.Markdown(md, styles={"color": "var(--secondary-text-color, #6c757d)"}, margin=(0, 10))


def status_alert() -> pn.pane.Alert:
    return pn.pane.Alert("", alert_type="info", visible=False, margin=(5, 10))


def show(alert: pn.pane.Alert, text: str, kind: str = "info") -> None:
    alert.object = text
    alert.alert_type = kind
    alert.visible = bool(text)


def run_busy(target, fn) -> None:
    """Run ``fn`` with Panel's loading spinner over ``target``.

    On the static site Python runs on the page's own thread, so nothing shows until Python
    returns to the browser: set the spinner, return, and do the work on the next tick.
    Without a page (tests, scripts) ``fn`` just runs.
    """
    if pn.state.curdoc is None:
        fn()
        return
    target.loading = True

    def run():
        try:
            fn()
        finally:
            target.loading = False

    pn.state.add_periodic_callback(run, period=60, count=1)
