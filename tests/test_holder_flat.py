import numpy as np
import pytest

from pegtrace.csg import Solid
from pegtrace.export import read_stl, solid_stl
from pegtrace.holder import oriented
from pegtrace.holder_flat import build_flat
from pegtrace.params import FlatParams, PegboardParams
from pegtrace.stability import check_flat, suggest_pocket_percent


@pytest.mark.parametrize("lip,flat_bottom,notch", [(True, True, False), (False, False, True), (True, False, True)])
def test_flat_is_single_valid_solid(hammer, lip, flat_bottom, notch):
    fp = FlatParams(lip=lip, flat_bottom=flat_bottom, notch=notch)
    r = build_flat(hammer, fp, PegboardParams())
    assert r.solid.is_valid()
    assert r.solid.num_components() == 1
    assert r.solid.volume() > 1000
    # nothing may intrude on the space the object passes through when lifted out
    assert (r.solid & r.keepout).volume() == pytest.approx(0, abs=1e-6)


def test_pegs_on_grid(hammer):
    pb = PegboardParams(preset="US 1/8 in hardboard (1 in grid, 3/16 in holes)")
    r = build_flat(hammer, FlatParams(), pb)
    pts = np.array(r.pegs.points)
    rel = (pts - pts[0]) / pb.spacing
    assert np.allclose(rel, np.round(rel), atol=1e-9)
    assert len(r.pegs.hooks) >= 2  # 90 mm wide head fits several columns


def test_flat_bottom_prints_upright(hammer):
    r = build_flat(hammer, FlatParams(flat_bottom=True), PegboardParams())
    s = oriented(r.solid, "print (upright)")
    lo, hi = s.bounds()
    assert lo[2] == pytest.approx(0, abs=1e-6)
    # the bottom face must be large: slice just above the bed
    assert s.slice(0.05).area() > 0.5 * r.regions["back plate"].bounds[2] * 2


def test_stl_roundtrip(hammer):
    r = build_flat(hammer, FlatParams(), PegboardParams())
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
    good = build_flat(gamma, FlatParams(pocket_percent=60), pb)
    assert good.info["stable"]
    # without walls on the tipping side the arm drags it out
    from shapely.geometry import box

    floor_only = box(-5, -5, 30, 0)
    rep = check_flat(gamma, floor_only)
    assert not rep.stable


def test_suggest_pocket(hammer):
    fp, pb = FlatParams(), PegboardParams()
    pct = suggest_pocket_percent(hammer, fp, pb)
    assert pct is not None and 5 <= pct <= 95


@pytest.fixture
def letter_t():
    """A T the right way up: a wide bar on top of a narrow stem."""
    from shapely.geometry import box

    return box(-40, 100, 40, 120).union(box(-10, 0, 10, 100))


def test_ring_holds_t_by_its_bar(letter_t):
    from pegtrace.holder_flat import ring_level

    fp, pb = FlatParams(style="ring"), PegboardParams()
    top, _ = ring_level(letter_t.buffer(fp.clear_xy), fp)
    assert 97 < top < 99.5  # just under the bar (which is 1 mm lower with clearance)
    r = build_flat(letter_t, fp, pb)
    assert r.solid.is_valid() and r.solid.num_components() == 1
    assert (r.solid & r.keepout).volume() == pytest.approx(0, abs=1e-6)
    assert r.info["stable"] and not r.warnings
    # much less material than a pocket around the whole stem and bar
    pocket = build_flat(letter_t, FlatParams(pocket_percent=90), pb)
    assert r.info["volume_cm3"] < 0.5 * pocket.info["volume_cm3"]
    # the stem hangs free: nothing of the holder below the chamfer under the ring
    lo, _ = Solid.union_all([s for k, s in r.parts.items() if k != "pegs"]).bounds()
    assert lo[1] > 50


def test_ring_upside_down_warns(letter_t):
    from shapely import affinity

    r = build_flat(affinity.rotate(letter_t, 180, origin=(0, 60)), FlatParams(style="ring"), PegboardParams())
    assert any("No narrow part" in w for w in r.warnings)


def test_auto_direction_prefers_ring_way_up(letter_t):
    from pegtrace.state import AppState

    st = AppState()
    st.flat.style = "ring"
    st.outline = letter_t  # bar up as traced
    st.auto_direction()
    o = st.oriented_outline()
    assert o.centroid.y > (o.bounds[1] + o.bounds[3]) / 2  # heavy bar on top
    st.flat.style = "pocket"
    st.auto_direction()
    o = st.oriented_outline()
    assert o.centroid.y < (o.bounds[1] + o.bounds[3]) / 2  # heavier end down
