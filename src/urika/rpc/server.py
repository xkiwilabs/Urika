"""Stdio JSON-RPC server for Urika compute backend."""
from __future__ import annotations

import sys
from typing import Any

from urika.rpc.methods import build_registry
from urika.rpc.protocol import build_notification, handle_request


def run_server() -> None:
    """Read JSON-RPC requests from stdin, write responses to stdout.

    Handlers that accept a `notify` kwarg can emit progress notifications
    mid-execution. These are written as JSON-RPC notifications (no id).
    """
    registry = build_registry()

    def notify(method: str, params: dict[str, Any]) -> None:
        """Write a progress notification to stdout."""
        sys.stdout.write(build_notification(method, params) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = handle_request(line, registry, notify=notify)
        if response is not None:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()
