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
from urika.notifications.events import EVENT_METADATA, EventMetadata

logger = logging.getLogger(__name__)

# Event types that warrant inline Pause/Stop buttons.
_ACTIVE_RUN_EVENTS = frozenset(
    {
        "experiment_started",
    }
)

# Fallback metadata for non-canonical event_types. The high-priority formatter
# reads EVENT_METADATA for the emoji and falls back to this when an event_type
# is not registered there.
_DEFAULT_METADATA = EventMetadata(
    emoji="\U0001f514",  # 🔔
    priority="low",
    label="Notification",
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
        """Send *event* as a Telegram message. Never raises."""
        try:
            import telegram

            bot = telegram.Bot(token=self._token)
            text = self._format_message(event)
            reply_markup = self._build_keyboard(event)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    bot.send_message(
                        chat_id=self._chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                )
            finally:
                loop.close()
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

    # ------------------------------------------------------------------
    # Message formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_message(event: NotificationEvent) -> str:
        """Build an HTML-formatted Telegram message from *event*."""
        if event.priority == "high":
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
    emoji = EVENT_METADATA.get(event.event_type, _DEFAULT_METADATA).emoji
    lines = [
        f"<b>{emoji} {_esc(event.event_type.replace('_', ' ').title())}</b>",
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
