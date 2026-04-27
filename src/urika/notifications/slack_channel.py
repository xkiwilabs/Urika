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
from urika.notifications.events import EVENT_METADATA, EventMetadata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event-type helpers
# ---------------------------------------------------------------------------

# Fallback metadata for non-canonical event_types. Channels read EVENT_METADATA
# (defined in events.py) for emoji + priority routing; this is the last-resort
# default when the event_type is not registered there.
_DEFAULT_METADATA = EventMetadata(
    emoji="\u2139\ufe0f",  # ℹ️
    priority="low",
    label="Notification",
)


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
        self._allowed_channels: list[str] | None = config.get("allowed_channels", None)
        self._allowed_users: list[str] | None = config.get("allowed_users", None)
        self._bus: object = None  # NotificationBus reference
        self._project_path: Path | None = None
        self._listener_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._socket_client: Any = None

        if self._allowed_channels is None and self._allowed_users is None:
            logger.warning(
                "Slack channel configured without allowed_channels or "
                "allowed_users — any user in the workspace can trigger "
                "actions. Set one to restrict."
            )

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
    # Authorization
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ids(payload: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract (channel_id, user_id) from a Slack interaction payload.

        Button clicks put the ids under ``payload["channel"]["id"]`` /
        ``payload["user"]["id"]``; Event-API wrappers put them under
        ``payload["event"]["channel"]`` / ``payload["event"]["user"]``.
        We try the button-click shape first, fall back to the event shape.
        """
        channel_id: str | None = None
        chan = payload.get("channel")
        if isinstance(chan, dict):
            channel_id = chan.get("id")
        if channel_id is None:
            event = payload.get("event")
            if isinstance(event, dict):
                ev_chan = event.get("channel")
                if isinstance(ev_chan, str):
                    channel_id = ev_chan

        user_id: str | None = None
        user = payload.get("user")
        if isinstance(user, dict):
            user_id = user.get("id")
        if user_id is None:
            event = payload.get("event")
            if isinstance(event, dict):
                ev_user = event.get("user")
                if isinstance(ev_user, str):
                    user_id = ev_user

        return channel_id, user_id

    def _is_authorized(self, payload: dict[str, Any]) -> bool:
        """Check whether an inbound interaction payload is allowed.

        Back-compat: if neither ``allowed_channels`` nor ``allowed_users`` is
        configured, all payloads are allowed. Otherwise fail closed if the
        corresponding list is set but the id is missing or not allowlisted.
        """
        if self._allowed_channels is None and self._allowed_users is None:
            return True

        channel_id, user_id = self._extract_ids(payload)

        if self._allowed_channels is not None:
            if channel_id is None or channel_id not in self._allowed_channels:
                return False
        if self._allowed_users is not None:
            if user_id is None or user_id not in self._allowed_users:
                return False
        return True

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
                # Optional allowlist: drop interactions from unauthorized
                # channels/users before any command dispatch.
                payload = req.payload or {}
                if not self._is_authorized(payload):
                    chan_id, user_id = self._extract_ids(payload)
                    logger.warning(
                        "Slack interaction from unauthorized channel/user "
                        "dropped: channel=%s user=%s",
                        chan_id,
                        user_id,
                    )
                    client.send_socket_mode_response(
                        SocketModeResponse(envelope_id=req.envelope_id)
                    )
                    return

                # Block Kit button clicks arrive as events with actions in the payload
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
                # Handle text messages (free text or /commands from chat).
                # Only process plain messages (no subtype) from humans
                # (no bot_id). Skip edits, deletes, joins, etc.
                event = payload.get("event", {})
                if (
                    event.get("type") == "message"
                    and not event.get("bot_id")
                    and not event.get("subtype")
                ):
                    msg_text = event.get("text", "").strip()
                    channel = event.get("channel", "")
                    if msg_text and self._bus is not None:
                        def _slack_respond(text: str) -> None:
                            try:
                                self._client.chat_postMessage(
                                    channel=channel or self._channel,
                                    text=text,
                                )
                            except Exception as exc:
                                logger.debug("Slack reply failed: %s", exc)

                        if msg_text.startswith("/"):
                            parts = msg_text[1:].split(None, 1)
                            cmd = parts[0].lower()
                            args = parts[1] if len(parts) > 1 else ""
                            self._bus.handle_remote_command(
                                cmd, args, respond=_slack_respond
                            )
                        else:
                            # Free text → orchestrator
                            self._bus.handle_remote_command(
                                "ask", msg_text, respond=_slack_respond
                            )
                        client.send_socket_mode_response(
                            SocketModeResponse(envelope_id=req.envelope_id)
                        )
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
        """Build Slack Block Kit blocks based on event type and priority.

        Priority routing is driven by ``EVENT_METADATA`` for canonical
        event_types and falls back to ``event.priority`` for anything not
        registered there. An explicit high ``event.priority`` from the caller
        promotes the routing — callers can bump a notification up but the
        canonical floor still applies.
        """
        meta = EVENT_METADATA.get(event.event_type)
        canonical_priority = meta.priority if meta else event.priority
        # Caller-supplied "high" wins over a lower canonical priority.
        priority = "high" if event.priority == "high" else canonical_priority

        if priority == "high":
            return self._build_high_priority(event)
        elif priority == "medium":
            return self._build_medium_priority(event)
        else:
            return self._build_low_priority(event)

    def _build_high_priority(self, event: NotificationEvent) -> list[dict[str, Any]]:
        """Header + section + optional metric fields for high-priority events."""
        emoji = EVENT_METADATA.get(event.event_type, _DEFAULT_METADATA).emoji
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
        emoji = EVENT_METADATA.get(event.event_type, _DEFAULT_METADATA).emoji
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
