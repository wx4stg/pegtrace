import pytest
from shapely.geometry import Polygon, box

from pegtrace.csg import Solid, elevation, extrude_x, extrude_y, extrude_z, section_x, top_view


def test_extrusion_axes():
    a = extrude_z(box(0, 0, 10, 20), 1, 4)
    lo, hi = a.bounds()
    assert list(lo) == pytest.approx([0, 0, 1]) and list(hi) == pytest.approx([10, 20, 4])
    b = extrude_y(box(0, 2, 10, 5), 0, 7)  # region in (x, z)
    lo, hi = b.bounds()
    assert list(lo) == pytest.approx([0, 0, 2]) and list(hi) == pytest.approx([10, 7, 5])
    c = extrude_x(box(2, 3, 5, 9), 1, 4)  # region in (z, y)
    lo, hi = c.bounds()
    assert list(lo) == pytest.approx([1, 3, 2]) and list(hi) == pytest.approx([4, 9, 5])


def test_triangle_orientation_x():
    tri = Polygon([(0, 0), (4, 0), (0, 6)])  # (z, y) right angle at origin
    g = extrude_x(tri, 0, 1)
    sec = section_x(g, 0.5)
    assert sec.symmetric_difference(tri).area < 1e-6


def test_views():
    b = extrude_y(box(0, 2, 10, 5), 0, 7)
    assert elevation(b).bounds == pytest.approx((0, 0, 10, 7))
    assert top_view(b).bounds == pytest.approx((0, 2, 10, 5))


def test_booleans():
    a = Solid.cube((10, 10, 10))
    b = Solid.cube((10, 10, 10)).translate(5, 0, 0)
    assert (a + b).volume() == pytest.approx(1500)
    assert (a - b).volume() == pytest.approx(500)
    assert (a & b).volume() == pytest.approx(500)
    assert (a + b).num_components() == 1
    verts, tris = (a + b).to_mesh()
    assert verts.shape[1] == 3 and tris.shape[1] == 3
