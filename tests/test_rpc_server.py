"""Tests for the stdio JSON-RPC server."""
import json
import subprocess
import sys


def test_server_responds_to_request():
    """Server reads JSON-RPC from stdin, writes response to stdout."""
    req = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools.list", "params": {},
    })
    proc = subprocess.run(
        [sys.executable, "-m", "urika.rpc"],
        input=req + "\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    resp = json.loads(proc.stdout.strip())
    assert "result" in resp
    assert isinstance(resp["result"], list)


def test_server_handles_multiple_requests():
    """Server processes multiple newline-delimited requests."""
    reqs = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools.list", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools.list", "params": {}}),
    ]) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "urika.rpc"],
        input=reqs,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = [ln for ln in proc.stdout.strip().split("\n") if ln]
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "result" in parsed


def test_server_handles_error_request():
    """Server returns error for unknown method."""
    req = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "nonexistent", "params": {},
    })
    proc = subprocess.run(
        [sys.executable, "-m", "urika.rpc"],
        input=req + "\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    resp = json.loads(proc.stdout.strip())
    assert "error" in resp
    assert resp["error"]["code"] == -32601
