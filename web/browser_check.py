"""Load the static site in headless Firefox and report status, console and a screenshot.

    python web/browser_check.py [--dist build/dist] [--timeout 300] [--shot out.png]
                                [--eval "js expression"]...

Uses Firefox's built-in WebDriver BiDi over a websocket (tornado), so no
Selenium/geckodriver is needed. Exits non-zero if the page reports an error.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import http.server
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from tornado.websocket import websocket_connect

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm"}

        def log_message(self, *a):
            pass

    port = free_port()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(directory)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


class Bidi:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.logs: list[str] = []
        self.reader = asyncio.ensure_future(self._read())

    async def _read(self):
        while True:
            raw = await self.ws.read_message()
            if raw is None:
                return
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            elif msg.get("method") == "log.entryAdded":
                p = msg["params"]
                self.logs.append(f"[{p.get('level')}] {p.get('text')}")

    async def send(self, method: str, **params):
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = fut
        await self.ws.write_message(json.dumps({"id": self.next_id, "method": method, "params": params}))
        msg = await fut
        if msg.get("type") == "error":
            raise RuntimeError(f"{method}: {msg.get('error')}: {msg.get('message')}")
        return msg["result"]

    async def evaluate(self, ctx: str, expr: str):
        r = await self.send("script.evaluate", expression=expr, target={"context": ctx}, awaitPromise=True)
        if r.get("type") == "exception":
            return {"exception": r["exceptionDetails"].get("text")}
        return r["result"].get("value")


async def check(args) -> int:
    httpd, port = serve(args.dist)
    dbg = free_port()
    profile = Path(tempfile.mkdtemp(prefix="pegtrace-ff-"))
    ff = subprocess.Popen(
        ["firefox", "--headless", "--no-remote", "--profile", str(profile),
         "--remote-debugging-port", str(dbg), "--window-size", f"{args.width},{args.height}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = None
        for _ in range(100):
            try:
                ws = await websocket_connect(f"ws://127.0.0.1:{dbg}/session", max_message_size=512 * 1024 * 1024)
                break
            except Exception:
                await asyncio.sleep(0.3)
        if ws is None:
            raise SystemExit("could not connect to Firefox remote agent")
        b = Bidi(ws)
        await b.send("session.new", capabilities={})
        await b.send("session.subscribe", events=["log.entryAdded"])
        tree = await b.send("browsingContext.getTree")
        ctx = tree["contexts"][0]["context"]
        url = f"http://127.0.0.1:{port}/{args.page}"
        t0 = time.time()
        await b.send("browsingContext.navigate", context=ctx, url=url, wait="complete")
        state = None
        while time.time() - t0 < args.timeout:
            state = await b.evaluate(ctx, "globalThis.__pegtrace_state")
            if state in ("ready", "error"):
                break
            await asyncio.sleep(1)
        print(f"state: {state} after {time.time() - t0:.1f}s")
        if state == "ready":
            await asyncio.sleep(args.settle)
        for expr in args.eval or []:
            print(f"eval {expr!r}: {await b.evaluate(ctx, expr)}")
        body = await b.evaluate(ctx, "document.body.innerText.slice(0, 2000)")
        print("---- page text ----")
        print(body)
        if args.shot:
            shot = await b.send("browsingContext.captureScreenshot", context=ctx, origin="document")
            Path(args.shot).write_bytes(base64.b64decode(shot["data"]))
            print(f"screenshot: {args.shot}")
        print("---- console ----")
        for line in b.logs[-args.max_logs:]:
            print(line[:2000])
        b.reader.cancel()
        ws.close()
        return 0 if state == "ready" else 1
    finally:
        ff.terminate()
        try:
            ff.wait(10)
        except subprocess.TimeoutExpired:
            ff.kill()
        httpd.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=Path, default=ROOT / "build" / "dist")
    ap.add_argument("--page", default="index.html")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--shot", default=None)
    ap.add_argument("--eval", action="append")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--max-logs", type=int, default=60)
    raise SystemExit(asyncio.run(check(ap.parse_args())))


if __name__ == "__main__":
    main()
