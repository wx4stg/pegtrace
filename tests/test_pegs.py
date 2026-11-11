import math

import pytest
from shapely.affinity import rotate as rot2d
from shapely.affinity import translate
from shapely.geometry import box

from pegtrace.params import PegboardParams
from pegtrace.pegs import PegLayout, auto_hook_bend, peg_solids


def hook_side(pb):
    """The hook's section through its middle (x = 0) as (z, y), and its curve's radius."""
    s = peg_solids(PegLayout(hooks=[(0.0, 0.0)], radius=pb.peg_d / 2), pb)
    return s.rotate(0, 90, 0).slice(0.0).to_shapely()


def turns_through(pb, steps=40):
    """Thread the board along the hook's curve: at each point of the curve, a board whose hole
    is lined up with the curve there (and shifted across it as needed) may only meet the hook
    inside the hole."""
    side = hook_side(pb)
    r = pb.peg_d / 2
    big = (pb.hook_bend or auto_hook_bend(pb)) + r
    zs = -(pb.board_t + pb.board_clear)
    c = pb.hole_d - pb.peg_d
    top = math.degrees(math.acos(max(1 - pb.hook_rise / big, 0.0)))
    t = pb.board_t
    for i in range(steps + 1):
        a = top * i / steps
        cz, cy = zs - big * math.sin(math.radians(a)), big * (1 - math.cos(math.radians(a)))

        def fits(shift):  # hole's axis along the curve's tangent, ``shift`` off its centre line
            slab = box(-t / 2, -500, t / 2, 500)
            hole = box(-t / 2, shift - pb.hole_d / 2, t / 2, shift + pb.hole_d / 2)
            slab, hole = (translate(rot2d(g, -a, origin=(0, 0)), cz, cy) for g in (slab, hole))
            return side.intersection(slab).difference(hole).area < 1e-3

        if not any(fits(c * k / 10) for k in range(-10, 11)):
            return False
    return True


@pytest.mark.parametrize("preset", ["US 1/4 in hardboard (1 in grid, 1/4 in holes)",
                                    "US 1/8 in hardboard (1 in grid, 3/16 in holes)",
                                    "Metric 25 mm grid (5 mm holes)"])
@pytest.mark.parametrize("peg_clear", [0.5, 1.0])
def test_hook_turns_into_the_board(preset, peg_clear):
    pb = PegboardParams(preset=preset, peg_clear=peg_clear)
    assert turns_through(pb)
    # a sharp corner (the old L-hook) does not
    assert not turns_through(PegboardParams(preset=preset, peg_clear=peg_clear, hook_bend=0.5))


@pytest.mark.parametrize("rise", [0.0, 5.0, 8.0, 30.0])
def test_hook_is_one_solid_reaching_the_rise(rise):
    pb = PegboardParams(hook_rise=rise)
    s = peg_solids(PegLayout(hooks=[(0.0, 0.0)], radius=pb.peg_d / 2), pb)
    assert s.is_valid() and s.num_components() == 1
    lo, hi = s.bounds()
    assert hi[1] == pytest.approx(rise + pb.peg_d / 2, abs=0.05)
    assert hi[2] == pytest.approx(0.6)  # into the back plate
