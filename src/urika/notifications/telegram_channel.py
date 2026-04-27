"""Telegram notification channel using python-telegram-bot.

Supports inbound commands routed through the NotificationBus remote command
handler, plus inline keyboard buttons for the same actions.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from urika.notifications.events import NotificationEvent
    from urika.orchestrator.pause import PauseController

from urika.notifications.base import NotificationChannel
from urika.notifications.events import EVENT_METADATA
from urika.notifications.formatting import format_event_emoji, format_event_label

logger = logging.getLogger(__name__)

# Event types that warrant inline Pause/Stop buttons.
_ACTIVE_RUN_EVENTS = frozenset(
    {
        "experiment_started",
    }
)


class TelegramChannel(NotificationChannel):
    """Telegram notifications via python-telegram-bot (optional dependency)."""

    def __init__(self, config: dict[str, Any]) -> None:
        # Import at init time to fail fast if not installed.
        import telegram  # noqa: F401

        self._chat_id: str = str(config.get("chat_id", ""))
        token_env: str = config.get("bot_token_env", "")
        self._token: str = os.environ.get(token_env, "") if token_env else ""
        self._controller: PauseController | None = None
        self._bus: object = None  # NotificationBus reference
        self._project_path: Path | None = None
        self._listener_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send(self, event: NotificationEvent) -> None:  # noqa: D401
        """Send *event* as a Telegram message.

        Runs the async ``send_message`` call in a fresh OS thread so callers
        already inside an asyncio event loop (e.g. FastAPI handlers) don't
        conflict with the new loop we create. Errors are logged and swallowed
        for the bus dispatch path; the bus itself wraps ``send`` in a try/except
        so callers like the dashboard test-send still see real failures.
        """
        try:
            import telegram

            text = self._format_message(event)
            reply_markup = self._build_keyboard(event)
            token = self._token
            chat_id = self._chat_id

            error: list[BaseException | None] = [None]

            def _do_send() -> None:
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        bot = telegram.Bot(token=token)
                        loop.run_until_complete(
                            bot.send_message(
                                chat_id=chat_id,
                                text=text,
                                parse_mode="HTML",
                                reply_markup=reply_markup,
                            )
                        )
                    finally:
                        loop.close()
                except BaseException as exc:  # noqa: BLE001
                    error[0] = exc

            t = threading.Thread(target=_do_send, daemon=True)
            t.start()
            t.join(timeout=15)
            if t.is_alive():
                raise TimeoutError("Telegram send timed out after 15s")
            if error[0] is not None:
                raise error[0]
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)

    def start_listener(
        self,
        controller: PauseController,
        project_path: Path | None = None,
        bus: object = None,
    ) -> None:
        """Start polling for inbound commands in a background thread."""
        if not self._token:
            logger.debug("No Telegram bot token — listener disabled")
            return
        self._controller = controller
        self._bus = bus
        self._project_path = project_path
        self._stop_event.clear()
        self._listener_thread = threading.Thread(
            target=self._poll_loop,
            name="urika-telegram-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def stop_listener(self) -> None:
        """Signal the polling thread to shut down."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None

    def health_check(self) -> tuple[bool, str]:
        """Probe the bot token via Telegram's ``getMe`` endpoint.

        Runs the async probe in a fresh OS thread so a caller already inside
        an asyncio event loop (e.g. a FastAPI handler) doesn't conflict with
        the new loop we create. Returns ``(True, "")`` on success,
        ``(False, error_message)`` on InvalidToken / TimedOut / NetworkError
        / any other exception.
        """
        if not self._token:
            return (False, "no bot token configured")

        result: list[tuple[bool, str]] = [(False, "health check did not run")]

        def _probe() -> None:
            try:
                from telegram import Bot

                loop = asyncio.new_event_loop()
                try:
                    bot = Bot(token=self._token)
                    loop.run_until_complete(bot.get_me())
                    result[0] = (True, "")
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                result[0] = (False, str(exc))

        t = threading.Thread(target=_probe, daemon=True)
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            return (False, "health check timed out after 10s")
        return result[0]

    # ------------------------------------------------------------------
    # Message formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_message(event: NotificationEvent) -> str:
        """Build an HTML-formatted Telegram message from *event*.

        Priority routing is driven by ``EVENT_METADATA`` for canonical
        event_types and falls back to ``event.priority`` for anything not
        registered there. An explicit high ``event.priority`` from the caller
        promotes the routing — callers can bump a notification up but the
        canonical floor still applies.
        """
        meta = EVENT_METADATA.get(event.event_type)
        canonical_priority = meta.priority if meta else event.priority
        priority = "high" if event.priority == "high" else canonical_priority
        if priority == "high":
            return _format_high(event)
        return _format_default(event)

    @staticmethod
    def _build_keyboard(event: NotificationEvent) -> Any | None:
        """Return an InlineKeyboardMarkup with Pause/Stop/Status/Results for active-run events."""
        if event.event_type not in _ACTIVE_RUN_EVENTS:
            return None

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = [
                [
                    InlineKeyboardButton("\u23f8 Pause", callback_data="urika_pause"),
                    InlineKeyboardButton("\u23f9 Stop", callback_data="urika_stop"),
                ],
                [
                    InlineKeyboardButton(
                        "\U0001f4ca Status", callback_data="urika_status"
                    ),
                    InlineKeyboardButton(
                        "\U0001f3c6 Results", callback_data="urika_results"
                    ),
                ],
            ]
            return InlineKeyboardMarkup(keyboard)
        except Exception as exc:
            logger.debug("Keyboard build failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Inbound polling
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread entry: run Telegram polling in its own event loop."""
        try:
            from telegram.ext import (
                ApplicationBuilder,
                CallbackQueryHandler,
                MessageHandler,
                filters,
            )
        except Exception as exc:
            logger.warning("Cannot start Telegram listener: %s", exc)
            return

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self._run_polling(
                    ApplicationBuilder,
                    MessageHandler,
                    CallbackQueryHandler,
                    filters,
                )
            )
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.warning("Telegram polling error: %s", exc)
        finally:
            loop.close()

    async def _run_polling(
        self,
        ApplicationBuilder: Any,
        MessageHandler: Any,
        CallbackQueryHandler: Any,
        filters: Any,
    ) -> None:
        """Build the Application, register handlers, and poll until stopped."""
        app = ApplicationBuilder().token(self._token).build()

        # Single handler for all /commands — routed through the bus
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_command))
        # Free text — routed to the orchestrator via the bus
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_free_text)
        )
        # Callback queries (inline buttons)
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Block until stop_listener() sets the event.
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    async def _handle_command(self, update: Any, context: Any) -> None:
        """Route any /command through the bus."""
        if not update.message or not update.message.text:
            return

        # Verify sender matches configured chat_id
        if self._chat_id and str(update.message.chat_id) != str(self._chat_id):
            logger.warning(
                "Ignoring command from unauthorized chat_id %s",
                update.message.chat_id,
            )
            return

        text = update.message.text.strip()
        if not text.startswith("/"):
            return

        parts = text[1:].split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if self._bus is not None:
            chat_id = update.message.chat_id

            def _send_reply(resp: str) -> None:
                """Send a reply via HTTP API — works from any thread, no event loop needed."""
                try:
                    import urllib.request
                    import urllib.parse
                    import json as _json

                    url = f"https://api.telegram.org/bot{self._token}/sendMessage"
                    payload = _json.dumps(
                        {
                            "chat_id": chat_id,
                            "text": resp,
                        }
                    ).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=10)
                except Exception as exc:
                    logger.warning("Telegram reply failed: %s", exc)

            self._bus.handle_remote_command(command, args, respond=_send_reply)
        elif self._controller is not None:
            # Fallback: direct control if no bus (shouldn't happen)
            if command == "pause":
                self._controller.request_pause()
                await update.message.reply_text("Pause requested \u23f8")
            elif command == "stop":
                self._controller.request_stop()
                await update.message.reply_text("Stop requested \u23f9")

    async def _handle_free_text(self, update: Any, context: Any) -> None:
        """Route plain text messages to the orchestrator via the bus."""
        if not update.message or not update.message.text:
            return

        # Verify sender
        if self._chat_id and str(update.message.chat_id) != str(self._chat_id):
            return

        text = update.message.text.strip()
        if not text or self._bus is None:
            return

        chat_id = update.message.chat_id

        def _send_reply(resp: str) -> None:
            try:
                import urllib.request
                import json as _json

                url = f"https://api.telegram.org/bot{self._token}/sendMessage"
                payload = _json.dumps(
                    {"chat_id": chat_id, "text": resp}
                ).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception as exc:
                logger.warning("Telegram reply failed: %s", exc)

        self._bus.handle_remote_command("ask", text, respond=_send_reply)

    async def _handle_callback(self, update: Any, context: Any) -> None:
        """Handle inline keyboard button presses — route through the bus."""
        query = update.callback_query
        if query is None:
            return

        # Verify sender matches configured chat_id
        if self._chat_id and str(query.message.chat_id) != str(self._chat_id):
            logger.warning(
                "Ignoring callback from unauthorized chat_id %s",
                query.message.chat_id,
            )
            await query.answer()
            return

        await query.answer()

        # Map callback data to commands
        data = query.data or ""
        command_map = {
            "urika_pause": ("pause", ""),
            "urika_stop": ("stop", ""),
            "urika_status": ("status", ""),
            "urika_results": ("results", ""),
        }

        if data in command_map and self._bus is not None:
            cmd, args = command_map[data]
            response_text: list[str] = []

            def sync_respond(resp: str) -> None:
                response_text.append(resp)

            self._bus.handle_remote_command(cmd, args, respond=sync_respond)
            for resp in response_text:
                try:
                    await query.message.reply_text(resp)
                except Exception:
                    pass
            # Remove buttons after click
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass


# ----------------------------------------------------------------------
# Formatting helpers (module-level to keep the class lean)
# ----------------------------------------------------------------------


def _esc(text: str) -> str:
    """Minimal HTML escaping for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_high(event: NotificationEvent) -> str:
    """Rich format for high-priority events."""
    emoji = format_event_emoji(event)
    label = format_event_label(event)
    lines = [
        f"<b>{emoji} {_esc(label)}</b>",
        f"<b>Project:</b> {_esc(event.project_name)}",
    ]
    if event.experiment_id:
        lines.append(f"<b>Experiment:</b> {_esc(event.experiment_id)}")
    lines.append(f"\n{_esc(event.summary)}")

    # Append metrics from details if present.
    metrics = event.details.get("metrics") if event.details else None
    if isinstance(metrics, dict):
        metric_lines = [f"  {_esc(k)}: {v}" for k, v in metrics.items()]
        lines.append("\n<b>Metrics:</b>\n" + "\n".join(metric_lines))

    return "\n".join(lines)


def _format_default(event: NotificationEvent) -> str:
    """Compact format for medium/low-priority events."""
    prefix = f"[{_esc(event.project_name)}]"
    if event.experiment_id:
        prefix += f" ({_esc(event.experiment_id)})"
    return f"{prefix} {_esc(event.summary)}"
