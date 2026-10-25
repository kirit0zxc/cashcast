"""Закрытый HTTP-адаптер неизменного пакета; содержимое запросов не журналируется."""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/model")
from predict import FrozenRisk

runtime = FrozenRisk("/model")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Банковские данные и тела запросов не попадают в access log.

    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond(200 if self.path == "/healthz" else 404,
                     {"model_version": runtime.config["version"], "ready": self.path == "/healthz"})

    def do_POST(self):
        if self.path != "/predict":
            self.respond(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError("invalid_size")
            self.connection.settimeout(5)
            result = runtime.predict(json.loads(self.rfile.read(size)))
        except (ValueError, TypeError, KeyError, OSError):
            self.respond(422, {"error": "unsupported_input"})
            return
        self.respond(200, result)


HTTPServer(("0.0.0.0", 8765), Handler).serve_forever()  # noqa: S104 — только внутренняя Docker-сеть.
