import numpy as np
import pytest
from PIL import Image

from pegtrace.calibration import apply_h, homography, order_corners, rectify_rectangle, scale_two_points


def test_homography_roundtrip():
    rng = np.random.default_rng(0)
    h_true = np.array([[1.2, 0.1, 30], [-0.05, 0.9, 12], [1e-4, -2e-4, 1]])
    src = rng.uniform(0, 1000, (6, 2))
    dst = apply_h(h_true, src)
    h = homography(src, dst)
    assert np.allclose(apply_h(h, src), dst, atol=1e-6)


def test_order_corners_is_clockwise_from_top_left():
    pts = [(900, 80), (100, 700), (120, 90), (880, 760)]
    c = order_corners(pts)
    assert tuple(c[0]) == (120, 90)
    assert tuple(c[1]) == (900, 80)
    assert tuple(c[2]) == (880, 760)
    assert tuple(c[3]) == (100, 700)


def test_rectify_recovers_paper(sample):
    path, truth = sample
    img = Image.open(path)
    corners = list(reversed(truth["corners_px"]))  # order must not matter
    cal = rectify_rectangle(img, corners, tuple(reversed(truth["paper_mm"])))
    w, h = truth["paper_mm"]
    mm = cal.px_to_mm(truth["corners_px"])
    assert np.allclose(mm, [(0, h), (w, h), (w, 0), (0, 0)], atol=0.5)
    assert cal.reference == pytest.approx((0, 0, w, h))
    left, bottom, right, top = cal.bounds
    assert (right - left) * cal.px_per_mm == pytest.approx(cal.image.size[0], abs=1)
    assert (top - bottom) * cal.px_per_mm == pytest.approx(cal.image.size[1], abs=1)


def test_two_point_scale():
    img = Image.new("RGB", (1000, 500), "white")
    cal = scale_two_points(img, (100, 100), (600, 100), 250.0)
    assert cal.bounds == pytest.approx((0, 0, 500, 250))
    assert np.allclose(cal.px_to_mm([(100, 500)]), [(50, 0)])
