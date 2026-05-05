"""Tests for v0.4.2 H3 — SSE generators honor request.is_disconnected.

Pre-fix the 5 SSE endpoints (run/finalize/summarize/build_tool/advisor
streams) polled disk every 0.5s without checking whether the browser
had disconnected. Closing the tab left the generator running until
the lockfile naturally disappeared — wasted CPU and a coroutine slot
leak under heavy use.

These tests check that each route's signature accepts a ``Request``
parameter (the FastAPI hook that exposes ``is_disconnected()``).
Drive-test of the actual disconnect behavior is hard via the
TestClient (it doesn't simulate mid-stream disconnect cleanly), so
we verify the contract — having the parameter on the signature is
the deterministic part of the fix.
"""

from __future__ import annotations

import inspect

import urika.dashboard.routers.api as api


class TestSseRoutesAcceptRequestParam:
    def _has_request_param(self, fn) -> bool:
        # ``api.py`` uses ``from __future__ import annotations`` so
        # parameter annotations are strings until ``get_type_hints``
        # resolves them. Match by name + annotation string — both
        # forms cover the contract.
        sig = inspect.signature(fn)
        for name, p in sig.parameters.items():
            if name == "request":
                return True
            ann = p.annotation
            if isinstance(ann, str) and ann.endswith("Request"):
                return True
        return False

    def test_run_stream_takes_request(self) -> None:
        assert self._has_request_param(api.api_run_stream), (
            "Pre-v0.4.2 ``api_run_stream`` didn't even take a Request "
            "param, so disconnect detection was structurally impossible."
        )

    def test_finalize_stream_takes_request(self) -> None:
        assert self._has_request_param(api.api_finalize_stream)

    def test_summarize_stream_takes_request(self) -> None:
        assert self._has_request_param(api.api_summarize_stream)

    def test_build_tool_stream_takes_request(self) -> None:
        assert self._has_request_param(api.api_build_tool_stream)

    def test_advisor_stream_takes_request(self) -> None:
        assert self._has_request_param(api.api_advisor_stream)


class TestSseSourceCallsIsDisconnected:
    """Cheap source-level check: each generator body must reference
    ``is_disconnected``. If a future edit drops the call we want to
    notice without standing up an end-to-end disconnect simulation.
    """

    def _fn_source_calls_disconnect(self, fn) -> bool:
        try:
            src = inspect.getsource(fn)
        except OSError:
            return False
        return "is_disconnected" in src

    def test_run_stream_polls_disconnect(self) -> None:
        assert self._fn_source_calls_disconnect(api.api_run_stream)

    def test_finalize_stream_polls_disconnect(self) -> None:
        assert self._fn_source_calls_disconnect(api.api_finalize_stream)

    def test_summarize_stream_polls_disconnect(self) -> None:
        assert self._fn_source_calls_disconnect(api.api_summarize_stream)

    def test_build_tool_stream_polls_disconnect(self) -> None:
        assert self._fn_source_calls_disconnect(api.api_build_tool_stream)

    def test_advisor_stream_polls_disconnect(self) -> None:
        assert self._fn_source_calls_disconnect(api.api_advisor_stream)
