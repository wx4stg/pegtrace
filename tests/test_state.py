import pytest
from shapely.geometry import Polygon

from pegtrace.sample import make_photo
from pegtrace.state import RULER, AppState


@pytest.fixture
def ready_state():
    photo, truth = make_photo()
    s = AppState()
    s.set_photo(photo, "sample.jpg")
    assert len(s.corners_px) == 4
    s.calibrate()
    assert s.autodetect()
    s.auto_direction()
    return s, truth


def test_full_pipeline(ready_state):
    s, truth = ready_state
    assert s.result is not None and s.result.solid.is_valid()
    t = Polygon(truth["object_mm"])
    assert s.outline.intersection(t).area / s.outline.union(t).area > 0.93
    data = s.stl_bytes()
    assert len(data) > 84


def test_params_trigger_rebuild(ready_state):
    s, _ = ready_state
    v0 = s.result.solid.volume()
    s.flat.wall = 4.0
    assert s.result.solid.volume() > v0
    s.mode = "shelf"
    assert s.result.mode == "shelf"


def test_project_roundtrip(ready_state):
    s, _ = ready_state
    s.mode = "shelf"
    s.shelf.rim_height = 4
    s.pegboard.preset = "US 1/8 in hardboard (1 in grid, 3/16 in holes)"
    text = s.to_json()
    s2 = AppState()
    s2.from_json(text)
    assert s2.mode == "shelf" and s2.shelf.rim_height == 4
    assert s2.pegboard.hole_d == pytest.approx(s.pegboard.hole_d)
    assert s2.direction == s.direction
    assert s2.outline.symmetric_difference(s.outline).area < 1.0
    assert s2.result.solid.volume() == pytest.approx(s.result.solid.volume(), rel=1e-3)


def test_ruler_calibration():
    photo, _ = make_photo()
    s = AppState()
    s.set_photo(photo)
    s.cal_method = RULER
    s.ruler_px = [(100, 100), (500, 100)]
    s.ruler_mm = 200
    cal = s.calibrate()
    assert cal.bounds[2] == pytest.approx(photo.size[0] * 0.5)


def test_bad_outline_reports_error():
    photo, _ = make_photo()
    s = AppState()
    s.set_photo(photo)
    s.calibrate()
    s.set_outline(Polygon([(0, 0), (1e-3, 0), (0, 1e-3)]))
    # degenerate outline: either no result or an error message, never an exception
    assert s.result is None or s.result.solid.is_valid()
