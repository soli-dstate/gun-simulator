"""Browser fallback: a tiny local HTTP server for the same UI (python -m gun_sim.ui --browser).

The desktop window (app.py) is the normal way to run the UI; this is handy for
debugging in a full browser. Only the standard library is used, and the server
binds to 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api

# Windows can map .js to text/plain via the registry, which breaks ES modules.
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data):
        self._send(status, json.dumps(data).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/schema":
            self._json(200, api.schema())
            return
        root = api.STATIC_DIR.resolve()
        file = (root / (path.lstrip("/") or "index.html")).resolve()
        if file.is_relative_to(root) and file.is_file():
            ctype = CONTENT_TYPES.get(file.suffix) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._send(200, file.read_bytes(), ctype)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if self.path == "/api/simulate":
                self._json(200, api.simulate(json.loads(body)))
            elif self.path == "/api/cycle":
                self._json(200, api.cycle(json.loads(body)))
            elif self.path == "/api/synthesize":
                self._json(200, api.synthesize(json.loads(body)))
            elif self.path == "/api/plume":
                self._json(200, api.plume_field(json.loads(body)))
            elif self.path == "/api/trajectory":
                self._json(200, api.trajectory(json.loads(body)))
            elif self.path == "/api/design":
                self._json(200, api.design(json.loads(body)))
            elif self.path == "/api/target":
                self._json(200, api.target(json.loads(body)))
            elif self.path == "/api/projectile":
                self._json(200, api.projectile_design(json.loads(body)))
            elif self.path == "/api/check":
                self._json(200, api.check(json.loads(body)))
            elif self.path == "/api/parse":
                self._json(200, api.parse_toml(body.decode()))
            else:
                self._json(404, {"error": "not found"})
        except Exception as e:  # report errors instead of hanging the UI
            self._json(400 if isinstance(e, api.USER_ERRORS) else 500, {"error": api.error_message(e)})


def serve(port: int = 0, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Gun simulator running at {url}")
    print("Press Ctrl+C to quit.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gun_sim.ui.server", description="Serve the gun simulator UI to a browser.")
    parser.add_argument("--port", type=int, default=0, help="port to listen on (default: any free port)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = parser.parse_args(argv)
    api.warm()
    serve(args.port, not args.no_browser)
