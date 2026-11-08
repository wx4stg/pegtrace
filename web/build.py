"""Build the static PegTrace site (Python runs in the browser via pyjs).

    python web/build.py [--app web/poc_app.py] [--recreate-env] [--app-only] [--out build/dist]

Steps:
1. create an emscripten-wasm32 conda env from emscripten-forge (+ conda-forge noarch)
2. pack it with empack, then append the pegtrace package as an extra tarball
3. copy the pyjs browser runtime and render index.html (CDN versions taken from the env)

Serve the output with any static file server, e.g.
    python -m http.server -d build/dist 8000
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ENV_PREFIX = ROOT / "build" / "wasm-env"
EMPACK = Path(sys.executable).with_name("empack")
CHANNELS = ["https://prefix.dev/emscripten-forge-4x", "conda-forge"]
PACKAGES = [
    "python", "pyjs", "numpy", "pillow", "shapely", "contourpy",
    "panel", "bokeh", "holoviews", "param",
]
MANIFOLD_JS_VERSION = "3.5.4"
VTK_JS_VERSION = "30.1.0"  # must match panel.models.vtk.VTK_VERSION of the env's panel


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, **kw)


def ensure_env(recreate: bool) -> None:
    if ENV_PREFIX.exists() and not recreate:
        return
    if ENV_PREFIX.exists():
        shutil.rmtree(ENV_PREFIX)
    chans = [a for c in CHANNELS for a in ("-c", c)]
    run(["micromamba", "create", "-y", "-p", ENV_PREFIX, "--platform", "emscripten-wasm32",
         "--override-channels", *chans, *PACKAGES])


def env_version(name: str) -> str:
    for meta in (ENV_PREFIX / "conda-meta").glob(f"{name}-*.json"):
        d = json.loads(meta.read_text())
        if d["name"] == name:
            return d["version"]
    raise SystemExit(f"{name} not found in {ENV_PREFIX}")


def python_site_packages() -> str:
    v = ".".join(env_version("python").split(".")[:2])
    return f"/lib/python{v}/site-packages"


def build(app: Path, out: Path, recreate: bool, app_only: bool = False) -> None:
    env_out = out / "env"
    meta = env_out / "empack_env_meta.json"
    app_only = app_only and meta.exists() and "pegtrace.tar.gz" in meta.read_text()
    if not app_only:
        ensure_env(recreate)
        if out.exists():
            shutil.rmtree(out)
        env_out.mkdir(parents=True)
        run([EMPACK, "pack", "env", "--env-prefix", ENV_PREFIX, "--outdir", env_out])

    # our package, staged without caches
    stage = ROOT / "build" / "stage" / "pegtrace"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(ROOT / "src" / "pegtrace", stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    run([EMPACK, "pack", "dir", "--host-dir", stage, "--mount-dir", f"{python_site_packages()}/pegtrace",
         "--outname", "pegtrace.tar.gz", "--outdir", env_out])
    if not app_only:  # the meta file already lists pegtrace.tar.gz otherwise
        run([EMPACK, "pack", "append", "--env-meta", env_out, "--tarfile", env_out / "pegtrace.tar.gz"])

    rt = ENV_PREFIX / "lib_js" / "pyjs"
    for f in ("pyjs_runtime_browser.js", "pyjs_runtime_browser.wasm"):
        shutil.copy2(rt / f, out / f)
    shutil.copy2(app, out / app.name)

    env_mb = sum(p.stat().st_size for p in env_out.iterdir()) / 1e6
    html = (WEB / "index.html.in").read_text()
    subs = {
        "TITLE": "PegTrace",
        "BOKEH": env_version("bokeh"),
        "PANEL": env_version("panel"),
        "MANIFOLD": MANIFOLD_JS_VERSION,
        "APP": app.name,
        "ENV_MB": f"{env_mb:.0f}",
        "EXTRA_HEAD": f'  <script src="https://cdn.jsdelivr.net/npm/vtk.js@{VTK_JS_VERSION}/vtk.js"></script>',
    }
    for k, v in subs.items():
        html = html.replace("{" + k + "}", v)
    (out / "index.html").write_text(html)
    print(f"built {out} ({env_mb:.0f} MB of packages)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=Path, default=WEB / "poc_app.py")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "dist")
    ap.add_argument("--recreate-env", action="store_true")
    ap.add_argument("--app-only", action="store_true", help="reuse packed env; repack pegtrace + page only")
    a = ap.parse_args()
    build(a.app.resolve(), a.out.resolve(), a.recreate_env, a.app_only)


if __name__ == "__main__":
    main()
