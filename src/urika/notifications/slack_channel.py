"""Slack notification channel using slack-sdk.

Sends rich Block Kit messages to a Slack channel and optionally listens for
inbound Pause/Stop button clicks via Socket Mode.  Status and Results buttons
allow read-only project queries from Slack.

Requires the ``slack-sdk`` package (optional dependency).
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Event-type helpers
# ---------------------------------------------------------------------------

_HIGH_PRIORITY_TYPES = {"criteria_met", "experiment_failed", "experiment_completed"}
_MEDIUM_PRIORITY_TYPES = {"paused"}
_LOW_PRIORITY_TYPES = {"turn_started", "run_recorded"}

_EMOJI_MAP: dict[str, str] = {
    "criteria_met": "\u2705",  # checkmark
    "experiment_failed": "\u274c",  # cross
    "experiment_completed": "\U0001f3c1",  # flag
    "paused": "\u23f8\ufe0f",  # pause
}


class SlackChannel(NotificationChannel):
    """Slack notification channel with outbound Block Kit messages and optional Socket Mode listener."""

    def __init__(self, config: dict[str, Any]) -> None:
        try:
            from slack_sdk import WebClient
        except ImportError as exc:
            raise ImportError(
                "slack-sdk is required for Slack notifications. "
                "Install it with: pip install slack-sdk"
            ) from exc

        self._channel: str = config.get("channel", "")
        token_env = config.get("bot_token_env", "")
        token = os.environ.get(token_env, "")
        self._client = WebClient(token=token)
        self._app_token_env: str = config.get("app_token_env", "")
        self._bus: object = None  # NotificationBus reference
        self._project_path: Path | None = None
        self._listener_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._socket_client: Any = None

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def send(self, event: NotificationEvent) -> None:
        """Send a Block Kit message to the configured Slack channel.

        Never raises -- all exceptions are caught and logged.
        """
        try:
            blocks = self._build_blocks(event)
            self._client.chat_postMessage(
                channel=self._channel,
                blocks=blocks,
                text=event.summary,  # Fallback for push notifications
            )
        except Exception as exc:
            logger.warning("Slack send failed: %s", exc)

    # ------------------------------------------------------------------
    # Inbound (Socket Mode)
    # ------------------------------------------------------------------

    def start_listener(
        self,
        controller: PauseController,
        project_path: Path | None = None,
        bus: object = None,
    ) -> None:
        """Start a Socket Mode listener in a background thread.

        If ``app_token_env`` was not configured or the env var is empty, this
        is a no-op.
        """
        self._bus = bus
        self._project_path = project_path
        if not self._app_token_env:
            return

        app_token = os.environ.get(self._app_token_env, "")
        if not app_token:
            logger.debug(
                "Slack app token env var %r is empty — inbound listener disabled",
                self._app_token_env,
            )
            return

        self._stop_event.clear()
        self._listener_thread = threading.Thread(
            target=self._run_socket_mode,
            args=(app_token, controller),
            name="urika-slack-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def stop_listener(self) -> None:
        """Stop the Socket Mode listener thread."""
        self._stop_event.set()
        if self._socket_client is not None:
            try:
                self._socket_client.close()
            except Exception as exc:
                logger.debug("Error closing Slack socket client: %s", exc)
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=3.0)
            self._listener_thread = None

    # ------------------------------------------------------------------
    # Socket Mode internals
    # ------------------------------------------------------------------

    def _run_socket_mode(self, app_token: str, controller: PauseController) -> None:
        """Run the Socket Mode client. Executed in a daemon thread."""
        try:
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError:
            logger.warning(
                "slack-sdk[socket_mode] not available — inbound listener disabled"
            )
            return

        try:
            self._socket_client = SocketModeClient(
                app_token=app_token,
                web_client=self._client,
            )

            def _handle_interaction(
                client: SocketModeClient, req: SocketModeRequest
            ) -> None:
                # TODO: Restrict interactions to authorized users/channels.
                # Slack's architecture routes button clicks through Slack's
                # servers, making sender verification harder than Telegram.
                # Consider checking payload.user.id or payload.channel.id
                # against an allow-list in future.

                # Block Kit button clicks arrive as events with actions in the payload
                payload = req.payload or {}
                actions = payload.get("actions", [])
                if actions:
                    for action in actions:
                        action_id = action.get("action_id", "")
                        command_map = {
                            "pause": ("pause", ""),
                            "stop": ("stop", ""),
                            "status": ("status", ""),
                            "results": ("results", ""),
                        }
                        if action_id in command_map and self._bus is not None:
                            cmd, args = command_map[action_id]
                            response_text: list[str] = []

                            def sync_respond(text: str) -> None:
                                response_text.append(text)

                            self._bus.handle_remote_command(
                                cmd, args, respond=sync_respond
                            )
                            _ack_action(
                                client,
                                req,
                                response_text[0] if response_text else "Done",
                            )
                            return
                        elif action_id in command_map:
                            # Fallback: direct control if no bus
                            if action_id == "pause":
                                controller.request_pause()
                                _ack_action(client, req, "Pause requested.")
                            elif action_id == "stop":
                                controller.request_stop()
                                _ack_action(client, req, "Stop requested.")
                            return
                # Acknowledge anything we don't handle to avoid Slack retries
                client.send_socket_mode_response(
                    SocketModeResponse(envelope_id=req.envelope_id)
                )

            def _ack_action(
                client: SocketModeClient,
                req: SocketModeRequest,
                text: str,
            ) -> None:
                client.send_socket_mode_response(
                    SocketModeResponse(envelope_id=req.envelope_id)
                )
                # Post a confirmation message in the channel
                try:
                    self._client.chat_postMessage(
                        channel=self._channel,
                        text=text,
                    )
                except Exception as exc:
                    logger.debug("Slack ack message failed: %s", exc)

            self._socket_client.socket_mode_request_listeners.append(
                _handle_interaction
            )
            self._socket_client.connect()

            # Block until stop is requested
            self._stop_event.wait()
        except Exception as exc:
            logger.warning("Slack Socket Mode listener failed: %s", exc)

    # ------------------------------------------------------------------
    # Block Kit builder
    # ------------------------------------------------------------------

    def _build_blocks(self, event: NotificationEvent) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks based on event type and priority."""
        event_type = event.event_type
        blocks: list[dict[str, Any]] = []

        if event_type in _HIGH_PRIORITY_TYPES:
            blocks = self._build_high_priority(event)
        elif event_type in _MEDIUM_PRIORITY_TYPES:
            blocks = self._build_medium_priority(event)
        else:
            blocks = self._build_low_priority(event)

        return blocks

    def _build_high_priority(self, event: NotificationEvent) -> list[dict[str, Any]]:
        """Header + section + optional metric fields for high-priority events."""
        emoji = _EMOJI_MAP.get(event.event_type, "\u2139\ufe0f")
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {event.event_type.replace('_', ' ').title()}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Project:* {event.project_name}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Experiment:* {event.experiment_id or 'N/A'}",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": event.summary,
                },
            },
        ]

        # Append metrics from details if present
        metrics = event.details.get("metrics")
        if isinstance(metrics, dict) and metrics:
            metric_fields = [
                {"type": "mrkdwn", "text": f"*{k}:* {v}"} for k, v in metrics.items()
            ]
            blocks.append({"type": "section", "fields": metric_fields})

        return blocks

    def _build_medium_priority(self, event: NotificationEvent) -> list[dict[str, Any]]:
        """Simple section with emoji for medium-priority events."""
        emoji = _EMOJI_MAP.get(event.event_type, "\u2139\ufe0f")
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} {event.summary}",
                },
            },
        ]

    def _build_low_priority(self, event: NotificationEvent) -> list[dict[str, Any]]:
        """Context block + action buttons for low-priority events."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"{event.project_name}"
                            f"{' / ' + event.experiment_id if event.experiment_id else ''}"
                            f" \u2014 {event.summary}"
                        ),
                    },
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Pause", "emoji": True},
                        "action_id": "pause",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Stop", "emoji": True},
                        "action_id": "stop",
                        "style": "danger",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Status",
                            "emoji": True,
                        },
                        "action_id": "status",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Results",
                            "emoji": True,
                        },
                        "action_id": "results",
                    },
                ],
            },
        ]
        return blocks
