"""Abstract base for notification channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urika.notifications.events import NotificationEvent
    from urika.orchestrator.pause import PauseController


class NotificationChannel(ABC):
    """Base class for notification backends (email, Slack, Telegram)."""

    @abstractmethod
    def send(self, event: NotificationEvent) -> None:
        """Send a notification event. Must not raise — log errors internally."""
        ...

    def start_listener(
        self,
        controller: PauseController,
        project_path: Path | None = None,
        bus: object = None,
    ) -> None:
        """Start listening for inbound commands (optional, for bidirectional channels)."""

    def stop_listener(self) -> None:
        """Stop the inbound command listener."""

    def health_check(self) -> tuple[bool, str]:
        """Probe the channel's external dependency (auth, network).

        Returns ``(True, "")`` if healthy, ``(False, error_message)`` if not.
        Default is ``(True, "")`` — channels without remote dependencies opt out.
        Subclasses with remote services (Slack, Telegram, SMTP) should override
        with a non-listening sanity probe (auth_test, getMe, SMTP NOOP, etc.).
        """
        return (True, "")
