"""MCP server (JSON-RPC 2.0 over HTTP POST) for the content_planner format.

Resources-only and read-only: serves the create-from-chat schema, the
conventions doc, and worked examples as MCP resources, so an AI tool added as a
connector can read the JSON shape itself instead of guessing — no private board
data, so no auth.

Hand-rolled to mirror ``availability.services.mcp``: this is a sync WSGI app and
the async MCP SDK's remote transport doesn't fit it, so a small JSON-RPC adapter
in a plain Django view is the pragmatic, proven choice (it's how the
availability connector already runs).
"""

from .schemas import SCHEMA_DIR

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})
SERVER_INFO = {"name": "secretcodes-content-planner", "version": "1.0.0"}


class ResourceNotFound(Exception):
    """Raised when resources/read references an unknown URI."""


RESOURCES = {
    "schema://content/create-from-chat": {
        "file": "create_from_chat.schema.json",
        "name": "Create-from-chat JSON Schema",
        "description": (
            "JSON Schema for the campaign import (create-from-chat) format."
        ),
        "mime": "application/schema+json",
    },
    "schema://content/export": {
        "file": "export.schema.json",
        "name": "Campaign export JSON Schema",
        "description": (
            "JSON Schema for the campaign export format (superset of "
            "create-from-chat)."
        ),
        "mime": "application/schema+json",
    },
    "docs://content/conventions": {
        "file": "conventions.md",
        "name": "Content planner JSON conventions",
        "description": (
            "How to produce a campaign JSON: channels, scheduling, hashtags, "
            "and which fields are ignored on import."
        ),
        "mime": "text/markdown",
    },
    "example://content/event-anchored-campaign": {
        "file": "examples/event-anchored-campaign.json",
        "name": "Example: event-anchored campaign",
        "description": (
            "A complete, valid create-from-chat payload anchored to an event " "date."
        ),
        "mime": "application/json",
    },
    "example://content/blog-and-social-series": {
        "file": "examples/blog-and-social-series.json",
        "name": "Example: blog + social series",
        "description": (
            "A complete, valid create-from-chat payload with absolute " "scheduling."
        ),
        "mime": "application/json",
    },
}


def _resource_descriptor(uri):
    res = RESOURCES[uri]
    return {
        "uri": uri,
        "name": res["name"],
        "description": res["description"],
        "mimeType": res["mime"],
    }


def _handle_initialize(params):
    requested = params.get("protocolVersion")
    negotiated = (
        requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
    )
    return {
        "protocolVersion": negotiated,
        "capabilities": {"resources": {}},
        "serverInfo": SERVER_INFO,
    }


def _handle_resources_list(params):
    return {"resources": [_resource_descriptor(uri) for uri in RESOURCES]}


def _handle_resources_read(params):
    uri = params.get("uri")
    if uri not in RESOURCES:
        raise ResourceNotFound(f"Unknown resource: {uri!r}")
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": RESOURCES[uri]["mime"],
                "text": (SCHEMA_DIR / RESOURCES[uri]["file"]).read_text(),
            }
        ]
    }


def _handle_tools_list(params):
    return {"tools": []}


METHODS = {
    "initialize": _handle_initialize,
    "resources/list": _handle_resources_list,
    "resources/read": _handle_resources_read,
    "tools/list": _handle_tools_list,
}


def _error(code, message, request_id):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def dispatch(payload):
    """Return the JSON-RPC 2.0 response dict, or ``None`` for notifications.

    A payload without an ``id`` is a notification — per the spec the server
    sends no response, so the caller returns HTTP 202 with an empty body.
    """
    if "id" not in payload:
        return None

    request_id = payload.get("id")
    method = payload.get("method")

    if method not in METHODS:
        return _error(-32601, f"Method not found: {method!r}", request_id)

    try:
        result = METHODS[method](payload.get("params") or {})
    except ResourceNotFound as exc:
        return _error(-32602, str(exc), request_id)
    except Exception as exc:
        return _error(-32603, f"Internal error: {exc}", request_id)

    return {"jsonrpc": "2.0", "id": request_id, "result": result}
