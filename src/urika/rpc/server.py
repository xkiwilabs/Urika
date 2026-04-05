"""Stdio JSON-RPC server for Urika compute backend."""
from __future__ import annotations

import sys

from urika.rpc.methods import build_registry
from urika.rpc.protocol import handle_request


def run_server() -> None:
    """Read JSON-RPC requests from stdin, write responses to stdout."""
    registry = build_registry()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = handle_request(line, registry)
        if response is not None:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()
