"""MCP (Model Context Protocol) server over JSON-RPC 2.0 via HTTP POST.

Exposes read-only availability tools for AI agents. Same pure compute that
powers the public web views — no new business logic, just a different
transport.
"""

import json
from datetime import timedelta

from django.utils.dateparse import parse_datetime

from availability.models import AvailabilityProfile

from .availability import classify_candidate, compute_availability
from .google import fetch_busy_blocks_for_all, has_active_calendars

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "secretcodes-availability", "version": "1.0.0"}
NO_CALENDARS_REASON = "No calendars connected"


class InvalidParams(Exception):
    """Raised by a tool handler when its arguments are malformed."""


class ToolNotFound(Exception):
    """Raised when tools/call references an unknown tool name."""


def _parse_dt(value):
    """Parse an ISO-8601 datetime string or raise InvalidParams."""
    parsed = parse_datetime(value) if value else None
    if parsed is None:
        raise InvalidParams(f"Invalid or missing datetime: {value!r}")
    return parsed


def _tool_check_availability(arguments):
    dt = _parse_dt(arguments.get("datetime"))
    duration = int(arguments.get("duration_minutes", 30))
    end = dt + timedelta(minutes=duration)
    if not has_active_calendars():
        return {
            "connected": False,
            "free": None,
            "band": None,
            "reason": NO_CALENDARS_REASON,
        }
    profile = AvailabilityProfile.get_solo()
    busy = fetch_busy_blocks_for_all(dt, end)
    free, band, reason = classify_candidate(
        profile,
        dt,
        end,
        busy,
        buffer=timedelta(minutes=profile.meeting_buffer_minutes),
    )
    return {"connected": True, "free": free, "band": band, "reason": reason}


def _tool_list_free_slots(arguments):
    start = _parse_dt(arguments.get("start"))
    end = _parse_dt(arguments.get("end"))
    duration = int(arguments.get("duration_minutes", 30))
    include_extended = bool(arguments.get("include_extended", False))
    if not has_active_calendars():
        return {"connected": False, "slots": [], "business_slot_count": 0}
    profile = AvailabilityProfile.get_solo()
    busy = fetch_busy_blocks_for_all(start, end)
    result = compute_availability(
        start,
        end,
        busy,
        profile,
        duration=timedelta(minutes=duration),
        include_extended=include_extended,
        buffer=timedelta(minutes=profile.meeting_buffer_minutes),
    )
    return {
        "connected": True,
        "slots": [
            {
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "band": slot.band,
            }
            for slot in result.free_slots
        ],
        "business_slot_count": result.business_slot_count,
    }


def _tool_get_busy_shadow(arguments):
    start = _parse_dt(arguments.get("start"))
    end = _parse_dt(arguments.get("end"))
    if not has_active_calendars():
        return {"connected": False, "busy_blocks": []}
    busy = fetch_busy_blocks_for_all(start, end)
    return {
        "connected": True,
        "busy_blocks": [
            {"start": block.start.isoformat(), "end": block.end.isoformat()}
            for block in busy
        ],
    }


def _tool_get_booking_info(arguments):
    return {
        "available": False,
        "message": (
            "Paid booking is not yet available. For now, contact Mariatta "
            "directly at mariatta@mariatta.ca."
        ),
    }


TOOLS = {
    "check_availability": {
        "handler": _tool_check_availability,
        "description": (
            "Check whether a specific time window is free on Mariatta's "
            "calendar. Returns whether it is free, the band "
            "(business/extended), and a reason if not free."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "datetime": {
                    "type": "string",
                    "format": "date-time",
                    "description": "ISO 8601 start datetime with timezone.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "default": 30,
                    "minimum": 1,
                    "description": "Meeting length in minutes.",
                },
            },
            "required": ["datetime"],
        },
    },
    "list_free_slots": {
        "handler": _tool_list_free_slots,
        "description": (
            "Return free time slots in a date range. Default duration is "
            "30 minutes, business hours only. Set include_extended=true "
            "to also return early-morning and evening extended-hour slots."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
                "duration_minutes": {
                    "type": "integer",
                    "default": 30,
                    "minimum": 1,
                },
                "include_extended": {"type": "boolean", "default": False},
            },
            "required": ["start", "end"],
        },
    },
    "get_busy_shadow": {
        "handler": _tool_get_busy_shadow,
        "description": (
            "Return the busy time ranges from Mariatta's connected Google "
            "Calendars in a date range. Only start/end timestamps — never "
            "event titles, attendees, or descriptions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
            },
            "required": ["start", "end"],
        },
    },
    "get_booking_info": {
        "handler": _tool_get_booking_info,
        "description": (
            "Return paid-booking availability info. Currently a stub — "
            "returns available=false until the Stripe booking layer lands."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
}


def _tool_definition(name):
    tool = TOOLS[name]
    return {
        "name": name,
        "description": tool["description"],
        "inputSchema": tool["input_schema"],
    }


def get_server_descriptor(endpoint_url, documentation_url):
    """Static metadata for machine discovery (served at /.well-known/mcp.json).

    Bundles server identity, transport info, and the full tool catalog in a
    single GET-able document so agent frameworks can sniff capabilities
    without an MCP handshake.
    """
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "protocolVersion": PROTOCOL_VERSION,
        "endpoint": endpoint_url,
        "documentation": documentation_url,
        "transport": "http",
        "authentication": "none",
        "tools": [_tool_definition(name) for name in TOOLS],
    }


def _handle_initialize(params):
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    }


def _handle_tools_list(params):
    return {"tools": [_tool_definition(name) for name in TOOLS]}


def _handle_tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name not in TOOLS:
        raise ToolNotFound(f"Unknown tool: {name!r}")
    result = TOOLS[name]["handler"](arguments)
    return {
        "content": [{"type": "text", "text": json.dumps(result, default=str)}],
    }


METHODS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def _error(code, message, request_id):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def dispatch(payload):
    """Return the JSON-RPC 2.0 response dict for a parsed request payload."""
    request_id = payload.get("id")
    method = payload.get("method")

    if method not in METHODS:
        return _error(-32601, f"Method not found: {method!r}", request_id)

    try:
        result = METHODS[method](payload.get("params") or {})
    except (InvalidParams, ToolNotFound) as exc:
        return _error(-32602, str(exc), request_id)
    except Exception as exc:
        return _error(-32603, f"Internal error: {exc}", request_id)

    return {"jsonrpc": "2.0", "id": request_id, "result": result}
