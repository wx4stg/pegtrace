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


def test_lasso_and_edit(app):
    state, steps = app.state, app.steps
    steps[0]._on_sample(None)
    steps[1]._on_apply(None)
    steps[2]._on_lasso(np.array([[20, 20], [120, 25], [110, 200], [30, 190]], float))
    assert state.outline is not None and state.outline.area > 10000
    steps[2]._on_edit({"xs": [[20, 120, 110, 60]], "ys": [[20, 25, 200, 210]]})
    assert abs(state.outline.bounds[3] - 210) < 1e-6
    assert state.simplify_tol > 0  # editing keeps the points but leaves the slider alone
    steps[2].clear.clicks += 1
    assert state.outline is None and len(steps[2].poly_pipe.data) == 0


def test_corner_drag_updates_state(app):
    state, steps = app.state, app.steps
    steps[0]._on_sample(None)
    h = state.photo.size[1]
    steps[1]._on_corner_draw({"x": [10, 20, 30, 40], "y": [h - 1, h - 2, h - 3, h - 4]})
    assert state.corners_px[0] == (10.0, 1.0)


def test_design_update_button(app):
    state, steps = app.state, app.steps
    steps[0]._on_sample(None)
    steps[1]._on_apply(None)
    steps[2]._on_auto(None)
    state.auto_direction()
    design = steps[4]
    pn.panel(design.view()).get_root()
    v0 = state.result.info["volume_cm3"]
    assert design.update.disabled
    state.flat.wall = 4.0  # a slider moves: nothing is rebuilt yet
    assert state.stale and not design.update.disabled and state.result.info["volume_cm3"] == v0
    design.update.clicks += 1
    assert not state.stale and design.update.disabled and state.result.info["volume_cm3"] > v0
