"""Content planner MCP server (resources-only) — JSON-RPC 2.0 over HTTP POST."""

import json

import pytest
from django.core.cache import cache
from django.urls import reverse

from content_planner.mcp import (
    PROTOCOL_VERSION,
    RESOURCES,
    SUPPORTED_PROTOCOL_VERSIONS,
    dispatch,
)

pytestmark = pytest.mark.django_db


def _jsonrpc(method, params=None, request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _post(client, payload):
    return client.post(
        reverse("content_mcp_endpoint"),
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------- transport + dispatcher ----------


def test_endpoint_returns_parse_error_for_invalid_json(client):
    resp = client.post(
        reverse("content_mcp_endpoint"),
        data="not json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == -32700


def test_endpoint_method_not_found(client):
    assert _post(client, _jsonrpc("nonsense/method")).json()["error"]["code"] == -32601


def test_endpoint_preserves_request_id(client):
    assert _post(client, _jsonrpc("initialize", request_id="abc")).json()["id"] == "abc"


def test_notification_returns_202_no_body(client):
    resp = client.post(
        reverse("content_mcp_endpoint"),
        data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        content_type="application/json",
    )
    assert resp.status_code == 202
    assert resp.content == b""


def test_dispatch_returns_none_for_notifications():
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_endpoint_accepts_post_without_trailing_slash(client):
    resp = client.post(
        "/mcp/content",
        data=json.dumps(_jsonrpc("initialize")),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_dispatch_internal_error_when_handler_raises(monkeypatch):
    monkeypatch.setitem(
        RESOURCES,
        "schema://content/create-from-chat",
        {"file": "does-not-exist.json", "name": "x", "description": "x", "mime": "x"},
    )
    resp = dispatch(
        _jsonrpc("resources/read", {"uri": "schema://content/create-from-chat"})
    )
    assert resp["error"]["code"] == -32603


# ---------- initialize ----------


def test_initialize_returns_protocol_and_server_info(client):
    result = _post(client, _jsonrpc("initialize")).json()["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "secretcodes-content-planner"
    assert "resources" in result["capabilities"]


@pytest.mark.parametrize("version", sorted(SUPPORTED_PROTOCOL_VERSIONS))
def test_initialize_echoes_supported_version(client, version):
    result = _post(client, _jsonrpc("initialize", {"protocolVersion": version})).json()[
        "result"
    ]
    assert result["protocolVersion"] == version


def test_initialize_falls_back_for_unknown_version(client):
    result = _post(
        client, _jsonrpc("initialize", {"protocolVersion": "1999-01-01"})
    ).json()["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION


# ---------- resources ----------


def test_resources_list_returns_all_uris(client):
    resources = _post(client, _jsonrpc("resources/list")).json()["result"]["resources"]
    uris = {r["uri"] for r in resources}
    assert uris == set(RESOURCES)
    assert all(r["mimeType"] and r["name"] for r in resources)


def test_resources_read_returns_schema_body(client):
    result = _post(
        client,
        _jsonrpc("resources/read", {"uri": "schema://content/create-from-chat"}),
    ).json()["result"]
    content = result["contents"][0]
    assert content["uri"] == "schema://content/create-from-chat"
    assert content["mimeType"] == "application/schema+json"
    assert "$schema" in content["text"]


def test_resources_read_example_is_valid_json(client):
    result = _post(
        client,
        _jsonrpc(
            "resources/read", {"uri": "example://content/event-anchored-campaign"}
        ),
    ).json()["result"]
    data = json.loads(result["contents"][0]["text"])
    assert data["campaign"]["name"]


def test_resources_read_unknown_uri(client):
    resp = _post(client, _jsonrpc("resources/read", {"uri": "schema://content/nope"}))
    assert resp.json()["error"]["code"] == -32602


def test_tools_list_is_empty(client):
    assert _post(client, _jsonrpc("tools/list")).json()["result"]["tools"] == []


def test_endpoint_rate_limits(client, settings):
    cache.clear()  # isolate from other tests' per-IP counts
    settings.MCP_RATE_LIMIT = "2/m"
    payload = _jsonrpc("tools/list")
    assert _post(client, payload).status_code == 200
    assert _post(client, payload).status_code == 200
    limited = _post(client, payload)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == -32000
