"""A loopback-only preview/picker server exposing only this run and viewer assets."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import json
import mimetypes
import threading

ASSETS = Path(__file__).resolve().parent / "assets"


class PreviewServer:
    def __init__(self, run, runtime, config, scene=None, port=0):
        self.run = Path(run)
        self.runtime = runtime
        self.config = config
        self.scene = scene
        self.selection = None
        self.selected = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, payload, status=200):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parsed = urlparse(self.path)
                route = unquote(parsed.path)
                if route == "/job.json":
                    return self.send_json(outer.config)
                if route == "/api/assess":
                    try:
                        args = parse_qs(parsed.query)
                        uv = [float(args["x"][0]), float(args["y"][0])]
                        result = outer.scene.assess(
                            uv,
                            outer.config["options"]["strength"],
                            outer.config["options"]["crop"],
                            outer.config["options"].get("crop_mode", "center"),
                        )
                        return self.send_json(result)
                    except (KeyError, ValueError, AttributeError) as error:
                        return self.send_json({"error": str(error)}, 400)
                paths = {
                    "/": ASSETS / "viewer.html",
                    "/picker": ASSETS / "picker.html",
                    "/viewer.js": ASSETS / "viewer.js",
                    "/preview.jpg": outer.run / "preview.jpg",
                    "/scene.ply": outer.run / "scene.ply",
                    "/video.mp4": outer.run / "dolly_zoom.mp4",
                    "/suitability.json": outer.run / "suitability.json",
                }
                target = paths.get(route)
                if route.startswith("/vendor/"):
                    if not route.startswith(("/vendor/three/", "/vendor/@sparkjsdev/spark/")):
                        return self.send_error(403)
                    candidate = (
                        Path(outer.runtime["node_modules"]) / route.removeprefix("/vendor/")
                    ).resolve()
                    try:
                        candidate.relative_to(Path(outer.runtime["node_modules"]).resolve())
                    except ValueError:
                        return self.send_error(403)
                    target = candidate
                if not target or not target.is_file():
                    return self.send_error(404)
                size = target.stat().st_size
                low, high = 0, size - 1
                partial = False
                if self.headers.get("Range"):
                    try:
                        value = self.headers["Range"].removeprefix("bytes=").split(",")[0]
                        left, right = value.split("-")
                        low = int(left or 0)
                        high = min(int(right) if right else size - 1, size - 1)
                        if low < 0 or high < low or low >= size:
                            raise ValueError
                        partial = True
                    except ValueError:
                        return self.send_error(416)
                self.send_response(206 if partial else 200)
                self.send_header(
                    "Content-Type",
                    mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(high - low + 1))
                if partial:
                    self.send_header("Content-Range", f"bytes {low}-{high}/{size}")
                self.end_headers()
                try:
                    with target.open("rb") as stream:
                        stream.seek(low)
                        remaining = high - low + 1
                        while remaining:
                            chunk = stream.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                if urlparse(self.path).path != "/api/anchor":
                    return self.send_error(404)
                if self.headers.get("Origin") not in (None, outer.url):
                    return self.send_error(403)
                if not outer.scene:
                    return self.send_json({"error": "This viewer is read-only."}, 403)
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size <= 0 or size > 4096:
                        raise ValueError("Invalid request size.")
                    selection = json.loads(self.rfile.read(size))
                    uv = [float(selection["x"]), float(selection["y"])]
                    outer.scene.anchor(uv)
                    outer.selection = {
                        "uv": uv,
                        "label": str(selection.get("label") or "Selected point")[:100],
                    }
                    outer.selected.set()
                    return self.send_json({"ok": True})
                except (ValueError, KeyError, TypeError) as error:
                    return self.send_json({"error": str(error)}, 400)

        self.http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}"

    def __enter__(self):
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
