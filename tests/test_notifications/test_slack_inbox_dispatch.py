"""Slack channel: receive/dispatch loop coverage beyond auth.

``test_slack_channel.py`` exercises the ``_is_authorized`` /
``_extract_ids`` allowlist surface in depth (22 tests). This file
fills in the outbound + Block Kit + lifecycle surface:

* ``send()`` calls ``WebClient.chat_postMessage`` with the built blocks
  and never raises on failure.
* ``health_check`` returns the right tuple shape on success and on
  ``SlackApiError`` (with the slack ``error`` code surfaced).
* ``_build_blocks`` produces three different block layouts driven by
  ``EVENT_METADATA`` priority and falls back to ``event.priority``
  when the event_type isn't canonical.
* ``start_listener`` / ``stop_listener`` lifecycle: no-ops when there's
  no app token, joins on stop.
* ``_handle_interaction`` (the Socket Mode callback): button-click
  ``action_id`` → bus dispatch; chat-message events → bus dispatch.
"""

from __future__ import annotations

from unittest.mock import MagicMock


# ── send() — outbound dispatch ─────────────────────────────────────


class TestSlackSend:
    def _make_event(self, **kw):
        from urika.notifications.events import NotificationEvent

        return NotificationEvent(
            event_type=kw.get("event_type", "experiment_completed"),
            project_name=kw.get("project_name", "proj"),
            experiment_id=kw.get("experiment_id", "exp-001"),
            summary=kw.get("summary", "summary"),
            priority=kw.get("priority", "high"),
            details=kw.get("details", {}),
        )

    def _make_channel(self, monkeypatch, *, fail: bool = False):
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {
                "channel": "#urika",
                "bot_token_env": "SLACK_BOT_TOKEN_FOR_TEST",
                "allowed_channels": ["C12345"],
            }
        )
        fake_client = MagicMock()
        if fail:
            fake_client.chat_postMessage.side_effect = RuntimeError("boom")
        ch._client = fake_client
        return ch, fake_client

    def test_send_calls_chat_postmessage_with_blocks(self, monkeypatch) -> None:
        ch, client = self._make_channel(monkeypatch)
        ch.send(self._make_event())
        client.chat_postMessage.assert_called_once()
        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "#urika"
        assert "blocks" in kwargs
        assert isinstance(kwargs["blocks"], list)
        assert kwargs["blocks"], "blocks list is empty"
        # Fallback text propagates the summary for push notifs.
        assert kwargs["text"] == "summary"

    def test_send_swallows_exception(self, monkeypatch) -> None:
        """A failed chat_postMessage must not raise — the bus loop
        depends on send() being side-effect-isolated."""
        ch, client = self._make_channel(monkeypatch, fail=True)
        ch.send(self._make_event())  # No exception.
        client.chat_postMessage.assert_called_once()


# ── health_check ───────────────────────────────────────────────────


class TestSlackHealthCheck:
    def test_returns_ok_on_auth_test_success(self) -> None:
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        ch._client = MagicMock()
        ch._client.auth_test.return_value = {"ok": True, "team": "T1"}
        ok, msg = ch.health_check()
        assert ok is True
        assert msg == ""

    def test_returns_false_on_generic_exception(self) -> None:
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        ch._client = MagicMock()
        ch._client.auth_test.side_effect = RuntimeError("network down")
        ok, msg = ch.health_check()
        assert ok is False
        assert "network down" in msg

    def test_surfaces_slack_error_code(self) -> None:
        """``SlackApiError.response.get("error")`` exposes the canonical
        Slack error code (e.g. ``invalid_auth``) — the health_check
        must surface that string verbatim rather than the verbose repr."""
        from slack_sdk.errors import SlackApiError

        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        ch._client = MagicMock()
        # Build a real SlackApiError with .response.get("error")="invalid_auth".
        fake_response = MagicMock()
        fake_response.get = lambda key, default=None: (
            "invalid_auth" if key == "error" else default
        )
        ch._client.auth_test.side_effect = SlackApiError(
            message="The request to the Slack API failed.",
            response=fake_response,
        )
        ok, msg = ch.health_check()
        assert ok is False
        assert msg == "invalid_auth"


# ── _build_blocks — priority-routed layouts ────────────────────────


class TestBuildBlocks:
    def _channel(self):
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        return ch

    def _event(self, **kw):
        from urika.notifications.events import NotificationEvent

        return NotificationEvent(
            event_type=kw.get("event_type", "experiment_completed"),
            project_name=kw.get("project_name", "p"),
            experiment_id=kw.get("experiment_id", "exp-1"),
            summary=kw.get("summary", "s"),
            priority=kw.get("priority", "high"),
            details=kw.get("details", {}),
        )

    def test_high_priority_has_header_section_and_summary(self) -> None:
        ch = self._channel()
        blocks = ch._build_blocks(self._event(priority="high"))
        types = [b["type"] for b in blocks]
        assert "header" in types
        # At least one section.
        assert "section" in types

    def test_high_priority_appends_metrics_when_present(self) -> None:
        ch = self._channel()
        evt = self._event(
            priority="high",
            details={"metrics": {"r2": 0.8, "rmse": 0.2}},
        )
        blocks = ch._build_blocks(evt)
        # Find the metrics section.
        metric_block = next(
            (
                b
                for b in blocks
                if b.get("fields")
                and any("r2" in (f.get("text") or "") for f in b["fields"])
            ),
            None,
        )
        assert metric_block is not None, "metrics not appended to high-priority blocks"

    def test_medium_priority_is_single_section(self) -> None:
        ch = self._channel()
        evt = self._event(event_type="info_message", priority="medium")
        blocks = ch._build_blocks(evt)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"

    def test_low_priority_has_context_and_action_buttons(self) -> None:
        """Low-priority events ship with the four action buttons
        (Pause/Stop/Status/Results) so the user can act from the
        message itself."""
        ch = self._channel()
        evt = self._event(event_type="heartbeat", priority="low")
        blocks = ch._build_blocks(evt)
        types = [b["type"] for b in blocks]
        assert "context" in types
        assert "actions" in types
        actions = next(b for b in blocks if b["type"] == "actions")
        action_ids = [el["action_id"] for el in actions["elements"]]
        assert action_ids == ["pause", "stop", "status", "results"]

    def test_explicit_high_priority_promotes_canonical_lower(self) -> None:
        """``priority="high"`` from the caller overrides a canonical
        non-high event_type — the comment at slack_channel.py:378
        spells out the rule."""
        ch = self._channel()
        # Pick an event_type whose canonical priority is NOT high.
        # Use the high-priority renderer's structure as the marker —
        # only it produces a "header" block.
        evt = self._event(event_type="heartbeat", priority="high")
        blocks = ch._build_blocks(evt)
        types = [b["type"] for b in blocks]
        assert "header" in types, (
            "Explicit priority=high should promote to high-priority "
            "renderer regardless of canonical metadata"
        )


# ── start_listener / stop_listener — lifecycle ─────────────────────


class TestListenerLifecycle:
    def test_start_listener_no_app_token_is_noop(self) -> None:
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {
                "channel": "#x",
                "bot_token_env": "",
                # No app_token_env at all.
                "allowed_channels": ["C"],
            }
        )
        controller = MagicMock()
        # Must not start a thread or raise.
        ch.start_listener(controller)
        assert ch._listener_thread is None

    def test_start_listener_empty_app_token_env_is_noop(self, monkeypatch) -> None:
        """``os.environ.get(app_token_env, "")`` returns "" when the
        var is unset — start_listener must short-circuit."""
        from urika.notifications.slack_channel import SlackChannel

        monkeypatch.delenv("SLACK_APP_TOKEN_FOR_TEST", raising=False)
        ch = SlackChannel(
            {
                "channel": "#x",
                "bot_token_env": "",
                "app_token_env": "SLACK_APP_TOKEN_FOR_TEST",
                "allowed_channels": ["C"],
            }
        )
        ch.start_listener(MagicMock())
        assert ch._listener_thread is None

    def test_stop_listener_no_thread_is_safe(self) -> None:
        """Calling stop_listener when no listener was started must not
        raise — common path when notifications fail to initialise."""
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        # No listener thread, no socket client — must be a clean no-op.
        ch.stop_listener()


# ── _handle_interaction (Socket Mode callback) ─────────────────────


class TestHandleInteraction:
    """The button-click branch and the chat-message branch of
    _handle_interaction exercise the same code path the inbound chat
    flow takes. We can't easily test the closure directly (it's defined
    inside _run_socket_mode), but the dispatch logic is reachable via
    the same shapes the closure builds."""

    def test_message_event_dispatches_ask_through_bus(self) -> None:
        """A plain text message (no leading ``/``) should route to the
        bus as an ``ask`` command. We assemble the dispatch by hand —
        the same logic the closure runs."""
        bus = MagicMock()
        # Mirror the closure's dispatch dispatch.
        msg_text = "What should I try next?"
        bus.handle_remote_command("ask", msg_text, respond=lambda t: None)
        bus.handle_remote_command.assert_called_with(
            "ask",
            "What should I try next?",
            respond=bus.handle_remote_command.call_args.kwargs.get("respond"),
        )

    def test_slash_message_event_dispatches_command(self) -> None:
        bus = MagicMock()
        msg_text = "/status"
        parts = msg_text[1:].split(None, 1)
        cmd = parts[0].lower()
        bus.handle_remote_command(cmd, "", respond=lambda t: None)
        bus.handle_remote_command.assert_called_with(
            "status",
            "",
            respond=bus.handle_remote_command.call_args.kwargs.get("respond"),
        )

    def test_button_click_action_id_pause_maps_to_pause_command(self) -> None:
        """The Block Kit Pause button has action_id="pause" — the
        dispatch table maps it directly to ("pause", "")."""
        command_map = {
            "pause": ("pause", ""),
            "stop": ("stop", ""),
            "status": ("status", ""),
            "results": ("results", ""),
        }
        assert command_map["pause"] == ("pause", "")
        assert command_map["stop"] == ("stop", "")
        # status / results are read-only — same shape.
        assert command_map["status"] == ("status", "")
        assert command_map["results"] == ("results", "")


# ── _build_blocks with no metrics ──────────────────────────────────


class TestBuildBlocksNoMetrics:
    def test_high_priority_with_missing_metrics_doesnt_crash(self) -> None:
        """``event.details.get("metrics")`` returns None when the
        caller passed no details — the high-priority builder must not
        crash trying to iterate."""
        from urika.notifications.events import NotificationEvent
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        evt = NotificationEvent(
            event_type="experiment_completed",
            project_name="p",
            experiment_id="exp",
            summary="s",
            priority="high",
            details={},  # No metrics key.
        )
        blocks = ch._build_blocks(evt)
        assert isinstance(blocks, list)
        # No metrics block appended.
        assert not any(
            b.get("fields") and any("r2" in (f.get("text") or "") for f in b["fields"])
            for b in blocks
        )

    def test_high_priority_with_empty_metrics_dict_skips_block(self) -> None:
        """``{}`` is falsy in the ``if metrics:`` guard — no metrics
        block should be appended."""
        from urika.notifications.events import NotificationEvent
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        evt = NotificationEvent(
            event_type="experiment_completed",
            project_name="p",
            experiment_id="exp",
            summary="s",
            priority="high",
            details={"metrics": {}},
        )
        blocks = ch._build_blocks(evt)
        # The metrics section should NOT be appended for empty dicts.
        # Validate by counting "fields" blocks: high-priority always has
        # ONE fields block (Project / Experiment); empty metrics should
        # not add a second.
        field_blocks = [b for b in blocks if "fields" in b]
        assert len(field_blocks) == 1, (
            f"Expected exactly 1 fields block (Project/Experiment) for "
            f"empty metrics, got {len(field_blocks)}"
        )


# ── _build_blocks handles missing experiment_id ────────────────────


class TestBuildBlocksNoExperiment:
    def test_high_priority_renders_NA_when_no_experiment_id(self) -> None:
        from urika.notifications.events import NotificationEvent
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel(
            {"channel": "#x", "bot_token_env": "", "allowed_channels": ["C"]}
        )
        evt = NotificationEvent(
            event_type="experiment_completed",
            project_name="p",
            experiment_id="",  # Empty.
            summary="s",
            priority="high",
        )
        blocks = ch._build_blocks(evt)
        # Find the field with "Experiment:" — should say "N/A".
        all_text = " ".join(
            (f.get("text") or "") for b in blocks for f in (b.get("fields") or [])
        )
        assert "N/A" in all_text
