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

    def create_proxy(fn, **_):
        jsf, handle = pyjs.create_callable(fn)
        _handles.append(handle)
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
    _orig_to_py = JsValue.to_py

    def to_py(self, *args, default_converter=None, **kwargs):
        return _orig_to_py(self)

    def to_bytes(self):
        arr = js.Uint8Array.new(self.buffer if hasattr(self, "buffer") else self)
        return bytes(pyjs.to_py(arr))

    JsValue.to_py = to_py
    JsValue.to_bytes = to_bytes
    JsValue.object_entries = lambda self: js.Object.entries(self)
    _installed = True
