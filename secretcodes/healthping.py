"""A minimal HTTP 200 responder for the non-web container roles.

App Service pings a Linux container's port on startup and restarts it if
nothing answers, which would crash-loop a Celery worker or beat process (they
bind no port). This serves a trivial ``ok`` on ``$PORT`` alongside them so the
platform's probe passes.

It is deliberately not a real health check: it says nothing about whether the
worker is consuming tasks, only that the container is up. It also serves the
same 200 for every path so it never exposes anything, since App Service gives
even a no-ingress app a public hostname.

Run as a standalone script (``python /code/secretcodes/healthping.py``) so it
stays pure stdlib and does not import Django or Celery.
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class _OK(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        """Silence the default per-request stderr logging."""


def serve(port=None):
    port = port or int(os.environ.get("PORT", "8000"))
    HTTPServer(("0.0.0.0", port), _OK).serve_forever()


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    serve()
