"""PegTrace Panel app.

Run locally:      pegtrace            (or: panel serve web/app_entry.py --show)
Static site:      python web/build.py --app web/app_entry.py
"""

from __future__ import annotations

import holoviews as hv
import panel as pn

from .state import AppState
from .ui.calibrate import CalibrateStep
from .ui.common import TABS_CSS
from .ui.design import DesignStep
from .ui.export import ExportStep
from .ui.load import LoadStep
from .ui.orient import OrientStep
from .ui.trace import TraceStep

STEPS = [LoadStep, CalibrateStep, TraceStep, OrientStep, DesignStep, ExportStep]
def setup() -> None:
    from .compat import patch_holoviews_callbacks

    patch_holoviews_callbacks()
    pn.extension("vtk", notifications=False)
    pn.config.throttled = True  # sliders apply on release
    hv.extension("bokeh", logo=False)


def create_app(state: AppState | None = None) -> pn.viewable.Viewable:
    setup()
    pn.config.theme = "default"  # light only, even with ?theme=dark in the URL
    if not pn.state._is_pyodide:  # the static page styles its own <body>
        pn.config.global_css = ["body { background: #ffffff; color-scheme: light; }"]
    state = state or AppState()
    tabs = pn.Tabs(sizing_mode="stretch_width", dynamic=False, stylesheets=[TABS_CSS])

    def go_to(i):
        return lambda: setattr(tabs, "active", i)

    steps = [cls(state, on_done=go_to(i + 1) if i + 1 < len(STEPS) else None) for i, cls in enumerate(STEPS)]
    tabs.extend([(s.title, s.view()) for s in steps])
    header = pn.Row(
        pn.pane.Markdown("## PegTrace", margin=(0, 10)),
        pn.pane.Markdown("Photo → outline → 3D-printable pegboard holder", margin=(8, 10),
                         styles={"color": "var(--secondary-text-color, #6c757d)"}),
        sizing_mode="stretch_width",
    )
    root = pn.Column(header, tabs, sizing_mode="stretch_width")
    root.state = state  # handy for scripting and tests
    root.steps = steps
    return root


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="PegTrace: trace an object, make a pegboard holder")
    ap.add_argument("--port", type=int, default=5006)
    ap.add_argument("--no-show", action="store_true")
    a = ap.parse_args()
    pn.serve({"pegtrace": create_app}, port=a.port, show=not a.no_show, title="PegTrace")
