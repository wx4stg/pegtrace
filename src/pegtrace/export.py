"""Mesh export (binary STL, pure numpy)."""

from __future__ import annotations

import io

import numpy as np

from .csg import Solid
from .holder import oriented

_STL_DTYPE = np.dtype([
    ("normal", "<f4", (3,)),
    ("v", "<f4", (3, 3)),
    ("attr", "<u2"),
])


def stl_bytes(verts: np.ndarray, tris: np.ndarray, header: str = "pegtrace") -> bytes:
    verts = np.asarray(verts, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64)
    tv = verts[tris]  # (n, 3, 3)
    n = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])  # float64: keeps slivers' normals
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    rec = np.zeros(len(tris), dtype=_STL_DTYPE)
    rec["normal"] = n
    rec["v"] = tv
    buf = io.BytesIO()
    buf.write(header.encode("ascii", "replace")[:80].ljust(80, b" "))
    buf.write(np.uint32(len(tris)).tobytes())
    buf.write(rec.tobytes())
    return buf.getvalue()


def read_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Binary STL -> (normals (n,3), triangles (n,3,3))."""
    count = int(np.frombuffer(data[80:84], dtype="<u4")[0])
    rec = np.frombuffer(data[84:84 + count * _STL_DTYPE.itemsize], dtype=_STL_DTYPE)
    return rec["normal"].copy(), rec["v"].copy()


def solid_stl(solid: Solid, orientation: str = "print (upright)") -> bytes:
    verts, tris = oriented(solid, orientation).to_mesh()
    return stl_bytes(verts, tris)
