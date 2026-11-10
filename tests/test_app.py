"""Drive the Panel UI through its callbacks (no browser)."""

import numpy as np
import pytest

pn = pytest.importorskip("panel")


@pytest.fixture
def app():
    from pegtrace.app import create_app

    return create_app()


def load_sample(load):
    """Upload the synthetic sample photo through the Photo step's file input."""
    import io

    from pegtrace.sample import make_photo

    buf = io.BytesIO()
    make_photo()[0].save(buf, format="JPEG", quality=92)
    load.file.filename = "sample.jpg"
    load.file.value = buf.getvalue()


def test_full_ui_flow(app):
    state, steps = app.state, app.steps
    load, cal, trace, orient, design, export = steps
    tabs = app[1]
    load_sample(load)
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


def test_export_file_names(app):
    export = app.steps[-1]
    assert export.save.filename == "pegtrace_project.json"
    app.state.export.project_filename = "wire strippers"
    assert export.save.filename == "wire strippers.json"
    app.state.export.project_filename = "  "
    assert export.save.filename == "pegtrace_project.json"
    app.state.export.filename = "strippers.STL"
    assert export.stl.filename == "strippers.STL"
    app.state.export.filename = "strippers"
    assert export.stl.filename == "strippers.stl"


def test_lasso_and_edit(app):
    state, steps = app.state, app.steps
    load_sample(steps[0])
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
    load_sample(steps[0])
    h = state.photo.size[1]
    steps[1]._on_corner_draw({"x": [10, 20, 30, 40], "y": [h - 1, h - 2, h - 3, h - 4]})
    assert state.corners_px[0] == (10.0, 1.0)


def test_design_update_button(app):
    state, steps = app.state, app.steps
    load_sample(steps[0])
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


def test_design_numbers_can_be_typed(app):
    design = app.steps[4]
    panel = design.ring_panel
    assert isinstance(panel._widgets["ring_height"], pn.widgets.EditableFloatSlider)
    assert isinstance(design.peg_panel._widgets["columns"], pn.widgets.EditableIntSlider)
    panel._widgets["ring_height"].value = 17.5  # typed into the box
    assert app.state.flat.ring_height == 17.5 and app.state.stale


def test_setting_diagrams_are_valid_svg():
    import xml.etree.ElementTree as ET

    from pegtrace.ui.diagrams import SKETCHES

    for kind, sketch in SKETCHES.items():
        html = sketch()
        assert html.count("<svg") == 2, kind  # two views each
        ET.fromstring(f"<root>{html.replace('&nbsp;', ' ')}</root>")  # well-formed


def test_photo_upload_messages(app):
    load = app.steps[0]
    load_sample(load)
    assert "Loaded **sample.jpg** (1600 × 1200 px)" in load.alert.object
    # the static site sends the file's name after its contents
    load.file.param.update(filename=None)
    load.file.value = load.file.value + b"\0"  # a different upload, still a valid JPEG
    assert "Loaded the photo (1600 × 1200 px)" in load.alert.object
    load.file.filename = "later.jpg"
    assert app.state.photo_name == "later.jpg" and "Loaded **later.jpg**" in load.alert.object
    # a HEIC photo the browser could not convert
    load.file.value = b"\0\0\0\x18ftypheic\0\0\0\0mif1heic" + b"\0" * 64
    assert "Could not convert that HEIC photo" in load.alert.object
