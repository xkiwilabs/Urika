"""Tests for JSON-RPC 2.0 protocol handler."""
import json
from urika.rpc.protocol import handle_request, RPCError


def test_valid_request_dispatches():
    """A valid JSON-RPC request dispatches to the registered method."""
    registry = {"echo": lambda params: params["msg"]}
    req = {"jsonrpc": "2.0", "id": 1, "method": "echo", "params": {"msg": "hello"}}
    resp = handle_request(json.dumps(req), registry)
    parsed = json.loads(resp)
    assert parsed["result"] == "hello"
    assert parsed["id"] == 1


def test_method_not_found():
    """Unknown method returns -32601 error."""
    registry = {}
    req = {"jsonrpc": "2.0", "id": 1, "method": "nope", "params": {}}
    resp = handle_request(json.dumps(req), registry)
    parsed = json.loads(resp)
    assert parsed["error"]["code"] == -32601


def test_invalid_json():
    """Malformed JSON returns -32700 parse error."""
    resp = handle_request("not json{", {})
    parsed = json.loads(resp)
    assert parsed["error"]["code"] == -32700


def test_method_exception_returns_error():
    """If the handler raises, return -32000 internal error."""
    def bad(params):
        raise ValueError("boom")
    registry = {"bad": bad}
    req = {"jsonrpc": "2.0", "id": 1, "method": "bad", "params": {}}
    resp = handle_request(json.dumps(req), registry)
    parsed = json.loads(resp)
    assert parsed["error"]["code"] == -32000
    assert "boom" in parsed["error"]["message"]


def test_notification_no_response():
    """A request without 'id' is a notification -- no response."""
    registry = {"noop": lambda params: None}
    req = {"jsonrpc": "2.0", "method": "noop", "params": {}}
    resp = handle_request(json.dumps(req), registry)
    assert resp is None


def test_rpc_error_attributes():
    """RPCError carries code and message."""
    err = RPCError(-32600, "Invalid Request")
    assert err.code == -32600
    assert err.message == "Invalid Request"
    assert str(err) == "Invalid Request"
