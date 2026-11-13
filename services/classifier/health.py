"""Small readiness endpoint for the classifier worker, including startup failure."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


def make_health_server(service, host="0.0.0.0", port=8002):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            state = service.health()
            body = json.dumps(state).encode()
            self.send_response(200 if state["status"] == "ok" else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)
