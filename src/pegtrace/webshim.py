"""Make Panel's in-browser code (written for Pyodide) run on pyjs.

pyjs (emscripten-forge) ships a tiny ``pyodide`` polyfill. Panel's
``panel.io.pyodide`` additionally needs ``js`` as an importable module,
``pyodide.ffi.create_proxy``/``jsnull``, ``pyodide.code.run_js`` and a few
Pyodide-flavoured conversions. Call :func:`install` before importing panel.
"""

from __future__ import annotations

import sys
import types

_installed = False
_handles: list = []  # keep proxied callables alive


class _JsNull:
    """Sentinel: pyjs converts JS null to None, so nothing is ever ``jsnull``."""

    def __repr__(self):
        return "jsnull"


def install() -> None:
    global _installed
    if _installed:
        return
    import pyjs
    from pyjs import JsValue

    js = sys.modules["pyjs_core.js"]
    sys.modules["js"] = js
    internal = sys.modules["pyjs_core"].internal

    # Panel and HoloViews detect the browser through `'_pyodide' in sys.modules`; without
    # it Panel takes server code paths (e.g. hold() schedules next-tick callbacks whose
    # SessionCallbackAdded events cannot be serialized to the browser document).
    sys.modules.setdefault("_pyodide", types.ModuleType("_pyodide"))

    pyodide = sys.modules.get("pyodide") or types.ModuleType("pyodide")
    ffi = sys.modules.get("pyodide.ffi") or types.ModuleType("pyodide.ffi")
    code = types.ModuleType("pyodide.code")
    sys.modules["pyodide"] = pyodide
    sys.modules["pyodide.ffi"] = ffi
    sys.modules["pyodide.code"] = code
    pyodide.ffi = ffi
    pyodide.code = code

    object_from_entries = js.Object.fromEntries

    def to_js(value, *, dict_converter=None, create_pyproxies=True, depth=-1, **_):
        if isinstance(value, (bytes, bytearray, memoryview)):
            b = bytes(value)
            return internal.bytes_to_typed_array(b, len(b))  # Uint8Array like Pyodide
        if dict_converter is None:
            dict_converter = object_from_entries  # plain objects, so Object.entries() works
        return pyjs.to_js(value, dict_converter=dict_converter)

    py_of_proxy: dict[int, object] = {}  # id(js function) -> python callable

    def create_proxy(fn, **_):
        jsf, handle = pyjs.create_callable(fn)
        _handles.append((jsf, handle))  # keep both alive (ids stay valid)
        py_of_proxy[id(jsf)] = fn
        return jsf

    def create_once_callable(fn, **_):
        return pyjs.create_once_callable(fn)

    def run_js(src: str, **_):
        return js.eval(src)

    ffi.to_js = to_js
    ffi.create_proxy = create_proxy
    ffi.create_once_callable = create_once_callable
    ffi.jsnull = _JsNull()
    ffi.JsProxy = JsValue
    ffi.JsException = pyjs.JsException
    code.run_js = run_js
    pyodide.to_js = to_js

    # Pyodide-style JsProxy helpers used by panel.io.pyodide
    kind_of = js.eval(
        "(v) => v === null || v === undefined ? 'null' : Array.isArray(v) ? 'array'"
        " : v instanceof ArrayBuffer ? 'arraybuffer' : ArrayBuffer.isView(v) ? 'view'"
        " : v instanceof Map ? 'map' : typeof v === 'object' ? 'object' : typeof v")
    as_u8 = js.eval(
        "(v) => v instanceof ArrayBuffer ? new Uint8Array(v)"
        " : ArrayBuffer.isView(v) ? new Uint8Array(v.buffer, v.byteOffset, v.byteLength)"
        " : (v && v.buffer instanceof ArrayBuffer) ? new Uint8Array(v.buffer) : new Uint8Array(0)")
    has_buffer = js.eval("(v) => v !== null && typeof v === 'object' && v.buffer instanceof ArrayBuffer"
                         " && !ArrayBuffer.isView(v)")
    entries = js.Object.entries
    _orig_to_py = JsValue.to_py

    def _bytes_of(v) -> bytes:
        return bytes(memoryview(pyjs.to_py(as_u8(v))).cast("B"))

    def _convert(v, default_converter):
        """JS -> Python like Pyodide's to_py: containers recurse, objects that hold a
        binary ``buffer`` (BokehJS Buffer) go to ``default_converter``."""
        if not isinstance(v, JsValue):
            return v
        kind = str(kind_of(v))
        if kind == "null":
            return None
        if kind == "array":
            return [_convert(x, default_converter) for x in v]
        if kind in ("arraybuffer", "view"):
            return _bytes_of(v)
        if kind == "map":
            return {_convert(k, default_converter): _convert(x, default_converter) for k, x in v.entries()}
        if kind == "object":
            if default_converter is not None and bool(has_buffer(v)):
                return default_converter(v, None, None)
            return {str(k): _convert(x, default_converter) for k, x in entries(v)}
        return _orig_to_py(v)

    def to_py(self, *args, default_converter=None, **kwargs):
        if default_converter is None:
            return _orig_to_py(self)
        return _convert(self, default_converter)

    def to_bytes(self):
        return _bytes_of(self)

    def object_entries(self):
        return [(str(k), x) for k, x in entries(self)]

    # Like a Pyodide PyProxy: calling a create_proxy() result from Python calls the
    # Python function directly (Panel passes keyword arguments this way).
    _orig_call = JsValue.__call__

    def _call(self, *args, **kwargs):
        fn = py_of_proxy.get(id(self))
        if fn is not None:
            return fn(*args, **kwargs)
        if kwargs:
            raise TypeError("JS functions do not take keyword arguments")
        return _orig_call(self, *args)

    JsValue.__call__ = _call
    JsValue.to_py = to_py
    JsValue.to_bytes = to_bytes
    JsValue.object_entries = object_entries
    _installed = True
