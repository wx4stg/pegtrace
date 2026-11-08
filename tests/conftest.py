import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def sample(tmp_path_factory):
    """Synthetic perspective photo + ground truth (generated fresh)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_sample", ROOT / "scripts" / "make_sample.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("sample")
    mod.main(str(out))
    truth = json.loads((out / "sample_truth.json").read_text())
    return out / "sample_photo.jpg", truth


@pytest.fixture
def hammer():
    """T-shaped outline in the holder frame, head down."""
    head = box(-45, 0, 45, 28)
    handle = box(-11, 20, 11, 160)
    return head.union(handle)


@pytest.fixture
def gamma():
    """Off-balance outline: thin upright bar with a long arm at the top."""
    return box(0, 0, 20, 150).union(box(0, 130, 120, 150))
