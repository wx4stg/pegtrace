"""Write triangle meshes as a ``.vtkjs`` scene (pure Python, no VTK needed).

The ``.vtkjs`` format is a zip archive read by vtk.js' HttpSceneLoader, which
is what Panel's ``pn.pane.VTKJS`` renders in the browser:

    index.json                 scene: camera, background, one entry per actor
    <name>/index.json          vtkPolyData description
    <name>/data/<md5>          raw little-endian arrays (points, polys)
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass
class MeshActor:
    name: str
    verts: np.ndarray  # (n, 3) float
    tris: np.ndarray  # (m, 3) int
    color: tuple[float, float, float] = (0.6, 0.65, 0.7)
    opacity: float = 1.0


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _array_entry(arr: np.ndarray, name: str, ncomp: int, vtk_class: str, files: dict[str, bytes], prefix: str):
    raw = np.ascontiguousarray(arr).tobytes()
    digest = hashlib.md5(raw).hexdigest()
    files[f"{prefix}/data/{digest}"] = raw
    dtype = {np.dtype("<f4"): "Float32Array", np.dtype("<u4"): "Uint32Array"}[arr.dtype]
    return {
        "vtkClass": vtk_class,
        "name": name,
        "numberOfComponents": ncomp,
        "dataType": dtype,
        "size": int(arr.size),
        "ref": {"encode": "LittleEndian", "basepath": "data", "id": digest},
    }


def scene_bytes(
    actors: Sequence[MeshActor],
    background=(1.0, 1.0, 1.0),
    view_dir=(1.0, 0.7, 1.6),
    view_up=(0.0, 1.0, 0.0),
) -> bytes:
    """Build a ``.vtkjs`` archive for the given meshes; the camera frames them all."""
    files: dict[str, bytes] = {}
    scene = []
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for i, a in enumerate(actors):
        verts = np.asarray(a.verts, dtype="<f4").reshape(-1, 3)
        tris = np.asarray(a.tris, dtype=np.int64).reshape(-1, 3)
        if len(verts) == 0 or len(tris) == 0:
            continue
        lo = np.minimum(lo, verts.min(axis=0))
        hi = np.maximum(hi, verts.max(axis=0))
        prefix = f"{i}_{''.join(ch if ch.isalnum() else '_' for ch in a.name)}"
        polys = np.column_stack([np.full(len(tris), 3), tris]).astype("<u4").ravel()
        dataset = {
            "vtkClass": "vtkPolyData",
            "points": _array_entry(verts.ravel(), "_points", 3, "vtkPoints", files, prefix),
            "polys": _array_entry(polys, "_polys", 1, "vtkCellArray", files, prefix),
            "pointData": {"vtkClass": "vtkDataSetAttributes", "arrays": []},
            "cellData": {"vtkClass": "vtkDataSetAttributes", "arrays": []},
        }
        files[f"{prefix}/index.json"] = json.dumps(dataset).encode()
        rgb = list(map(float, a.color))
        scene.append({
            "name": a.name,
            "type": "httpDataSetReader",
            "httpDataSetReader": {"url": prefix},
            "actor": {"origin": [0, 0, 0], "scale": [1, 1, 1], "position": [0, 0, 0]},
            "actorRotation": [0, 0, 0, 1],
            "mapper": {"colorByArrayName": "", "colorMode": 0, "scalarMode": 0, "scalarVisibility": False},
            "property": {
                "representation": 2,
                "edgeVisibility": 0,
                "color": rgb,
                "diffuseColor": rgb,
                "ambientColor": rgb,
                "opacity": float(a.opacity),
                "ambient": 0.15,
                "diffuse": 0.85,
                "specular": 0.1,
            },
        })
    if not scene:
        lo, hi = np.zeros(3), np.ones(3)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2 or 1.0
    d = np.asarray(view_dir, float)
    d /= np.linalg.norm(d)
    index = {
        "version": 1.0,
        "background": list(map(float, background)),
        "camera": {
            "focalPoint": center.tolist(),
            "position": (center + d * radius * 3.2).tolist(),
            "viewUp": list(map(float, view_up)),
        },
        "centerOfRotation": center.tolist(),
        "scene": scene,
        "lookupTables": {},
    }
    files["index.json"] = json.dumps(index).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def data_url(archive: bytes) -> str:
    import base64

    return "data:application/octet-stream;base64," + base64.b64encode(archive).decode("ascii")


def scene_pane(archive: bytes | None = None, **params):
    """A Panel VTKJS pane showing a ``.vtkjs`` archive.

    The archive is sent as a ``data:`` URL: Panel 1.8's VTKJS model mishandles
    inline ``data`` (it never calls its async loader), and the URL path needs no
    server, so it works the same under ``panel serve`` and in the static page.
    """
    from panel.pane.vtk.vtk import VTKJS

    class VTKScene(VTKJS):
        def _get_vtkjs(self, fetch=True):
            return self.object, None  # always a URL; never fetched in Python

    return VTKScene(data_url(archive) if archive else None, **params)
