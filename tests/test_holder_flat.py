import numpy as np
import pytest

from pegtrace.csg import Solid
from pegtrace.export import read_stl, solid_stl
from pegtrace.holder import oriented
from pegtrace.holder_flat import build_flat
from pegtrace.params import FlatParams, PegboardParams
from pegtrace.stability import check_flat


def pocket(top_y=64.0, **kw):
    """A pocket: the band reaches under the object (floor a wall thick under the gap)."""
    return FlatParams(top_y=top_y, bottom_y=-4.0, **kw)


def ring(top_y, height=10.0, **kw):
    """A ring: the band's bottom is above the object's lowest point."""
    return FlatParams(top_y=top_y, bottom_y=top_y - height, **kw)


@pytest.mark.parametrize("lip,notch,bottom_y", [(True, False, -4.0), (False, True, -10.0), (True, True, -2.0)])
def test_flat_is_single_valid_solid(hammer, lip, notch, bottom_y):
    fp = FlatParams(top_y=64, bottom_y=bottom_y, lip=lip, notch=notch)
    r = build_flat(hammer, fp, PegboardParams())
    assert r.solid.is_valid()
    assert r.solid.num_components() == 1
    assert r.solid.volume() > 1000
    # nothing may intrude on the space the object passes through when lifted out
    assert (r.solid & r.keepout).volume() == pytest.approx(0, abs=1e-6)


def test_pegs_on_grid(hammer):
    pb = PegboardParams(preset="US 1/8 in hardboard (1 in grid, 3/16 in holes)")
    r = build_flat(hammer, pocket(), pb)
    pts = np.array(r.pegs.points)
    rel = (pts - pts[0]) / pb.spacing
    assert np.allclose(rel, np.round(rel), atol=1e-9)
    assert len(r.pegs.hooks) >= 2  # 90 mm wide head fits several columns


def test_pocket_bottom_prints_upright(hammer):
    r = build_flat(hammer, pocket(), PegboardParams())
    s = oriented(r.solid, "print (upright)")
    lo, hi = s.bounds()
    assert lo[2] == pytest.approx(0, abs=1e-6)
    # the bottom face must be large: slice just above the bed
    assert s.slice(0.05).area() > 0.5 * r.regions["back plate"].bounds[2] * 2


def test_stl_roundtrip(hammer):
    r = build_flat(hammer, pocket(), PegboardParams())
    data = solid_stl(r.solid)
    normals, tris = read_stl(data)
    verts, faces = r.solid.to_mesh()
    assert len(tris) == len(faces)
    tv = verts.astype(float)[faces]
    area = np.linalg.norm(np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0]), axis=1) / 2
    ok = area > 1e-9  # Manifold keeps zero-area triangles to stay watertight at T-junctions
    assert np.allclose(np.linalg.norm(normals[ok], axis=1), 1, atol=1e-4)
    # watertight: every undirected edge is shared by exactly two triangles
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert np.all(counts == 2)


def test_stability_flags_off_balance_shape(gamma):
    pb = PegboardParams()
    good = build_flat(gamma, pocket(90), pb)
    assert good.info["stable"]
    # without walls on the tipping side the arm drags it out
    from shapely.geometry import box

    floor_only = box(-5, -5, 30, 0)
    rep = check_flat(gamma, floor_only)
    assert not rep.stable


def test_suggest_pocket(hammer):
    """A hammer head down gets wider going down, not up: a pocket, deep enough to hold it."""
    from pegtrace.holder_flat import suggest_band, with_band
    from pegtrace.stability import is_secure

    fp, pb = FlatParams(), PegboardParams()
    top_y, bottom_y, kind = suggest_band(hammer, fp, pb)
    assert kind == "pocket" and bottom_y <= -(fp.clear_xy + fp.wall) and 10 <= top_y < 150
    r = build_flat(hammer, with_band(fp, top_y, bottom_y), pb)
    assert r.solid.num_components() == 1 and not r.warnings
    assert is_secure(check_flat(hammer, r.regions["walls"]))


@pytest.fixture
def letter_t():
    """A T the right way up: a wide bar on top of a narrow stem."""
    from shapely.geometry import box

    return box(-40, 100, 40, 120).union(box(-10, 0, 10, 100))


def test_ring_holds_t_by_its_bar(letter_t):
    from pegtrace.holder_flat import suggest_band

    fp, pb = ring(99, clear_xy=1.0), PegboardParams()  # just under the bar, less clearance
    top, bottom, kind = suggest_band(letter_t, fp, pb)  # the suggestion agrees
    assert kind == "ring" and 97 < top < 99.5 and bottom == top - 10
    r = build_flat(letter_t, fp, pb)
    assert r.solid.is_valid() and r.solid.num_components() == 1
    assert (r.solid & r.keepout).volume() == pytest.approx(0, abs=1e-6)
    assert r.info["stable"] and not r.warnings
    # much less material than a pocket around the whole stem and bar
    cup = build_flat(letter_t, pocket(109), pb)
    assert r.info["volume_cm3"] < 0.5 * cup.info["volume_cm3"]
    # the stem hangs free: nothing of the holder below the chamfer under the ring
    lo, _ = Solid.union_all([s for k, s in r.parts.items() if k != "pegs"]).bounds()
    assert lo[1] > 50


def test_ring_underside_is_one_flat_face(letter_t):
    """With no back plate below the ring supports, nothing but the pegs (behind the board)
    reaches below the supports' slope, so the holder can lie on it to print at an angle."""
    from pegtrace.holder_flat import CHAMFER_SLOPE, flat_regions

    pb = PegboardParams()
    for below in (0.0, 5.0):
        fp = ring(99, clear_xy=1.0, plate_below=below)
        r = build_flat(letter_t, fp, pb)
        assert r.solid.is_valid() and r.solid.num_components() == 1 and not r.warnings
        yf = flat_regions(letter_t, fp, pb).y_floor
        v, _ = Solid.union_all([s for k, s in r.parts.items() if k != "pegs"]).to_mesh()
        under = (yf + CHAMFER_SLOPE * v[:, 2]) - v[:, 1]  # how far each vertex lies below the slope
        assert under.max() == pytest.approx(below, abs=1e-3)
        # every vertex of the plate's bottom lies on the (lowered) slope
        plate, _ = r.parts["back plate"].to_mesh()
        low = plate[:, 1] <= yf - below + CHAMFER_SLOPE * fp.back_t + 1e-3
        assert low.sum() >= 4
        assert np.allclose(plate[low, 1], yf - below + CHAMFER_SLOPE * plate[low, 2], atol=1e-3)


def test_ring_upside_down_warns(letter_t):
    from shapely import affinity

    r = build_flat(affinity.rotate(letter_t, 180, origin=(0, 60)), ring(40, clear_xy=1.0), PegboardParams())
    assert any("slide through" in w and "wide end up" in w for w in r.warnings)
    # inside the bar: the warning points to just under it
    r = build_flat(letter_t, ring(110, clear_xy=1.0), PegboardParams())
    assert any("slide through" in w and "starts at 99 mm" in w for w in r.warnings), r.warnings


def test_ring_rest_with_a_tilted_bar(letter_t):
    from shapely import affinity

    from pegtrace.holder_flat import ring_rest, suggest_ring_top

    from shapely.geometry import box

    fp = ring(40, clear_xy=1.0)
    bar = affinity.rotate(box(-40, 100, 40, 120), 4, origin=(0, 110))  # left end lower
    pc = bar.union(box(-10, 0, 10, 108)).buffer(fp.clear_xy)
    top = suggest_ring_top(pc, 40, fp)
    # the ring stops under the bar's lowest corner, so only the stem is inside it
    assert top == pytest.approx(bar.bounds[1] - fp.clear_xy, abs=0.3)
    assert below_width(pc, top) < 23
    assert ring_rest(pc, top, fp, 10.0) == pytest.approx(top, abs=0.3)


def below_width(pc, y):
    from pegtrace.geom2d import below

    b = below(pc, y).bounds
    return b[2] - b[0]


def test_ring_top_too_low_says_where_to_put_it(letter_t):
    r = build_flat(letter_t, ring(60, clear_xy=1.0), PegboardParams())
    msg = [w for w in r.warnings if "slide down" in w]
    assert msg and "39 mm" in msg[0] and "set Top Y to 99 mm" in msg[0]
    assert not any("falls through" in w for w in r.warnings)  # the stability check agrees: it rests
    r = build_flat(letter_t, ring(20, clear_xy=1.0), PegboardParams())  # a 79 mm slide
    assert any("slide down 79 mm" in w for w in r.warnings)
    assert not any("falls through" in w for w in r.warnings)
    r = build_flat(letter_t, ring(99, clear_xy=1.0), PegboardParams())
    assert not any("slide" in w for w in r.warnings)


def test_auto_direction_prefers_ring_way_up(letter_t, hammer):
    from shapely import affinity

    from pegtrace.state import AppState

    st = AppState()
    st.outline = affinity.rotate(letter_t, 180)  # bar down as traced
    st.auto_direction()
    o = st.oriented_outline()
    assert o.centroid.y > (o.bounds[1] + o.bounds[3]) / 2  # heavy bar on top, hanging in a ring
    assert 0 < st.flat.bottom_y < st.flat.top_y and st.result.info["style"] == "ring"
    assert not st.result.warnings and not st.stale
    # no way up gets wider going up: heavier end down, in a pocket
    st.outline = affinity.scale(letter_t.union(affinity.translate(letter_t, 0, -100)), 1, 1).convex_hull
    st.auto_direction()
    o = st.oriented_outline()
    assert st.flat.bottom_y < 0 and st.result.info["style"] == "pocket"


def test_ring_closes_around_separate_handles():
    """Wire strippers hang by the joint, handles down. The handles flare apart below the
    ring; the ring must still close around each one (the user threads them through)."""
    import json
    from pathlib import Path

    from shapely.geometry import LineString, Polygon

    from pegtrace.tracing import orient_polygon

    truth = json.loads((Path(__file__).parent / "data" / "wire_strippers.json").read_text())
    o = orient_polygon(Polygon(truth["outline_mm"]), 270.0)  # jaws up, as in the user's project
    fp = ring(104.5)
    r = build_flat(o, fp, PegboardParams())
    assert r.solid.is_valid() and r.solid.num_components() == 1
    assert not any("slide" in w for w in r.warnings), r.warnings
    # across the middle of the ring: a wall on each side of each handle
    y = (fp.top_y + fp.bottom_y) / 2
    cut = r.regions["walls"].intersection(LineString([(-200, y), (200, y)]))
    assert len(getattr(cut, "geoms", [cut])) == 4, cut
    # and the holder never overlaps the object where it hangs
    ghost = r.ghost
    assert (r.solid & ghost).volume() == pytest.approx(0, abs=1e-3)


def _thin_area(region, t):
    """Area of ``region`` thinner than ``t``: what an opening by t/2 removes, ignoring the bits
    it shaves off sharp corners (up to about (t/2)^2 (1 - pi/4) each, a little more if acute)."""
    from pegtrace.geom2d import polygons_of

    r = t / 2 - 0.05  # within 0.1 mm: curves are drawn with chords
    opened = region.buffer(-r, quad_segs=16).buffer(r, quad_segs=16)
    corner = 2 * (t / 2) ** 2 * (1 - np.pi / 4)
    return sum(p.area for p in polygons_of(region.difference(opened)) if p.area > corner)


@pytest.fixture
def pliers():
    """A joint on top of two legs that flare apart going down (like wire cutters' handles)."""
    from shapely.geometry import Polygon, box

    left = Polygon([(-16, 100), (-4, 100), (-22, 0), (-36, 0)])
    right = Polygon([(4, 100), (16, 100), (36, 0), (22, 0)])
    return box(-20, 100, 20, 125).union(left).union(right)


@pytest.mark.parametrize("wall", [1.2, 2.4, 4.0, 6.0])
@pytest.mark.parametrize("style", ["ring", "pocket"])
def test_walls_are_never_thinner_than_the_setting(pliers, style, wall):
    from pegtrace.holder_flat import flat_regions

    fp = ring(99, wall=wall) if style == "ring" else pocket(75, wall=wall)
    reg = flat_regions(pliers, fp, PegboardParams())
    assert reg.walls.area > 0
    assert _thin_area(reg.walls, wall) < 0.01
    r = build_flat(pliers, fp, PegboardParams())
    assert r.solid.is_valid() and r.solid.num_components() == 1
    assert (r.solid & r.keepout).volume() == pytest.approx(0, abs=1e-3)


@pytest.mark.parametrize("wall", [1.2, 2.4, 4.0])
def test_ring_supports_follow_leaning_legs(pliers, wall):
    """Below the ring the legs lean out past its edge. The supports under each wall must follow
    them out at full thickness, not taper away to nothing."""
    from shapely.geometry import LineString

    fp = ring(99, wall=wall)
    r = build_flat(pliers, fp, PegboardParams())
    assert r.solid.is_valid() and r.solid.num_components() == 1
    bottom = pliers.bounds[1] + fp.bottom_y
    for drop in (1.0, 4.0):  # just under the ring, and lower down the slope
        y = bottom - drop
        sec = r.solid.slice(fp.back_t + 0.5).to_shapely()  # through the walls, near the board
        cut = sec.intersection(LineString([(-200, y), (200, y)]))
        pieces = sorted(getattr(cut, "geoms", [cut]), key=lambda g: g.bounds[0])
        # outside and inside of each leg (the two inside ones merge when the walls are thick)
        assert len(pieces) in (3, 4), (drop, cut)
        assert min(p.length for p in pieces) >= wall - 0.1, (drop, [p.length for p in pieces])
    assert (r.solid & r.ghost).volume() == pytest.approx(0, abs=1e-3)


@pytest.mark.parametrize("bottom_y", [-4.0, -12.0])
def test_bottom_below_the_object_fills_in_a_pocket(hammer, bottom_y):
    """Bottom Y under the object: the band is filled in under it down to Bottom Y, a flat
    floor the object stands on."""
    from pegtrace.holder_flat import flat_regions

    fp = FlatParams(top_y=64, bottom_y=bottom_y)
    reg = flat_regions(hammer, fp, PegboardParams())
    assert not reg.ring and reg.bottom == pytest.approx(bottom_y)
    assert reg.walls.bounds[1] == pytest.approx(bottom_y) and reg.back.bounds[1] == pytest.approx(bottom_y)
    under = box_(-40, bottom_y, 40, -fp.clear_xy - 0.01)  # all of it under the object, gap aside
    assert under.difference(reg.walls).area < 1e-6
    r = build_flat(hammer, fp, PegboardParams())
    assert r.info["style"] == "pocket" and r.info["stable"] and not r.warnings
    assert r.solid.bounds()[0][1] == pytest.approx(bottom_y)


def test_bottom_above_the_object_makes_a_ring(letter_t):
    from pegtrace.holder_flat import flat_regions

    reg = flat_regions(letter_t, ring(99), PegboardParams())
    assert reg.ring and reg.bottom == pytest.approx(89)
    assert reg.walls.bounds[1] >= 89 - 1e-6  # nothing under the stem in the band's plane
    assert build_flat(letter_t, ring(99), PegboardParams()).info["style"] == "ring"


@pytest.mark.parametrize("top_y,bottom_y,note,top,bottom", [
    (99, 98, "at least 3 mm below Top Y", 99, 96),       # band too short
    (64, -1, "floor thinner than a wall", 64, -3.9),     # floor inside the gap under the object
    (64, 0, "floor thinner than a wall", 64, -3.9),      # 0: the object's bottom, still a pocket
])
def test_band_settings_that_cannot_work_are_adjusted(hammer, top_y, bottom_y, note, top, bottom):
    from pegtrace.holder_flat import flat_regions

    reg = flat_regions(hammer, FlatParams(top_y=top_y, bottom_y=bottom_y), PegboardParams())
    assert reg.top == pytest.approx(top) and reg.bottom == pytest.approx(bottom)
    assert any(note in n for n in reg.notes), reg.notes
    r = build_flat(hammer, FlatParams(top_y=top_y, bottom_y=bottom_y), PegboardParams())
    assert any(note in w for w in r.warnings)


def test_suggests_a_ring_for_wire_strippers():
    """Hung jaws up, the handles splay wider than the joint, but each passes through its own
    opening: the joint rests on a ring around both."""
    import json
    from pathlib import Path

    from shapely.geometry import Polygon

    from pegtrace.holder_flat import suggest_band, with_band
    from pegtrace.tracing import orient_polygon

    truth = json.loads((Path(__file__).parent / "data" / "wire_strippers.json").read_text())
    o = orient_polygon(Polygon(truth["outline_mm"]), 270.0)
    fp, pb = FlatParams(), PegboardParams()
    top_y, bottom_y, kind = suggest_band(o, fp, pb)
    assert kind == "ring" and bottom_y > 0
    r = build_flat(o, with_band(fp, top_y, bottom_y), pb)
    assert r.solid.num_components() == 1 and not r.warnings, r.warnings


def box_(*b):
    from shapely.geometry import box

    return box(*b)
