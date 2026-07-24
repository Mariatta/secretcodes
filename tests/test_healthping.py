"""The startup-probe responder used by the worker/beat container roles."""

import socket
import threading
from http.client import HTTPConnection

from secretcodes import healthping


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_responds_200_ok_on_any_path():
    port = _free_port()
    server = healthping.HTTPServer(("127.0.0.1", port), healthping._OK)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        for path in ("/", "/anything", "/robots.txt"):
            conn = HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", path)
            response = conn.getresponse()
            assert response.status == 200
            assert response.read() == b"ok"
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_serve_reads_the_port_from_env_and_starts_the_server(monkeypatch):
    """`serve()` blocks on serve_forever, so stub the server to observe it."""
    seen = {}

    class FakeServer:
        def __init__(self, address, handler):
            seen["address"] = address

        def serve_forever(self):
            seen["served"] = True

    monkeypatch.setattr(healthping, "HTTPServer", FakeServer)
    monkeypatch.setenv("PORT", "8123")
    healthping.serve()
    assert seen["address"] == ("0.0.0.0", 8123)
    assert seen["served"] is True
