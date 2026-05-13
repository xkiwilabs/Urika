"""Telegram channel: bot inbox + /run dispatch coverage.

The existing ``test_telegram_channel.py`` only covers the formatter
routing (high vs default). This file extends to the inbound side and
the bot-API surface:

* Init reads token from env var (``bot_token_env`` → ``os.environ[...]``).
* ``send()`` formats + builds keyboard + threads the bot.send_message
  call; swallows exceptions so a downed bus dispatch isn't fatal.
* ``health_check`` runs ``bot.get_me()`` in a fresh loop, classifies
  the result.
* ``_handle_command`` / ``_handle_callback`` / ``_handle_free_text`` —
  the routing surface that turns an inbound Telegram message into a
  bus ``handle_remote_command`` call (with the chat-id gate).
* ``_build_keyboard`` is None for non-experiment-started events.
* ``_esc`` HTML escaping.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ── Init / token resolution ────────────────────────────────────────


class TestTelegramChannelInit:
    def test_reads_token_from_env_var(self, monkeypatch) -> None:
        from urika.notifications.telegram_channel import TelegramChannel

        monkeypatch.setenv("TG_TOKEN_FOR_TEST", "secret-token-12345")
        ch = TelegramChannel({"chat_id": "111", "bot_token_env": "TG_TOKEN_FOR_TEST"})
        assert ch._token == "secret-token-12345"
        assert ch._chat_id == "111"

    def test_no_token_when_env_var_missing(self) -> None:
        from urika.notifications.telegram_channel import TelegramChannel

        ch = TelegramChannel({"chat_id": "x", "bot_token_env": "UNSET_VAR_FOR_TEST_X"})
        assert ch._token == ""

    def test_chat_id_coerced_to_string(self, monkeypatch) -> None:
        """``config.get("chat_id")`` may come back as an int (e.g.
        from a TOML int field). ``str(...)`` wraps it."""
        from urika.notifications.telegram_channel import TelegramChannel

        ch = TelegramChannel({"chat_id": 12345, "bot_token_env": ""})
        assert ch._chat_id == "12345"


# ── send() — message dispatch + exception swallowing ───────────────


class TestTelegramSend:
    def _make_event(self, **kw):
        from urika.notifications.events import NotificationEvent

        return NotificationEvent(
            event_type=kw.get("event_type", "experiment_started"),
            project_name=kw.get("project_name", "proj"),
            experiment_id=kw.get("experiment_id", "exp-001"),
            summary=kw.get("summary", "summary line"),
            priority=kw.get("priority", "medium"),
        )

    def test_send_swallows_exception_when_bot_call_raises(self, monkeypatch) -> None:
        """send() must NOT propagate Telegram-side errors. The bus's
        dispatch loop has its own try/except, but a raised exception
        here would corrupt the loop for *other* channels."""
        from urika.notifications.telegram_channel import TelegramChannel

        ch = TelegramChannel({"chat_id": "x", "bot_token_env": ""})
        # No token at all — Telegram Bot init will likely raise.
        # send() must not propagate.
        ch.send(self._make_event())  # No assertion — just no exception.

    def test_send_handles_missing_token(self) -> None:
        from urika.notifications.telegram_channel import TelegramChannel

        ch = TelegramChannel({"chat_id": "x", "bot_token_env": ""})
        ch.send(self._make_event())  # No exception.


# ── health_check ───────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_check_no_token_returns_error(self) -> None:
        from urika.notifications.telegram_channel import TelegramChannel

        ch = TelegramChannel({"chat_id": "x", "bot_token_env": ""})
        ok, msg = ch.health_check()
        assert ok is False
        assert "token" in msg.lower()

    def test_health_check_returns_false_on_invalid_token(self, monkeypatch) -> None:
        """A bad token produces (False, <err>) via the exception
        handler. We don't care about the exact wording — only that
        the result shape is preserved."""
        from urika.notifications.telegram_channel import TelegramChannel

        monkeypatch.setenv("TG_TOKEN_FOR_TEST", "obviously-bad-token")
        ch = TelegramChannel({"chat_id": "x", "bot_token_env": "TG_TOKEN_FOR_TEST"})
        ok, msg = ch.health_check()
        # We hit network — InvalidToken / TimedOut / unreachable, all
        # collapse to (False, "...some text...").
        assert ok is False
        assert isinstance(msg, str) and msg


# ── _build_keyboard — event-type-gated inline buttons ──────────────


class TestBuildKeyboard:
    def test_keyboard_is_none_for_non_active_events(self) -> None:
        from urika.notifications.events import NotificationEvent
        from urika.notifications.telegram_channel import TelegramChannel

        for event_type in (
            "experiment_completed",
            "criteria_met",
            "validation_error",
        ):
            event = NotificationEvent(
                event_type=event_type, project_name="p", summary="s"
            )
            assert TelegramChannel._build_keyboard(event) is None, (
                f"Keyboard should be None for {event_type}"
            )

    def test_keyboard_built_for_experiment_started(self) -> None:
        from urika.notifications.events import NotificationEvent
        from urika.notifications.telegram_channel import TelegramChannel

        event = NotificationEvent(
            event_type="experiment_started", project_name="p", summary="s"
        )
        kb = TelegramChannel._build_keyboard(event)
        assert kb is not None
        # Returns an InlineKeyboardMarkup with two rows of two buttons.
        from telegram import InlineKeyboardMarkup

        assert isinstance(kb, InlineKeyboardMarkup)


# ── _handle_command — chat-id gating + bus routing ─────────────────


@pytest.fixture
def _channel():
    """A TelegramChannel with a fake bus + chat_id set."""
    from urika.notifications.telegram_channel import TelegramChannel

    ch = TelegramChannel({"chat_id": "888", "bot_token_env": ""})
    bus = MagicMock()
    ch._bus = bus
    return ch, bus


def _make_update(*, chat_id: str, text: str):
    """Build a stub telegram.Update with the message text + chat_id."""
    message = SimpleNamespace(chat_id=chat_id, text=text, reply_text=MagicMock())
    return SimpleNamespace(message=message, callback_query=None)


class TestHandleCommand:
    @pytest.mark.asyncio
    async def test_routes_status_through_bus(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_command(_make_update(chat_id="888", text="/status"), None)
        # Routed to the bus.
        bus.handle_remote_command.assert_called_once()
        args, kwargs = bus.handle_remote_command.call_args
        assert args[0] == "status"
        assert args[1] == ""  # no args

    @pytest.mark.asyncio
    async def test_command_with_args_passes_args_through(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_command(
            _make_update(chat_id="888", text="/logs experiment_123"),
            None,
        )
        args, _ = bus.handle_remote_command.call_args
        assert args[0] == "logs"
        assert args[1] == "experiment_123"

    @pytest.mark.asyncio
    async def test_drops_command_from_wrong_chat_id(self, _channel) -> None:
        """If chat_id doesn't match the configured one, the command is
        silently dropped — bus must not be called."""
        ch, bus = _channel
        await ch._handle_command(_make_update(chat_id="999", text="/status"), None)
        bus.handle_remote_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_drops_non_slash_message(self, _channel) -> None:
        """``_handle_command`` is for /commands only — plain text
        belongs in ``_handle_free_text``."""
        ch, bus = _channel
        await ch._handle_command(
            _make_update(chat_id="888", text="hello not a command"),
            None,
        )
        bus.handle_remote_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_drops_empty_message(self, _channel) -> None:
        ch, bus = _channel
        update = SimpleNamespace(message=None, callback_query=None)
        await ch._handle_command(update, None)
        bus.handle_remote_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_lowercases_command(self, _channel) -> None:
        """``parts[0].lower()`` — case-insensitive command names."""
        ch, bus = _channel
        await ch._handle_command(_make_update(chat_id="888", text="/STATUS"), None)
        args, _ = bus.handle_remote_command.call_args
        assert args[0] == "status"


# ── _handle_free_text — plain text → "ask" command ─────────────────


class TestHandleFreeText:
    @pytest.mark.asyncio
    async def test_routes_free_text_as_ask(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_free_text(
            _make_update(chat_id="888", text="What should I try next?"),
            None,
        )
        args, _ = bus.handle_remote_command.call_args
        assert args[0] == "ask"
        assert "What should I try next" in args[1]

    @pytest.mark.asyncio
    async def test_drops_empty_text(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_free_text(_make_update(chat_id="888", text="   "), None)
        bus.handle_remote_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_drops_text_from_wrong_chat_id(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_free_text(_make_update(chat_id="bad", text="anything"), None)
        bus.handle_remote_command.assert_not_called()


# ── _handle_callback — inline keyboard button presses ──────────────


class TestHandleCallback:
    def _make_query(self, *, chat_id: str, data: str):
        message = SimpleNamespace(
            chat_id=chat_id,
            reply_text=_AsyncMock(),
        )
        query = SimpleNamespace(
            message=message,
            data=data,
            answer=_AsyncMock(),
            edit_message_reply_markup=_AsyncMock(),
        )
        return SimpleNamespace(message=None, callback_query=query)

    @pytest.mark.asyncio
    async def test_pause_button_routes_pause_command(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_callback(
            self._make_query(chat_id="888", data="urika_pause"), None
        )
        args, _ = bus.handle_remote_command.call_args
        assert args[0] == "pause"

    @pytest.mark.asyncio
    async def test_stop_button_routes_stop_command(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_callback(
            self._make_query(chat_id="888", data="urika_stop"), None
        )
        args, _ = bus.handle_remote_command.call_args
        assert args[0] == "stop"

    @pytest.mark.asyncio
    async def test_unknown_callback_data_does_nothing(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_callback(
            self._make_query(chat_id="888", data="urika_unknown"), None
        )
        bus.handle_remote_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_from_wrong_chat_id_is_dropped(self, _channel) -> None:
        ch, bus = _channel
        await ch._handle_callback(
            self._make_query(chat_id="999", data="urika_pause"), None
        )
        bus.handle_remote_command.assert_not_called()


# ── _esc — HTML escaping ───────────────────────────────────────────


class TestHtmlEscape:
    def test_escapes_lt_gt_amp(self) -> None:
        from urika.notifications.telegram_channel import _esc

        assert _esc("a & b < c > d") == "a &amp; b &lt; c &gt; d"

    def test_ampersand_escaped_first(self) -> None:
        """Order matters — ``&amp;`` must be applied BEFORE the ``<``
        and ``>`` substitutions, or the ``&`` in ``&lt;`` would be
        double-escaped to ``&amp;lt;``."""
        from urika.notifications.telegram_channel import _esc

        # If & is escaped last, the test produces &amp;lt;
        assert _esc("<") == "&lt;"
        assert _esc("&") == "&amp;"
        # The combined case is the one that distinguishes order.
        assert _esc("<&>") == "&lt;&amp;&gt;"

    def test_does_not_escape_safe_chars(self) -> None:
        from urika.notifications.telegram_channel import _esc

        assert _esc("hello world 123 !@#$%^*()") == "hello world 123 !@#$%^*()"


# ── _format_high — high-priority message structure ─────────────────


class TestFormatHigh:
    def test_includes_emoji_label_project_summary(self) -> None:
        from urika.notifications.events import NotificationEvent
        from urika.notifications.telegram_channel import _format_high

        evt = NotificationEvent(
            event_type="experiment_completed",
            project_name="myproj",
            experiment_id="exp-001",
            summary="It worked.",
            priority="high",
        )
        out = _format_high(evt)
        assert "myproj" in out
        assert "exp-001" in out
        assert "It worked." in out
        # The HTML tag wraps something.
        assert "<b>" in out

    def test_metrics_appear_when_present(self) -> None:
        from urika.notifications.events import NotificationEvent
        from urika.notifications.telegram_channel import _format_high

        evt = NotificationEvent(
            event_type="experiment_completed",
            project_name="p",
            experiment_id="exp",
            summary="done",
            details={"metrics": {"r2": 0.81, "rmse": 0.12}},
        )
        out = _format_high(evt)
        assert "r2" in out and "0.81" in out
        assert "rmse" in out


# ── helper: AsyncMock that works on Python 3.7+ ────────────────────


class _AsyncMock(MagicMock):
    """Tiny async-callable mock so test fixtures can build stub query
    objects without depending on unittest.mock.AsyncMock (3.8+).
    """

    async def __call__(self, *args, **kwargs):  # type: ignore[override]
        return super().__call__(*args, **kwargs)
