import shapely
from shapely import affinity
from shapely.geometry import Polygon

from pegtrace.geom2d import below, from_contours, sweep, sweep_up, to_contours


def test_sweep_matches_bruteforce():
    p = Polygon([(0, 0), (30, 5), (12, 12), (25, 30), (-5, 20)])
    exact = sweep(p, 7, 40)
    brute = shapely.union_all([affinity.translate(p, 7 * t / 400, 40 * t / 400) for t in range(401)])
    assert exact.symmetric_difference(brute).area < 0.02 * exact.area
    assert exact.contains(brute.buffer(-0.05))


def test_sweep_up_removes_overhangs():
    # a C-shape: sweeping up fills everything above the lower arm
    c = Polygon([(0, 0), (30, 0), (30, 5), (5, 5), (5, 25), (30, 25), (30, 30), (0, 30)])
    u = below(sweep_up(c, 100), 30)
    assert abs(u.area - 30 * 30) < 1e-6


def test_contours_roundtrip():
    ring = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(3, 3), (3, 6), (6, 6), (6, 3)]])
    back = from_contours(to_contours(ring))
    assert back.symmetric_difference(ring).area < 1e-9
