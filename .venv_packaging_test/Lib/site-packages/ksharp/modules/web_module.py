from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ksharp.runtime import Interpreter


class KarshipWebServer:
    def __init__(self, interpreter: "Interpreter", host: str = "127.0.0.1", port: int = 8080) -> None:
        self._interpreter = interpreter
        self.host = host
        self.port = int(port)
        self._routes: dict[str, Any] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def route(self, path: str, handler: Any) -> str:
        normalized = self._normalize_path(path)
        self._routes[normalized] = handler
        return normalized

    def routes(self) -> list[str]:
        return sorted(self._routes.keys())

    def run(self) -> dict[str, Any]:
        if self._server is not None:
            return {"running": True, "host": self.host, "port": self.port}

        module = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # type: ignore
                module._dispatch("GET", self)

            def do_POST(self):  # type: ignore
                module._dispatch("POST", self)

            def log_message(self, _format, *args):  # type: ignore
                # Silence default HTTP logs.
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return {"running": True, "host": self.host, "port": self.port}

    def stop(self) -> bool:
        if self._server is None:
            return False
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        return True

    def _dispatch(self, method: str, handler: BaseHTTPRequestHandler) -> None:
        parsed = urllib.parse.urlparse(handler.path)
        path = self._normalize_path(parsed.path)
        route_handler = self._routes.get(path)
        if route_handler is None:
            self._write_response(handler, 404, {"error": "route-not-found", "path": path})
            return

        content_length = int(handler.headers.get("Content-Length", "0") or 0)
        body_raw = handler.rfile.read(content_length) if content_length > 0 else b""
        body_text = body_raw.decode("utf-8", errors="replace")
        request_obj = {
            "method": method,
            "path": path,
            "query": dict(urllib.parse.parse_qsl(parsed.query)),
            "body": body_text,
            "headers": {k: v for k, v in handler.headers.items()},
        }

        result = self._invoke(route_handler, [request_obj])
        status, response_body, response_headers = self._normalize_response(result)
        self._write_response(handler, status, response_body, response_headers)

    def _invoke(self, callee: Any, args: list[Any]) -> Any:
        if callable(callee):
            try:
                return callee(*args)
            except TypeError:
                return callee()
        return self._interpreter.call(callee, args)

    def _normalize_response(self, result: Any) -> tuple[int, Any, dict[str, str]]:
        if isinstance(result, tuple):
            if len(result) == 2:
                status, body = result
                return int(status), body, {}
            if len(result) == 3:
                status, body, headers = result
                return int(status), body, dict(headers)
        return 200, result, {}

    def _write_response(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        body: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        headers = headers or {}
        if isinstance(body, (dict, list)):
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        else:
            payload = str(body).encode("utf-8")
            content_type = "text/plain; charset=utf-8"

        handler.send_response(int(status))
        handler.send_header("Content-Type", headers.get("Content-Type", content_type))
        handler.send_header("Content-Length", str(len(payload)))
        for key, value in headers.items():
            if key.lower() == "content-type":
                continue
            handler.send_header(str(key), str(value))
        handler.end_headers()
        handler.wfile.write(payload)

    @staticmethod
    def _normalize_path(path: str) -> str:
        raw = str(path).strip() or "/"
        if not raw.startswith("/"):
            raw = f"/{raw}"
        return raw


class WebRuntimeModule:
    def __init__(self, interpreter: "Interpreter", memory_manager) -> None:
        self._interpreter = interpreter
        self._memory_manager = memory_manager
        self._default_server: KarshipWebServer | None = None

    def page(self, title: str, body_html: str) -> str:
        compact = self._memory_manager.mode == "eco"
        space = "" if compact else " "
        return (
            "<!doctype html>"
            "<html><head><meta charset='utf-8'>"
            f"<title>{title}</title></head>{space}"
            f"<body>{body_html}</body></html>"
        )

    def json(self, value: Any) -> str:
        if self._memory_manager.mode == "eco":
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(value, ensure_ascii=False)

    def create_server(self, host: str = "127.0.0.1", port: int = 8080) -> KarshipWebServer:
        return KarshipWebServer(self._interpreter, host=host, port=port)

    def route(self, path: str, handler: Any) -> str:
        if self._default_server is None:
            self._default_server = self.create_server()
        return self._default_server.route(path, handler)

    def run(self, host: str = "127.0.0.1", port: int = 8080) -> dict[str, Any]:
        if self._default_server is None:
            self._default_server = self.create_server(host=host, port=port)
        else:
            self._default_server.host = host
            self._default_server.port = int(port)
        return self._default_server.run()

    def stop(self) -> bool:
        if self._default_server is None:
            return False
        return self._default_server.stop()
