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


def test_insert_vertex_extends_or_splits():
    from pegtrace.tracing import insert_vertex

    sq = [(0, 0), (100, 0), (100, 100)]
    # far from every edge: continues after the last added vertex
    v, i = insert_vertex(sq, (-10, 150), after=2, snap=2)
    assert i == 3 and v[3] == (-10.0, 150.0)
    v, i = insert_vertex(sq, (-10, 150), after=0, snap=2)
    assert i == 1
    # on an edge: splits it
    v, i = insert_vertex(sq, (100.5, 50), after=0, snap=2)
    assert i == 2 and v == [(0, 0), (100, 0), (100.5, 50), (100, 100)]
    # the first points just append
    assert insert_vertex([], (1, 2), after=-1, snap=0) == ([(1.0, 2.0)], 0)
    assert insert_vertex([(0, 0)], (5, 5), after=0, snap=0)[1] == 1
