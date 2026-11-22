"""Foreground loopback-only workbench server, intentionally not an Internet service."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import sys
import threading
from urllib.parse import unquote, urlsplit

from . import __version__
from .api import _allowed, _object, capabilities, dispatch
from .io import MAX_INPUT_BYTES, loads

_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                  ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                  ".png": "image/png", ".json": "application/json; charset=utf-8", ".ico": "image/x-icon"}
_WORKERS = threading.BoundedSemaphore(2)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = f"RecursiveCal/{__version__}"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, value: dict) -> None:
        self._respond(status, json.dumps(value, allow_nan=False).encode(), "application/json; charset=utf-8")

    def _local_request(self) -> bool:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in allowed:
            self._json(403, {"error": "loopback Host required"})
            return False
        if origin is not None and origin != f"http://{host}":
            self._json(403, {"error": "same-origin request required"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._json(403, {"error": "cross-site request rejected"})
            return False
        return True

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._local_request():
            return
        path = unquote(urlsplit(self.path).path)
        if path == "/api/capabilities":
            self._json(200, capabilities())
            return
        if path == "/api/inquiry/capabilities":
            from .inquiry import capabilities as inquiry_capabilities
            self._json(200, inquiry_capabilities())
            return
        if path == "/api/health":
            self._json(200, {"status": "ok", "version": __version__, "hardware_connected": False})
            return
        if path == "/":
            path = "/index.html"
        parts = path.lstrip("/").split("/")
        if any(part in ("", ".", "..") or "\\" in part or "\x00" in part for part in parts):
            self._json(404, {"error": "asset not found"})
            return
        asset = files("recursivecal_lab").joinpath("web", *parts)
        suffix = "." + parts[-1].rsplit(".", 1)[-1]
        if suffix not in _CONTENT_TYPES or not asset.is_file():
            self._json(404, {"error": "asset not found"})
            return
        self._respond(200, asset.read_bytes(), _CONTENT_TYPES[suffix])

    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "Content-Type application/json required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_INPUT_BYTES:
            self._json(413, {"error": "a positive Content-Length no greater than 8 MiB is required"})
            return
        if not _WORKERS.acquire(blocking=False):
            self._json(429, {"error": "two calculations are already running; try again after they finish"})
            return
        self._stream_started = False
        try:
            payload = loads(self.rfile.read(length).decode("utf-8"))
            if urlsplit(self.path).path == "/api/inquiry/stream":
                from .inquiry import run_study
                body = _object(payload, "request")
                _allowed(body, {"case", "seed", "policy", "max_tests", "budget", "rig_version"})
                report = run_study(**body, on_event=self._stream_event)
                self._stream_event({"type": "complete", "report": report})
                return
            result = dispatch(urlsplit(self.path).path, payload)
            self._json(200, result)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            if self._stream_started:
                self._stream_event({"type": "error", "error": str(exc)})
            else:
                self._json(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # A closed monitor cancels this foreground request at an event
            # boundary. It does not leave a detached calculation running.
            self.close_connection = True
        except Exception:
            error = "calculation failed; inspect the foreground terminal for details"
            if self._stream_started:
                self._stream_event({"type": "error", "error": error})
            else:
                self._json(500, {"error": error})
            import traceback
            traceback.print_exc(file=sys.stderr)
        finally:
            _WORKERS.release()

    def _stream_event(self, event: dict) -> None:
        if not self._stream_started:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Connection", "close")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self._stream_started = True
            self.close_connection = True
        self.wfile.write((json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n").encode())
        self.wfile.flush()


def serve(*, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("the workbench only binds to 127.0.0.1 or localhost")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    with WorkbenchServer(("127.0.0.1", port), Handler) as server:
        print(f"RecursiveCal {__version__}: http://127.0.0.1:{port}", flush=True)
        print("Running in this terminal. Ctrl+C stops the server. Hardware connected: no.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nWorkbench stopped.", flush=True)

