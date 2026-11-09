import numpy as np
import pytest

from pegtrace.csg import Solid
from pegtrace.holder import oriented
from pegtrace.holder_flat import build_flat
from pegtrace.holder_shelf import build_shelf
from pegtrace.params import FlatParams, PegboardParams, ShelfParams


def overhang_area(solid: Solid, max_angle_deg: float = 46.0) -> float:
    """Area of downward faces steeper than ``max_angle_deg`` from vertical, above the bed."""
    verts, tris = solid.to_mesh()
    tv = verts.astype(float)[tris]
    n = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    nz = np.divide(n[:, 2], 2 * area, out=np.zeros(len(area)), where=area > 0)
    lowest = tv[:, :, 2].min(axis=1)
    bad = (nz < -np.sin(np.radians(90 - max_angle_deg))) & (lowest > 0.05)
    return float(area[bad].sum())


def body_without_pegs(result):
    return Solid.union_all([s for k, s in result.parts.items() if k != "pegs"])


def test_flat_body_has_no_overhangs(hammer):
    r = build_flat(hammer, FlatParams(style="pocket", flat_bottom=True), PegboardParams())
    assert overhang_area(oriented(body_without_pegs(r), "print (upright)")) < 1.0


@pytest.mark.parametrize("sp", [ShelfParams(), ShelfParams(rim_height=5), ShelfParams(through=True)])
def test_shelf_body_has_no_overhangs(hammer, sp):
    r = build_shelf(hammer, sp, PegboardParams())
    assert overhang_area(oriented(body_without_pegs(r), "print (upright)")) < 1.0


def test_flat_ring_has_no_overhangs():
    from shapely.geometry import box

    t = box(-40, 100, 40, 120).union(box(-10, 0, 10, 100))
    r = build_flat(t, FlatParams(style="ring", ring_top=99), PegboardParams())
    assert overhang_area(oriented(body_without_pegs(r), "print (upright)")) < 1.0
