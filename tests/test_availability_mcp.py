import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from django.urls import reverse

from availability.services.availability import BusyBlock
from availability.services.mcp import (
    PROTOCOL_VERSION,
    TOOLS,
    InvalidParams,
    ToolNotFound,
    _handle_tools_call,
    _tool_check_availability,
    dispatch,
)

UTC = timezone.utc


def _jsonrpc(method, params=None, request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _post(client, payload):
    return client.post(
        reverse("mcp_endpoint"),
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.fixture(autouse=True)
def _mock_fetch_busy_blocks():
    with patch(
        "availability.services.mcp.fetch_busy_blocks_for_all", return_value=[]
    ) as mock:
        yield mock


# ---------- transport + dispatcher ----------


@pytest.mark.django_db
def test_mcp_endpoint_returns_parse_error_for_invalid_json(client):
    response = client.post(
        reverse("mcp_endpoint"), data="not json", content_type="application/json"
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == -32700
    assert data["jsonrpc"] == "2.0"


@pytest.mark.django_db
def test_mcp_endpoint_returns_method_not_found_for_unknown_method(client):
    response = _post(client, _jsonrpc("nonsense/method"))
    data = response.json()
    assert data["error"]["code"] == -32601


@pytest.mark.django_db
def test_mcp_endpoint_preserves_request_id(client):
    response = _post(client, _jsonrpc("initialize", request_id="abc-123"))
    assert response.json()["id"] == "abc-123"


@pytest.mark.django_db
def test_mcp_dispatch_returns_internal_error_when_tool_raises():
    payload = _jsonrpc(
        "tools/call",
        {
            "name": "check_availability",
            "arguments": {"datetime": "2026-05-04T10:00:00+00:00"},
        },
    )
    with patch(
        "availability.services.mcp.classify_candidate",
        side_effect=RuntimeError("boom"),
    ):
        response = dispatch(payload)
    assert response["error"]["code"] == -32603
    assert "boom" in response["error"]["message"]


# ---------- initialize ----------


@pytest.mark.django_db
def test_initialize_returns_protocol_and_server_info(client):
    response = _post(client, _jsonrpc("initialize"))
    data = response.json()
    assert data["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert data["result"]["serverInfo"]["name"] == "secretcodes-availability"
    assert "tools" in data["result"]["capabilities"]


# ---------- tools/list ----------


@pytest.mark.django_db
def test_tools_list_returns_all_tools(client):
    response = _post(client, _jsonrpc("tools/list"))
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == set(TOOLS)


@pytest.mark.django_db
def test_tools_list_entries_have_input_schemas(client):
    response = _post(client, _jsonrpc("tools/list"))
    for tool in response.json()["result"]["tools"]:
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"
        assert tool["description"]


# ---------- tools/call ----------


@pytest.mark.django_db
def test_tools_call_rejects_unknown_tool(client):
    response = _post(
        client, _jsonrpc("tools/call", {"name": "unknown_tool", "arguments": {}})
    )
    data = response.json()
    assert data["error"]["code"] == -32602


@pytest.mark.django_db
def test_tools_call_rejects_invalid_datetime(client):
    response = _post(
        client,
        _jsonrpc(
            "tools/call",
            {"name": "check_availability", "arguments": {"datetime": "nonsense"}},
        ),
    )
    data = response.json()
    assert data["error"]["code"] == -32602


@pytest.mark.django_db
def test_tools_call_check_availability_free_in_business_hours(client):
    response = _post(
        client,
        _jsonrpc(
            "tools/call",
            {
                "name": "check_availability",
                "arguments": {
                    "datetime": datetime(2026, 5, 4, 17, 0, tzinfo=UTC).isoformat(),
                    "duration_minutes": 30,
                },
            },
        ),
    )
    content = response.json()["result"]["content"][0]
    assert content["type"] == "text"
    parsed = json.loads(content["text"])
    assert parsed["free"] is True
    assert parsed["band"] == "business"


@pytest.mark.django_db
def test_tools_call_check_availability_reports_busy(client, _mock_fetch_busy_blocks):
    candidate_start = datetime(2026, 5, 4, 17, 0, tzinfo=UTC)
    candidate_end = datetime(2026, 5, 4, 17, 30, tzinfo=UTC)
    _mock_fetch_busy_blocks.return_value = [BusyBlock(candidate_start, candidate_end)]

    response = _post(
        client,
        _jsonrpc(
            "tools/call",
            {
                "name": "check_availability",
                "arguments": {"datetime": candidate_start.isoformat()},
            },
        ),
    )
    parsed = json.loads(response.json()["result"]["content"][0]["text"])
    assert parsed["free"] is False
    assert parsed["reason"] == "Busy"


@pytest.mark.django_db
def test_tools_call_list_free_slots_returns_structured_slots(client):
    response = _post(
        client,
        _jsonrpc(
            "tools/call",
            {
                "name": "list_free_slots",
                "arguments": {
                    "start": datetime(2026, 5, 4, 0, tzinfo=UTC).isoformat(),
                    "end": datetime(2026, 5, 5, 0, tzinfo=UTC).isoformat(),
                    "duration_minutes": 60,
                },
            },
        ),
    )
    parsed = json.loads(response.json()["result"]["content"][0]["text"])
    assert parsed["business_slot_count"] == 8


@pytest.mark.django_db
def test_tools_call_list_free_slots_includes_extended_when_requested(client):
    response = _post(
        client,
        _jsonrpc(
            "tools/call",
            {
                "name": "list_free_slots",
                "arguments": {
                    "start": datetime(2026, 5, 4, 0, tzinfo=UTC).isoformat(),
                    "end": datetime(2026, 5, 5, 0, tzinfo=UTC).isoformat(),
                    "include_extended": True,
                },
            },
        ),
    )
    parsed = json.loads(response.json()["result"]["content"][0]["text"])
    assert any(slot["band"] == "extended" for slot in parsed["slots"])


@pytest.mark.django_db
def test_tools_call_get_busy_shadow_returns_blocks(client, _mock_fetch_busy_blocks):
    start = datetime(2026, 5, 4, 17, 0, tzinfo=UTC)
    end = datetime(2026, 5, 4, 18, 0, tzinfo=UTC)
    _mock_fetch_busy_blocks.return_value = [BusyBlock(start, end)]

    response = _post(
        client,
        _jsonrpc(
            "tools/call",
            {
                "name": "get_busy_shadow",
                "arguments": {
                    "start": datetime(2026, 5, 4, 0, tzinfo=UTC).isoformat(),
                    "end": datetime(2026, 5, 5, 0, tzinfo=UTC).isoformat(),
                },
            },
        ),
    )
    parsed = json.loads(response.json()["result"]["content"][0]["text"])
    assert len(parsed["busy_blocks"]) == 1
    assert parsed["busy_blocks"][0]["start"] == start.isoformat()


@pytest.mark.django_db
def test_tools_call_get_booking_info_returns_stub(client):
    response = _post(
        client,
        _jsonrpc("tools/call", {"name": "get_booking_info", "arguments": {}}),
    )
    parsed = json.loads(response.json()["result"]["content"][0]["text"])
    assert parsed["available"] is False
    assert "booking" in parsed["message"].lower()


# ---------- direct unit tests for internal helpers ----------


def test_handle_tools_call_raises_for_unknown_tool():
    with pytest.raises(ToolNotFound):
        _handle_tools_call({"name": "nope", "arguments": {}})


def test_invalid_params_raised_for_missing_datetime():
    with pytest.raises(InvalidParams):
        _tool_check_availability({})
