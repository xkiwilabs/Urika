"""Tests for PauseController and KeyListener."""

from __future__ import annotations

import sys
import threading
from unittest.mock import patch

from urika.orchestrator.pause import KeyListener, PauseController


class TestPauseController:
    def test_initial_state(self) -> None:
        pc = PauseController()
        assert pc.is_pause_requested() is False
        assert pc.is_stop_requested() is False

    def test_request_pause(self) -> None:
        pc = PauseController()
        pc.request_pause()
        assert pc.is_pause_requested() is True

    def test_request_stop(self) -> None:
        pc = PauseController()
        pc.request_stop()
        assert pc.is_stop_requested() is True

    def test_pause_and_stop_independent(self) -> None:
        pc = PauseController()
        pc.request_pause()
        assert pc.is_pause_requested() is True
        assert pc.is_stop_requested() is False

        pc2 = PauseController()
        pc2.request_stop()
        assert pc2.is_stop_requested() is True
        assert pc2.is_pause_requested() is False

    def test_reset_clears_both(self) -> None:
        pc = PauseController()
        pc.request_pause()
        pc.request_stop()
        assert pc.is_pause_requested() is True
        assert pc.is_stop_requested() is True

        pc.reset()
        assert pc.is_pause_requested() is False
        assert pc.is_stop_requested() is False

    def test_thread_safe(self) -> None:
        pc = PauseController()
        result = threading.Event()

        def set_pause() -> None:
            pc.request_pause()
            result.set()

        t = threading.Thread(target=set_pause)
        t.start()
        result.wait(timeout=2.0)
        t.join(timeout=2.0)

        assert pc.is_pause_requested() is True


class TestKeyListener:
    def test_noop_when_not_tty(self) -> None:
        pc = PauseController()
        listener = KeyListener(pc)

        with patch.object(sys, "stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            listener.start()

        # No thread should have been created
        assert listener._thread is None

    def test_stop_without_start(self) -> None:
        pc = PauseController()
        listener = KeyListener(pc)
        # Should not raise
        listener.stop()
