"""JSON-RPC 2.0 protocol handler."""
from __future__ import annotations

import json
from typing import Any, Callable

Registry = dict[str, Callable[[dict[str, Any]], Any]]


class RPCError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def handle_request(raw: str, registry: Registry) -> str | None:
    """Parse a JSON-RPC 2.0 request, dispatch to registry, return response."""
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        return _error_response(None, -32700, f"Parse error: {e}")

    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    if method not in registry:
        if req_id is None:
            return None
        return _error_response(req_id, -32601, f"Method not found: {method}")

    try:
        result = registry[method](params)
    except Exception as e:
        if req_id is None:
            return None
        return _error_response(req_id, -32000, str(e))

    if req_id is None:
        return None
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error_response(req_id: int | None, code: int, message: str) -> str:
    """Build a JSON-RPC 2.0 error response."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })
