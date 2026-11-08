import pytest

from pegtrace.holder_shelf import build_shelf
from pegtrace.params import PegboardParams, ShelfParams


@pytest.mark.parametrize("sp", [
    ShelfParams(),
    ShelfParams(rim_height=6, gussets=False),
    ShelfParams(through=True, pocket_depth=6),
])
def test_shelf_is_single_valid_solid(hammer, sp):
    r = build_shelf(hammer, sp, PegboardParams())
    assert r.solid.is_valid()
    assert r.solid.num_components() == 1
    assert (r.solid & r.keepout).volume() == pytest.approx(0, abs=1e-6)


def test_pocket_depth(hammer):
    sp = ShelfParams(pocket_depth=10, floor_t=2, gussets=False)
    r = build_shelf(hammer, sp, PegboardParams())
    pocket_area = r.regions["pocket"].area
    full = r.regions["shelf"].area * (sp.pocket_depth + sp.floor_t)
    shelf_vol = r.parts["shelf"].volume()
    assert shelf_vol == pytest.approx(full - pocket_area * sp.pocket_depth, rel=0.01)


def test_shelf_sits_against_back_plate(hammer):
    sp = ShelfParams()
    r = build_shelf(hammer, sp, PegboardParams())
    lo, _ = r.parts["shelf"].bounds()
    assert lo[2] == pytest.approx(0, abs=1e-6)
    assert r.regions["pocket"].bounds[1] >= sp.back_t + sp.shelf_wall - sp.clear_xy - 1e-6
