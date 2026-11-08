"""Thin solid-modelling adapter over the Manifold library.

Two interchangeable backends wrap the same C++ library:

* ``py`` - the ``manifold3d`` Python package (local / server use).
* ``js`` - the ``manifold-3d`` npm WASM module, reached through the browser
  Python runtime's JS bridge (pyjs or Pyodide). The page bootstrap must run
  ``const wasm = await Module(); wasm.setup(); globalThis.manifold = wasm;``
  before Python starts, so all calls here are synchronous.

Geometry code only uses :class:`Solid`, :class:`Section` and the module-level
constructors; it never touches a backend directly.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

import numpy as np

DEFAULT_SEGMENTS = 48


def _choose_backend() -> str:
    env = os.environ.get("PEGTRACE_CSG", "").lower()
    if env in ("py", "js"):
        return env
    return "js" if sys.platform == "emscripten" else "py"


BACKEND = _choose_backend()


# --------------------------------------------------------------------------
# backend: python manifold3d
# --------------------------------------------------------------------------
class _PyBackend:
    name = "py"

    def __init__(self):
        import manifold3d as m3

        self.m3 = m3

    # sections
    def section(self, contours):
        m3 = self.m3
        if not contours:
            return m3.CrossSection()
        return m3.CrossSection([np.asarray(c, dtype=float) for c in contours], m3.FillRule.Positive)

    def section_empty(self, cs):
        return cs.is_empty()

    def section_polygons(self, cs):
        return [np.asarray(p, dtype=float) for p in cs.to_polygons()]

    def section_offset(self, cs, delta, segments):
        return cs.offset(delta, self.m3.JoinType.Round, 2.0, segments)

    def section_area(self, cs):
        return cs.area()

    def extrude(self, cs, height):
        return cs.extrude(height)

    # solids
    def empty(self):
        return self.m3.Manifold()

    def cube(self, size, center):
        return self.m3.Manifold.cube(tuple(map(float, size)), center)

    def cylinder(self, h, r_lo, r_hi, segments, center):
        return self.m3.Manifold.cylinder(h, r_lo, r_hi, segments, center)

    def sphere(self, r, segments):
        return self.m3.Manifold.sphere(r, segments)

    def translate(self, m, v):
        return m.translate(tuple(map(float, v)))

    def rotate(self, m, v):
        return m.rotate(tuple(map(float, v)))

    def mirror(self, m, n):
        return m.mirror(tuple(map(float, n)))

    def union(self, ms):
        if not ms:
            return self.empty()
        if len(ms) == 1:
            return ms[0]
        return self.m3.Manifold.batch_boolean(list(ms), self.m3.OpType.Add)

    def subtract(self, a, b):
        return a - b

    def intersect(self, a, b):
        return a ^ b

    def is_empty(self, m):
        return m.is_empty()

    def volume(self, m):
        return m.volume()

    def status_ok(self, m):
        return m.status() == self.m3.Error.NoError

    def components(self, m):
        return len(m.decompose())

    def genus(self, m):
        return m.genus()

    def bounds(self, m):
        b = m.bounding_box()
        return np.array(b[:3]), np.array(b[3:])

    def project(self, m):
        return m.project()

    def slice(self, m, z):
        return m.slice(z)

    def mesh(self, m):
        mesh = m.to_mesh()
        verts = np.asarray(mesh.vert_properties, dtype=np.float32)[:, :3]
        tris = np.asarray(mesh.tri_verts, dtype=np.uint32)
        return np.ascontiguousarray(verts), np.ascontiguousarray(tris)


# --------------------------------------------------------------------------
# backend: JS manifold-3d through the browser JS bridge
# --------------------------------------------------------------------------
class _JsBackend:
    name = "js"

    def __init__(self):
        try:  # pyjs (emscripten-forge)
            import pyjs

            self.js = pyjs.js
            self._to_js = pyjs.to_js
            self._to_py = pyjs.to_py
        except ImportError:  # Pyodide
            import js  # type: ignore[import-not-found]
            from pyodide.ffi import to_js  # type: ignore[import-not-found]

            self.js = js
            self._to_js = to_js
            self._to_py = lambda o: o.to_py()
        wasm = self.js.globalThis.manifold
        self.Manifold = wasm.Manifold
        self.CrossSection = wasm.CrossSection

    def _vec(self, v):
        return self._to_js([float(x) for x in v])

    def _contours_js(self, contours):
        return self._to_js([[[float(x), float(y)] for x, y in np.asarray(c)] for c in contours])

    # sections
    def section(self, contours):
        if not contours:
            return self.CrossSection.ofPolygons(self._to_js([]), "Positive")
        return self.CrossSection.ofPolygons(self._contours_js(contours), "Positive")

    def section_empty(self, cs):
        return bool(cs.isEmpty())

    def section_polygons(self, cs):
        polys = self._to_py(cs.toPolygons())
        return [np.asarray(p, dtype=float).reshape(-1, 2) for p in polys]

    def section_offset(self, cs, delta, segments):
        return cs.offset(float(delta), "Round", 2.0, int(segments))

    def section_area(self, cs):
        return float(cs.area())

    def extrude(self, cs, height):
        return cs.extrude(float(height))

    # solids
    def empty(self):
        return self.Manifold.union(self._to_js([]))

    def cube(self, size, center):
        return self.Manifold.cube(self._vec(size), bool(center))

    def cylinder(self, h, r_lo, r_hi, segments, center):
        return self.Manifold.cylinder(float(h), float(r_lo), float(r_hi), int(segments), bool(center))

    def sphere(self, r, segments):
        return self.Manifold.sphere(float(r), int(segments))

    def translate(self, m, v):
        return m.translate(self._vec(v))

    def rotate(self, m, v):
        return m.rotate(self._vec(v))

    def mirror(self, m, n):
        return m.mirror(self._vec(n))

    def union(self, ms):
        if not ms:
            return self.empty()
        if len(ms) == 1:
            return ms[0]
        return self.Manifold.union(self._to_js(list(ms)))

    def subtract(self, a, b):
        return a.subtract(b)

    def intersect(self, a, b):
        return a.intersect(b)

    def is_empty(self, m):
        return bool(m.isEmpty())

    def volume(self, m):
        return float(m.volume())

    def status_ok(self, m):
        return str(m.status()) == "NoError"

    def components(self, m):
        parts = m.decompose()
        n = int(parts.length)
        for i in range(n):
            parts[i].delete()
        return n

    def genus(self, m):
        return int(m.genus())

    def bounds(self, m):
        bb = m.boundingBox()
        lo = np.array([float(bb.min[i]) for i in range(3)])
        hi = np.array([float(bb.max[i]) for i in range(3)])
        return lo, hi

    def project(self, m):
        return m.project()

    def slice(self, m, z):
        return m.slice(float(z))

    def mesh(self, m):
        mesh = m.getMesh()
        nprop = int(mesh.numProp)
        verts = np.asarray(self._to_py(mesh.vertProperties), dtype=np.float32).reshape(-1, nprop)[:, :3]
        tris = np.asarray(self._to_py(mesh.triVerts), dtype=np.uint32).reshape(-1, 3)
        return np.ascontiguousarray(verts), np.ascontiguousarray(tris)

    def release(self, obj):
        try:
            obj.delete()
        except Exception:  # already deleted / not an Embind object
            pass


_backend = None


def backend():
    global _backend
    if _backend is None:
        _backend = _JsBackend() if BACKEND == "js" else _PyBackend()
    return _backend


def _release(obj):
    b = _backend
    if b is not None and hasattr(b, "release") and obj is not None:
        b.release(obj)


# --------------------------------------------------------------------------
# public wrappers
# --------------------------------------------------------------------------
class Section:
    """2D cross-section (wraps CrossSection)."""

    __slots__ = ("_h",)

    def __init__(self, handle):
        self._h = handle

    def __del__(self):
        _release(getattr(self, "_h", None))

    @classmethod
    def from_contours(cls, contours: Sequence[np.ndarray]) -> "Section":
        return cls(backend().section(list(contours)))

    @classmethod
    def from_shapely(cls, geom) -> "Section":
        from .geom2d import to_contours

        return cls.from_contours(to_contours(geom))

    def is_empty(self) -> bool:
        return backend().section_empty(self._h)

    def area(self) -> float:
        return backend().section_area(self._h)

    def polygons(self) -> list[np.ndarray]:
        return backend().section_polygons(self._h)

    def to_shapely(self):
        from .geom2d import from_contours

        return from_contours(self.polygons())

    def offset(self, delta: float, segments: int = DEFAULT_SEGMENTS) -> "Section":
        return Section(backend().section_offset(self._h, delta, segments))

    def extrude(self, height: float) -> "Solid":
        if self.is_empty() or height <= 0:
            return Solid.empty()
        return Solid(backend().extrude(self._h, height))


class Solid:
    """3D solid (wraps Manifold). Operations return new solids."""

    __slots__ = ("_h",)

    def __init__(self, handle):
        self._h = handle

    def __del__(self):
        _release(getattr(self, "_h", None))

    # constructors
    @classmethod
    def empty(cls) -> "Solid":
        return cls(backend().empty())

    @classmethod
    def cube(cls, size, center: bool = False) -> "Solid":
        return cls(backend().cube(size, center))

    @classmethod
    def cylinder(cls, h: float, r_lo: float, r_hi: float | None = None,
                 segments: int = DEFAULT_SEGMENTS, center: bool = False) -> "Solid":
        return cls(backend().cylinder(h, r_lo, r_lo if r_hi is None else r_hi, segments, center))

    @classmethod
    def sphere(cls, r: float, segments: int = DEFAULT_SEGMENTS) -> "Solid":
        return cls(backend().sphere(r, segments))

    @classmethod
    def union_all(cls, solids: Sequence["Solid"]) -> "Solid":
        hs = [s._h for s in solids if s is not None and not s.is_empty()]
        if not hs:
            return cls.empty()
        return cls(backend().union(hs))

    # transforms
    def translate(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> "Solid":
        return Solid(backend().translate(self._h, (x, y, z)))

    def rotate(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> "Solid":
        """Euler rotation in degrees (applied x, then y, then z)."""
        return Solid(backend().rotate(self._h, (x, y, z)))

    def mirror(self, normal) -> "Solid":
        return Solid(backend().mirror(self._h, normal))

    # booleans
    def __add__(self, other: "Solid") -> "Solid":
        return Solid.union_all([self, other])

    def __sub__(self, other: "Solid") -> "Solid":
        if other.is_empty():
            return self
        return Solid(backend().subtract(self._h, other._h))

    def __and__(self, other: "Solid") -> "Solid":
        return Solid(backend().intersect(self._h, other._h))

    # queries
    def is_empty(self) -> bool:
        return backend().is_empty(self._h)

    def volume(self) -> float:
        return backend().volume(self._h)

    def is_valid(self) -> bool:
        return backend().status_ok(self._h)

    def num_components(self) -> int:
        return backend().components(self._h)

    def genus(self) -> int:
        return backend().genus(self._h)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return backend().bounds(self._h)

    def project(self) -> Section:
        """Silhouette on the XY plane (looking along -Z)."""
        return Section(backend().project(self._h))

    def slice(self, z: float) -> Section:
        return Section(backend().slice(self._h, z))

    def to_mesh(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (verts float32 Nx3, tris uint32 Mx3)."""
        return backend().mesh(self._h)


# --------------------------------------------------------------------------
# helpers that combine shapely regions and solids
# --------------------------------------------------------------------------
def extrude_z(geom, z0: float, z1: float) -> Solid:
    """Extrude a shapely region (x, y) along +Z over [z0, z1]."""
    if geom is None or geom.is_empty or z1 <= z0:
        return Solid.empty()
    return Section.from_shapely(geom).extrude(z1 - z0).translate(0, 0, z0)


def extrude_y(geom, y0: float, y1: float) -> Solid:
    """Extrude a shapely region given in (x, z) coordinates along +Y over [y0, y1]."""
    from shapely import affinity

    if geom is None or geom.is_empty or y1 <= y0:
        return Solid.empty()
    # mirror d -> -d, extrude along z, then rotate -90 about x: (x, y, z) -> (x, z, -y)
    mirrored = affinity.scale(geom, xfact=1.0, yfact=-1.0, origin=(0, 0))
    return Section.from_shapely(mirrored).extrude(y1 - y0).rotate(-90, 0, 0).translate(0, y0, 0)


def extrude_x(geom, x0: float, x1: float) -> Solid:
    """Extrude a shapely region given in (z, y) coordinates along +X over [x0, x1]."""
    if geom is None or geom.is_empty or x1 <= x0:
        return Solid.empty()
    # region (u=z, v=y) extruded along +Z gives (u, v, w). Rotate +90 about y maps
    # (x, y, z) -> (z, y, -x); so (u, v, w) -> (w, v, -u). Mirror u first so -u -> z.
    from shapely import affinity

    mirrored = affinity.scale(geom, xfact=-1.0, yfact=1.0, origin=(0, 0))
    return Section.from_shapely(mirrored).extrude(x1 - x0).rotate(0, 90, 0).translate(x0, 0, 0)


def elevation(solid: Solid):
    """Front silhouette in the (x, y) plane as shapely geometry."""
    return solid.project().to_shapely()


def top_view(solid: Solid):
    """Silhouette seen from above, in (x, z) coordinates."""
    # rotate -90 about x: (x, y, z) -> (x, z, -y); projecting along Z then gives (x, z)
    return solid.rotate(-90, 0, 0).project().to_shapely()


def section_x(solid: Solid, x: float):
    """Cross-section at plane X = x, returned in (z, y) coordinates."""
    # rotate -90 about y: (x, y, z) -> (-z, y, x); the plane X=x becomes Z'=x and
    # in-plane coords are (x'=-z, y'=y) -> mirror x' for (z, y).
    from shapely import affinity

    g = solid.rotate(0, -90, 0).slice(x).to_shapely()
    return affinity.scale(g, xfact=-1.0, yfact=1.0, origin=(0, 0))
