import pytest
from PIL import Image
from shapely.geometry import Polygon, box

from pegtrace.calibration import rectify_rectangle
from pegtrace.tracing import auto_down_angle, autodetect, orient_polygon, polygon_from_xy


def test_polygon_from_xy_fixes_bowtie():
    p = polygon_from_xy([0, 10, 0, 10], [0, 10, 10, 0])
    assert p.is_valid and not p.is_empty
    assert p.area > 0


def test_autodetect_matches_truth(sample):
    path, truth = sample
    cal = rectify_rectangle(Image.open(path), truth["corners_px"], truth["paper_mm"])
    p = autodetect(cal)
    t = Polygon(truth["object_mm"])
    iou = p.intersection(t).area / p.union(t).area
    assert iou > 0.93


@pytest.mark.parametrize("angle", [0, 90, 180, 270, 33])
def test_orient_puts_chosen_direction_down(angle):
    # a wedge whose narrow tip points along `angle`
    import math

    from shapely import affinity

    wedge = affinity.rotate(Polygon([(0, -10), (0, 10), (60, 0)]), angle, origin=(0, 0))
    o = orient_polygon(wedge, angle)
    x0, y0, x1, y1 = o.bounds
    assert y0 == pytest.approx(0, abs=1e-9)
    assert (x0 + x1) / 2 == pytest.approx(0, abs=1e-9)
    tip = min(o.exterior.coords, key=lambda c: c[1])
    assert tip[0] == pytest.approx(0, abs=1e-6)  # tip is the lowest point, centred


def test_auto_down_angle_puts_heavy_end_down(hammer):
    o = orient_polygon(hammer, auto_down_angle(hammer))
    assert o.centroid.y < (o.bounds[3] - o.bounds[1]) / 2


def test_merge_close_vertices_makes_sharp_corners():
    from shapely.geometry import box

    from pegtrace.tracing import merge_close_vertices

    rounded = box(0, 0, 40, 20).buffer(-2).buffer(2, quad_segs=1)  # 2 points per corner
    merged = merge_close_vertices(rounded, 3.0)
    assert len(merged.exterior.coords) - 1 == 4
    assert merged.contains(rounded.buffer(-1e-6))  # only grows
    assert merged.area == pytest.approx(800, rel=0.01)


def test_merge_close_vertices_keeps_narrow_tabs():
    from shapely.geometry import box

    from pegtrace.tracing import merge_close_vertices

    tab = box(0, 0, 60, 20).union(box(28, 20, 32, 50))  # a 4 mm wide tab sticking up
    merged = merge_close_vertices(tab, 5.0)
    assert merged.equals(tab.normalize()) or abs(merged.area - tab.area) < 1e-6


def test_autodetect_ignores_shadow_on_paper():
    """Real photo with a shadow across part of the paper: the outline must follow the tool,
    not the shadow. Compare with a hand-traced outline (which is a little generous)."""
    import json
    from pathlib import Path

    from pegtrace.params import PAPER_SIZES

    data = Path(__file__).parent / "data"
    truth = json.loads((data / "wire_strippers.json").read_text())
    cal = rectify_rectangle(Image.open(data / "wire_strippers.jpg"), truth["corners_px"], PAPER_SIZES[truth["paper"]])
    p = autodetect(cal)
    t = Polygon(truth["outline_mm"])
    assert p.intersection(t).area / p.union(t).area > 0.85
