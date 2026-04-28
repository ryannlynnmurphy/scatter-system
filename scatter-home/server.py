"""Scatter Home — laptop forward surface. Suite tiles + same launch contract as Catalog."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent.resolve()
INDEX_HTML = HERE / "index.html"
TOKENS_CSS = HERE.parent / "scatter-design-system" / "tokens.css"

_cat_mod = None


def _load_catalog():
    global _cat_mod
    if _cat_mod is not None:
        return _cat_mod
    cat_path = HERE.parent / "scatter-catalog" / "server.py"
    spec = importlib.util.spec_from_file_location("scatter_catalog_server", cat_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scatter-catalog server")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _cat_mod = mod
    return mod


def suite_for_home():
    try:
        items = _load_catalog().list_suite()
    except Exception:
        return []
    return [x for x in items if x.get("slug") != "home"]


def launch_tile(spec: dict) -> dict:
    try:
        return _load_catalog().launch(spec)
    except Exception as e:
        return {"ok": False, "detail": str(e)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, status: int, payload: dict | list) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self.send_error(404, "missing")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path
        if path == "/":
            return self._file(INDEX_HTML, "text/html; charset=utf-8")
        if path == "/tokens.css":
            return self._file(TOKENS_CSS, "text/css")
        if path == "/api/suite":
            return self._json(200, suite_for_home())
        self.send_error(404, "not found")

    def do_POST(self) -> None:
        if self.path != "/api/launch":
            self.send_error(404, "not found")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        try:
            spec = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "detail": "bad json"})
        return self._json(200, launch_tile(spec))


def main() -> None:
    port = int(os.environ.get("PORT", "3080"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stdout.write(f"\n  Scatter Home at http://127.0.0.1:{port}\n\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
