"""Telegram notification channel using python-telegram-bot.

Supports inbound /pause, /stop, /status, and /results commands as well as
inline keyboard buttons for the same actions.
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

logger = logging.getLogger(__name__)

# Event types that warrant inline Pause/Stop buttons.
_ACTIVE_RUN_EVENTS = frozenset(
    {
        "turn_started",
        "run_recorded",
        "experiment_starting",
    }
)

# Emoji map for high-priority event types.
_EMOJI: dict[str, str] = {
    "criteria_met": "\u2705",  # ✅
    "error": "\u274c",  # ❌
    "experiment_complete": "\U0001f3c1",  # 🏁
    "finalize_complete": "\U0001f3c1",  # 🏁
}


class TelegramChannel(NotificationChannel):
    """Telegram notifications via python-telegram-bot (optional dependency)."""

    def __init__(self, config: dict[str, Any]) -> None:
        # Import at init time to fail fast if not installed.
        import telegram  # noqa: F401

        self._chat_id: str = str(config.get("chat_id", ""))
        token_env: str = config.get("bot_token_env", "")
        self._token: str = os.environ.get(token_env, "") if token_env else ""
        self._controller: PauseController | None = None
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
        self, controller: PauseController, project_path: Path | None = None
    ) -> None:
        """Start polling for inbound commands in a background thread."""
        if not self._token:
            logger.debug("No Telegram bot token — listener disabled")
            return
        self._controller = controller
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
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Project queries
    # ------------------------------------------------------------------

    def _query_status(self) -> str:
        """Return project status text, or a fallback if unavailable."""
        if self._project_path is None:
            return "No project loaded."
        try:
            from urika.notifications.queries import get_status_text

            return get_status_text(self._project_path)
        except Exception as exc:
            logger.debug("Status query failed: %s", exc)
            return f"Status query failed: {exc}"

    def _query_results(self) -> str:
        """Return project results text, or a fallback if unavailable."""
        if self._project_path is None:
            return "No project loaded."
        try:
            from urika.notifications.queries import get_results_text

            return get_results_text(self._project_path)
        except Exception as exc:
            logger.debug("Results query failed: %s", exc)
            return f"Results query failed: {exc}"

    # ------------------------------------------------------------------
    # Inbound polling
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread entry: run Telegram polling in its own event loop."""
        try:
            from telegram.ext import (
                ApplicationBuilder,
                CallbackQueryHandler,
                CommandHandler,
            )
        except Exception as exc:
            logger.warning("Cannot start Telegram listener: %s", exc)
            return

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self._run_polling(
                    ApplicationBuilder,
                    CommandHandler,
                    CallbackQueryHandler,
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
        CommandHandler: Any,
        CallbackQueryHandler: Any,
    ) -> None:
        """Build the Application, register handlers, and poll until stopped."""
        app = ApplicationBuilder().token(self._token).build()

        app.add_handler(CommandHandler("pause", self._handle_pause_command))
        app.add_handler(CommandHandler("stop", self._handle_stop_command))
        app.add_handler(CommandHandler("status", self._handle_status_command))
        app.add_handler(CommandHandler("results", self._handle_results_command))
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

    async def _handle_pause_command(self, update: Any, context: Any) -> None:
        """Handle /pause from a Telegram user."""
        if self._controller is not None:
            self._controller.request_pause()
            logger.info("Pause requested via Telegram /pause command")
        if update.message:
            await update.message.reply_text("Pause requested \u23f8")

    async def _handle_stop_command(self, update: Any, context: Any) -> None:
        """Handle /stop from a Telegram user."""
        if self._controller is not None:
            self._controller.request_stop()
            logger.info("Stop requested via Telegram /stop command")
        if update.message:
            await update.message.reply_text("Stop requested \u23f9")

    async def _handle_status_command(self, update: Any, context: Any) -> None:
        """Handle /status from a Telegram user."""
        if self._project_path is None:
            text = "No project loaded."
        else:
            try:
                from urika.notifications.queries import get_status_text

                text = get_status_text(self._project_path)
            except Exception as exc:
                logger.debug("Status query failed: %s", exc)
                text = f"Status query failed: {exc}"
        if update.message:
            await update.message.reply_text(text)

    async def _handle_results_command(self, update: Any, context: Any) -> None:
        """Handle /results from a Telegram user."""
        if self._project_path is None:
            text = "No project loaded."
        else:
            try:
                from urika.notifications.queries import get_results_text

                text = get_results_text(self._project_path)
            except Exception as exc:
                logger.debug("Results query failed: %s", exc)
                text = f"Results query failed: {exc}"
        if update.message:
            await update.message.reply_text(text)

    async def _handle_callback(self, update: Any, context: Any) -> None:
        """Handle inline keyboard button presses (Pause / Stop / Status / Results)."""
        query = update.callback_query
        if query is None:
            return
        await query.answer()

        if query.data == "urika_pause" and self._controller is not None:
            self._controller.request_pause()
            await query.edit_message_reply_markup(reply_markup=None)
            logger.info("Pause requested via Telegram inline button")
        elif query.data == "urika_stop" and self._controller is not None:
            self._controller.request_stop()
            await query.edit_message_reply_markup(reply_markup=None)
            logger.info("Stop requested via Telegram inline button")
        elif query.data == "urika_status":
            text = self._query_status()
            try:
                import telegram

                bot = telegram.Bot(token=self._token)
                await bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                )
            except Exception as exc:
                logger.debug("Status callback reply failed: %s", exc)
        elif query.data == "urika_results":
            text = self._query_results()
            try:
                import telegram

                bot = telegram.Bot(token=self._token)
                await bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                )
            except Exception as exc:
                logger.debug("Results callback reply failed: %s", exc)


# ----------------------------------------------------------------------
# Formatting helpers (module-level to keep the class lean)
# ----------------------------------------------------------------------


def _esc(text: str) -> str:
    """Minimal HTML escaping for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_high(event: NotificationEvent) -> str:
    """Rich format for high-priority events."""
    emoji = _EMOJI.get(event.event_type, "\U0001f514")  # 🔔 default
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
