"""Email notification channel — SMTP outbound using stdlib."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from urika.notifications.base import NotificationChannel
from urika.notifications.events import NotificationEvent

logger = logging.getLogger(__name__)

# Priority levels that trigger immediate send (flush pending batch too).
_HIGH_PRIORITIES = frozenset({"high", "medium"})


class EmailChannel(NotificationChannel):
    """SMTP email notifications — stdlib only, no external dependencies."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._to: list[str] = config.get("to", [])
        self._from: str = config.get("from_addr", "")
        self._server: str = config.get("smtp_server", "smtp.gmail.com")
        self._port: int = config.get("smtp_port", 587)
        self._username: str = config.get("username", self._from)
        self._password_env: str = config.get("password_env", "")
        self._pending: list[NotificationEvent] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send(self, event: NotificationEvent) -> None:  # noqa: D401
        """Dispatch *event* — batches low-priority, flushes on medium/high."""
        if event.priority == "low":
            self._pending.append(event)
            return

        # Medium / high: flush any pending events together with this one.
        events_to_send = self._pending + [event]
        self._pending = []
        self._send_email(events_to_send)

    def stop_listener(self) -> None:
        """Flush any remaining batched events on shutdown."""
        if self._pending:
            self._send_email(self._pending)
            self._pending = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_email(self, events: list[NotificationEvent]) -> None:
        """Build and send an HTML email. All errors are caught and logged."""
        if not events or not self._to:
            return

        try:
            subject = self._build_subject(events)
            html = self._build_html(events)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._from
            msg["To"] = ", ".join(self._to)
            msg.attach(MIMEText(html, "html"))

            password = (
                os.environ.get(self._password_env, "") if self._password_env else ""
            )

            ctx = ssl.create_default_context()
            with smtplib.SMTP(self._server, self._port, timeout=15) as smtp:
                smtp.starttls(context=ctx)
                if password:
                    smtp.login(self._username, password)
                smtp.sendmail(self._from, self._to, msg.as_string())

            logger.info(
                "Email notification sent to %s (%d event(s))",
                ", ".join(self._to),
                len(events),
            )
        except Exception:
            logger.exception("Failed to send email notification")

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _build_subject(events: list[NotificationEvent]) -> str:
        """Subject line from the highest-priority (or most recent) event."""
        # Prefer the last high-priority event; fall back to the last event.
        primary = events[-1]
        for evt in reversed(events):
            if evt.priority == "high":
                primary = evt
                break
        return f"[Urika] {primary.project_name} \u2014 {primary.summary}"

    @staticmethod
    def _build_html(events: list[NotificationEvent]) -> str:
        """Render a simple HTML digest email with inline CSS."""
        rows = ""
        for evt in events:
            priority_color = {
                "high": "#d32f2f",
                "medium": "#f57c00",
                "low": "#757575",
            }.get(evt.priority, "#757575")
            experiment_cell = (
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee;">'
                f"{_esc(evt.experiment_id)}</td>"
                if evt.experiment_id
                else '<td style="padding:8px 12px;border-bottom:1px solid #eee;">&mdash;</td>'
            )
            rows += (
                "<tr>"
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee;'
                f'color:{priority_color};font-weight:600;">{_esc(evt.event_type)}</td>'
                f"{experiment_cell}"
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee;">'
                f"{_esc(evt.summary)}</td>"
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee;'
                f'color:#999;font-size:12px;">{_esc(evt.timestamp)}</td>'
                "</tr>"
            )

        project_name = _esc(events[0].project_name)

        return (
            "<!DOCTYPE html>"
            '<html><head><meta charset="utf-8"></head>'
            '<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;'
            'background:#f5f5f5;">'
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:640px;margin:20px auto;background:#fff;'
            'border:1px solid #ddd;border-radius:6px;overflow:hidden;">'
            # Header
            '<tr><td style="background:#1a237e;color:#fff;padding:16px 20px;'
            'font-size:18px;font-weight:700;">'
            f"Urika &mdash; {project_name}</td></tr>"
            # Body
            '<tr><td style="padding:16px 20px;">'
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;">'
            '<tr style="background:#f9f9f9;">'
            '<th style="padding:8px 12px;text-align:left;font-size:13px;'
            'color:#555;border-bottom:2px solid #ddd;">Event</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:13px;'
            'color:#555;border-bottom:2px solid #ddd;">Experiment</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:13px;'
            'color:#555;border-bottom:2px solid #ddd;">Summary</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:13px;'
            'color:#555;border-bottom:2px solid #ddd;">Time</th>'
            "</tr>"
            f"{rows}"
            "</table>"
            "</td></tr>"
            # Footer
            '<tr><td style="padding:12px 20px;font-size:11px;color:#999;'
            'border-top:1px solid #eee;text-align:center;">'
            "Sent by Urika notification system</td></tr>"
            "</table>"
            "</body></html>"
        )


def _esc(text: str) -> str:
    """Minimal HTML escaping for user-supplied text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
