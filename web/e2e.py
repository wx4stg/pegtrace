"""End-to-end UI test with Playwright (real clicks, polygon drawing, downloads).

    python web/e2e.py --serve              # starts `panel serve web/app_entry.py`
    python web/e2e.py --dist build/dist    # static site (Python in the browser)
    python web/e2e.py --url http://...     # an already running app

Screenshots of every step go to --shots (default: build/e2e).
Exits non-zero on the first failed check.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_dir(directory: Path) -> str:
    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm"}

        def log_message(self, *a):
            pass

    port = free_port()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(directory)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/index.html"


def start_panel() -> tuple[subprocess.Popen, str]:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "panel", "serve", str(ROOT / "web" / "app_entry.py"), "--port", str(port),
         "--address", "127.0.0.1", "--allow-websocket-origin", f"127.0.0.1:{port}"],
        cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}/app_entry"
    for _ in range(120):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return proc, url
        except OSError:
            time.sleep(0.5)
    raise SystemExit("panel serve did not start")


class Run:
    def __init__(self, page: Page, shots: Path):
        self.page = page
        self.shots = shots
        self.n = 0
        self.errors: list[str] = []
        self.step = "boot"
        self.console: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda e: self.errors.append(
            f"[{self.step}] uncaught: {getattr(e, 'name', '')} {getattr(e, 'message', e)} {(getattr(e, 'stack', '') or '')[:400]}"))

    def _on_console(self, m):
        text = m.text
        if m.type == "error" and text.strip() in ("Object", "JSHandle@object", "[object Object]"):
            try:  # describe error objects instead of printing "Object"
                text = " | ".join(a.evaluate("e => e && (e.stack || e.message || JSON.stringify(e))") or "?"
                                  for a in m.args)
            except Exception:
                pass
        if m.type == "error":
            loc = m.location or {}
            text = f"{text} (at {loc.get('url', '?')}:{loc.get('lineNumber', '?')})"
            self.errors.append(text)
        self.console.append(f"[{m.type}] {text}")

    def shot(self, name: str):
        self.n += 1
        path = self.shots / f"{self.n:02d}_{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        print(f"  screenshot {path.name}")

    def click(self, text: str, exact=True, nth=0):
        self.page.get_by_role("button", name=text, exact=exact).nth(nth).click()

    def tab(self, title: str):
        self.page.get_by_text(title, exact=True).first.click()
        self.page.wait_for_timeout(600)

    def wait_text(self, text: str, timeout=60_000):
        self.page.get_by_text(text).first.wait_for(state="visible", timeout=timeout)

    def check(self, cond: bool, msg: str):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            self.shot("failure")
            raise SystemExit(1)

    def visible_canvas(self):
        """Bounding box of the largest visible bokeh canvas (the main plot)."""
        boxes = []
        for c in self.page.locator("canvas").all():
            try:
                if c.is_visible():
                    b = c.bounding_box()
                    if b and b["width"] > 200:
                        boxes.append(b)
            except Exception:
                pass
        return max(boxes, key=lambda b: b["width"] * b["height"]) if boxes else None


def run(url: str, shots: Path, boot_timeout: float) -> None:
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1500, "height": 1000}, accept_downloads=True)
        ctx.add_init_script("""
          window.addEventListener('unhandledrejection', (e) => {
            const r = e.reason;
            let d;
            try { d = r && (r.stack || r.message) ? (r.stack || r.message)
                       : JSON.stringify(r, Object.getOwnPropertyNames(Object(r))).slice(0, 800); }
            catch (err) { d = String(r); }
            console.warn('UNHANDLED REJECTION: ' + d + ' keys=' + (r && typeof r === 'object' ? Object.keys(r).join(',') : ''));
          });
          window.addEventListener('error', (e) => {
            let d;
            try { d = JSON.stringify(e.error, Object.getOwnPropertyNames(Object(e.error))).slice(0, 800); }
            catch (err) { d = String(e.error); }
            console.warn('UNHANDLED ERROR: ' + e.message + ' @ ' + e.filename + ':' + e.lineno + ':' + e.colno
                         + ' obj=' + d + ' ctor=' + (e.error && e.error.constructor && e.error.constructor.name));
          });""")
        page = ctx.new_page()
        r = Run(page, shots)
        try:
            steps(r, page, url, boot_timeout)
        except BaseException:
            r.shot("failure")
            print("---- errors and rejections ----")
            for line in r.console:
                if "UNHANDLED" in line or line.startswith("[error]"):
                    print(line[:1500])
            print("---- last console messages ----")
            for line in r.console[-25:]:
                print(line if len(line) < 3000 else line[:300] + "\n  ...\n" + line[-1500:])
            raise
        finally:
            browser.close()


def steps(r: Run, page: Page, url: str, boot_timeout: float) -> None:
    if True:
        print(f"opening {url}")
        t0 = time.time()
        page.goto(url)
        r.wait_text("Try the sample photo", timeout=boot_timeout * 1000)
        print(f"  app ready after {time.time() - t0:.1f}s")

        print("step 1: photo")

        r.step = "step 1: photo"
        r.click("Try the sample photo")
        r.wait_text("Loaded the sample photo")
        page.wait_for_timeout(1500)
        r.shot("scale_step")

        print("step 2: scale")

        r.step = "step 2: scale"
        r.click("Apply scale")
        r.wait_text("Scale applied")
        page.wait_for_timeout(1500)

        rng = page.evaluate("""() => {
          const all = Bokeh.documents.flatMap(d => [...d.all_models]);
          // newest poly_select plot (replaced plots can linger in all_models)
          const p = all.filter(m => m.toolbar && m.toolbar.tools.some(t => (t.type||t.constructor.name) === 'PolySelectTool')).pop();
          return p ? [p.x_range.start, p.x_range.end, p.y_range.start, p.y_range.end] : null;
        }""")
        r.check(rng is not None and rng[0] < 0 and rng[1] > 200 and rng[2] < 0 and rng[3] > 250,
                f"trace plot shows the whole calibrated image (ranges {rng})")
        print("step 3: trace by hand with poly_select")

        r.step = "step 3: trace by hand with poly_select"
        box = r.visible_canvas()
        r.check(box is not None, "trace plot canvas visible")
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        pts = [(-60, -80), (70, -70), (80, 60), (-50, 90)]
        for dx, dy in pts:
            page.mouse.click(cx + dx, cy + dy)
            page.wait_for_timeout(450)  # faster taps register as double-taps
        page.keyboard.press("Enter")  # bokeh 3 finishes poly_select with Enter or press-and-hold
        page.wait_for_timeout(1000)
        r.shot("after_hand_trace_clicks")
        r.wait_text("Outline:", timeout=20_000)
        r.check(True, "hand-drawn polygon reached Python")
        r.shot("hand_trace")
        r.click("Auto-detect outline")
        r.wait_text("Outline detected")
        page.wait_for_timeout(1500)
        r.shot("auto_trace")
        r.click("Use this outline")

        print("step 4: orientation")

        r.step = "step 4: orientation"
        page.wait_for_timeout(800)
        r.click("Auto: long axis vertical")
        page.wait_for_timeout(1500)
        r.shot("orientation")
        r.click("Continue to design")

        print("step 5: design")

        r.step = "step 5: design"
        r.wait_text("Size:")
        page.wait_for_timeout(1500)
        r.shot("design_front")
        r.tab("Side section")
        r.shot("design_side")
        r.tab("3D")
        page.wait_for_timeout(3000)
        r.shot("design_3d")
        r.step = "after 3d"
        r.tab("Front")

        print("step 4b/5b: shelf mode")

        r.step = "step 4b/5b: shelf mode"
        r.tab("4 · Orientation")
        r.click("Shelf (top-down footprint)")
        page.wait_for_timeout(1000)
        r.tab("5 · Design")
        r.wait_text("Size:")
        r.tab("Top")
        page.wait_for_timeout(1500)
        r.shot("shelf_top")
        r.tab("3D")
        page.wait_for_timeout(3000)
        r.shot("shelf_3d")
        r.tab("Front")
        r.tab("4 · Orientation")
        r.click("Flat against the board")
        page.wait_for_timeout(1000)
        r.tab("5 · Design")
        r.wait_text("Size:")

        print("step 6: export")

        r.step = "step 6: export"
        r.click("Continue to export")
        page.wait_for_timeout(800)
        with page.expect_download(timeout=60_000) as dl:
            r.click("Download STL", exact=False)
            page.wait_for_timeout(1500)
            # FileDownload without embed: first click prepares the file, second downloads
            if not r.page.get_by_text("STL ready").count():
                r.click("Download STL", exact=False)
        path = dl.value.path()
        size = Path(path).stat().st_size
        r.check(size > 10_000, f"downloaded STL ({size / 1024:.0f} KB)")
        r.shot("export")

        bad = [e for e in r.errors if "favicon" not in e]
        r.check(not bad, "no browser console errors" + ("" if not bad else f": {bad[:5]}"))


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--serve", action="store_true")
    g.add_argument("--dist", type=Path)
    g.add_argument("--url")
    ap.add_argument("--shots", type=Path, default=ROOT / "build" / "e2e")
    ap.add_argument("--boot-timeout", type=float, default=240)
    a = ap.parse_args()
    proc = None
    try:
        if a.serve:
            proc, url = start_panel()
        elif a.dist:
            url = serve_dir(a.dist)
        else:
            url = a.url
        run(url, a.shots, a.boot_timeout)
        print("E2E PASSED")
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
