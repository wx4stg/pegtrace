"""Drive the Panel UI through its callbacks (no browser)."""

import numpy as np
import pytest

pn = pytest.importorskip("panel")


@pytest.fixture
def app():
    from pegtrace.app import create_app

    return create_app()


def test_full_ui_flow(app):
    state, steps = app.state, app.steps
    load, cal, trace, orient, design, export = steps
    tabs = app[1]
    load._on_sample(None)
    assert state.photo is not None and tabs.active == 1
    cal._on_apply(None)
    assert state.calibration is not None and tabs.active == 2
    trace._on_auto(None)
    assert state.outline is not None
    trace._on_done(None)
    assert tabs.active == 3
    state.auto_direction()
    assert state.result is not None
    # render every view once
    for s in steps:
        pn.panel(s.view()).get_root()
    design.views.active = design.TAB_3D
    design._apply_3d()
    assert design.scene.object.startswith("data:application/octet-stream;base64,")
    data = export._stl()
    assert data is not None and len(data.getvalue()) > 1000
    assert len(export._project().getvalue()) > 1000


def test_point_draw_trace(app):
    state, steps = app.state, app.steps
    steps[0]._on_sample(None)
    steps[1]._on_apply(None)
    trace = steps[2]
    clicks = [(20, 20), (120, 25), (110, 200), (30, 190)]
    xs, ys = [], []
    for x, y in clicks:  # the browser sends all points after each click, the new one last
        xs.append(x)
        ys.append(y)
        trace._on_draw({"x": list(xs), "y": list(ys)})
    assert state.outline is not None and state.outline.area > 10000
    assert trace.verts == [(20.0, 20.0), (120.0, 25.0), (110.0, 200.0), (30.0, 190.0)]
    # a click on the edge between vertices 1 and 2 splits it, wherever the browser put it
    trace._on_draw({"x": xs + [115], "y": ys + [112]})
    assert trace.verts[2] == (115.0, 112.0) and len(trace.verts) == 5
    # drag the new vertex outward
    v = list(trace.verts)
    v[2] = (160.0, 112.0)
    trace._on_draw({"x": [a for a, _ in v], "y": [b for _, b in v]})
    assert abs(state.outline.bounds[2] - 160) < 1e-6
    # delete it (Backspace), then undo the last point
    del v[2]
    trace._on_draw({"x": [a for a, _ in v], "y": [b for _, b in v]})
    assert len(trace.verts) == 4 and state.outline.bounds[2] < 125
    trace._on_undo(None)
    assert len(trace.verts) == 3 and state.outline is not None
    trace._on_undo(None)
    assert state.outline is None
    # outlines from auto-detect show up as editable vertices
    trace._on_auto(None)
    assert state.outline is not None and len(trace.verts) == len(state.outline.exterior.coords) - 1


def test_corner_drag_updates_state(app):
    state, steps = app.state, app.steps
    steps[0]._on_sample(None)
    h = state.photo.size[1]
    steps[1]._on_corner_draw({"x": [10, 20, 30, 40], "y": [h - 1, h - 2, h - 3, h - 4]})
    assert state.corners_px[0] == (10.0, 1.0)
