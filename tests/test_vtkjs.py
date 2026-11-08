import io
import json
import zipfile

import numpy as np

from pegtrace.csg import Solid
from pegtrace.vtkjs import MeshActor, data_url, scene_bytes


def test_scene_archive_structure():
    verts, tris = Solid.cube((10, 20, 30)).to_mesh()
    data = scene_bytes([MeshActor("box part", verts, tris, color=(1, 0, 0), opacity=0.5)])
    zf = zipfile.ZipFile(io.BytesIO(data))
    index = json.loads(zf.read("index.json"))
    (entry,) = index["scene"]
    assert entry["property"]["opacity"] == 0.5
    ds = json.loads(zf.read(entry["httpDataSetReader"]["url"] + "/index.json"))
    pts = ds["points"]
    raw = zf.read(f"{entry['httpDataSetReader']['url']}/data/{pts['ref']['id']}")
    arr = np.frombuffer(raw, dtype="<f4").reshape(-1, 3)
    assert np.allclose(arr, verts)
    polys = np.frombuffer(zf.read(f"{entry['httpDataSetReader']['url']}/data/{ds['polys']['ref']['id']}"), "<u4")
    assert polys.size == ds["polys"]["size"] == 4 * len(tris)
    assert np.all(polys.reshape(-1, 4)[:, 0] == 3)
    # camera looks at the middle of the box
    assert np.allclose(index["camera"]["focalPoint"], [5, 10, 15])


def test_data_url_roundtrip():
    import base64

    url = data_url(b"abc")
    assert url.startswith("data:application/octet-stream;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"abc"
