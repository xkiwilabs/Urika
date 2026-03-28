"""Tests for the email notification channel."""

from __future__ import annotations

import logging
from typing import Any

from urika.notifications.email_channel import EmailChannel
from urika.notifications.events import NotificationEvent


def _make_event(
    summary: str = "test", priority: str = "high", event_type: str = "test_event"
) -> NotificationEvent:
    return NotificationEvent(
        event_type=event_type,
        project_name="my-project",
        summary=summary,
        priority=priority,
    )


def _email_config() -> dict[str, Any]:
    return {
        "to": ["alice@example.com"],
        "from_addr": "urika@example.com",
        "smtp_server": "smtp.example.com",
        "smtp_port": 587,
        "username": "urika@example.com",
        "password_env": "",
    }


class FakeSMTP:
    """Stand-in for smtplib.SMTP that records sent messages."""

    instances: list[FakeSMTP] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.sent: list[tuple[str, list[str], str]] = []
        FakeSMTP.instances.append(self)

    def starttls(self, **kwargs: Any) -> None:
        pass

    def login(self, user: str, pwd: str) -> None:
        pass

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        self.sent.append((from_addr, to_addrs, msg))

    def quit(self) -> None:
        pass

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class TestEmailChannel:
    def setup_method(self) -> None:
        FakeSMTP.instances.clear()

    def test_init(self):
        """Creates with config dict."""
        ch = EmailChannel(_email_config())
        assert ch._to == ["alice@example.com"]
        assert ch._server == "smtp.example.com"
        assert ch._port == 587

    def test_send_high_priority(self, monkeypatch):
        """Mock smtplib.SMTP, send a high-priority event, verify SMTP called."""
        monkeypatch.setattr("urika.notifications.email_channel.smtplib.SMTP", FakeSMTP)
        ch = EmailChannel(_email_config())
        ch.send(_make_event("Criteria met!", priority="high"))

        assert len(FakeSMTP.instances) == 1
        smtp = FakeSMTP.instances[0]
        assert len(smtp.sent) == 1
        assert smtp.sent[0][0] == "urika@example.com"
        assert smtp.sent[0][1] == ["alice@example.com"]

    def test_send_low_priority_batches(self, monkeypatch):
        """Low-priority event is batched; high-priority flushes the batch."""
        monkeypatch.setattr("urika.notifications.email_channel.smtplib.SMTP", FakeSMTP)
        ch = EmailChannel(_email_config())

        # Low-priority: should not trigger send
        ch.send(_make_event("Turn 1/5", priority="low"))
        assert len(FakeSMTP.instances) == 0

        # High-priority: should flush both events
        ch.send(_make_event("Criteria met!", priority="high"))
        assert len(FakeSMTP.instances) == 1
        smtp = FakeSMTP.instances[0]
        assert len(smtp.sent) == 1
        # The email body should contain both summaries
        body = smtp.sent[0][2]
        assert "Turn 1/5" in body
        assert "Criteria met!" in body

    def test_stop_flushes_pending(self, monkeypatch):
        """stop_listener() flushes any remaining batched events."""
        monkeypatch.setattr("urika.notifications.email_channel.smtplib.SMTP", FakeSMTP)
        ch = EmailChannel(_email_config())

        ch.send(_make_event("queued event", priority="low"))
        assert len(FakeSMTP.instances) == 0

        ch.stop_listener()
        assert len(FakeSMTP.instances) == 1
        body = FakeSMTP.instances[0].sent[0][2]
        assert "queued event" in body

    def test_send_error_logged(self, monkeypatch, caplog):
        """Mock SMTP to raise, verify no exception and warning logged."""

        def raise_on_smtp(*args: Any, **kwargs: Any) -> None:
            raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(
            "urika.notifications.email_channel.smtplib.SMTP", raise_on_smtp
        )
        ch = EmailChannel(_email_config())

        with caplog.at_level(
            logging.WARNING, logger="urika.notifications.email_channel"
        ):
            # Should not raise
            ch.send(_make_event("fail event", priority="high"))

        assert "Failed to send email notification" in caplog.text

    def test_html_contains_summary(self, monkeypatch):
        """Capture the email body and verify it contains the event summary."""
        monkeypatch.setattr("urika.notifications.email_channel.smtplib.SMTP", FakeSMTP)
        ch = EmailChannel(_email_config())
        ch.send(
            _make_event(
                "RMSE improved to 0.31", priority="high", event_type="run_recorded"
            )
        )

        assert len(FakeSMTP.instances) == 1
        body = FakeSMTP.instances[0].sent[0][2]
        assert "RMSE improved to 0.31" in body
        assert "my-project" in body

    def test_medium_priority_sends_immediately(self, monkeypatch):
        """Medium-priority events trigger immediate send (like high)."""
        monkeypatch.setattr("urika.notifications.email_channel.smtplib.SMTP", FakeSMTP)
        ch = EmailChannel(_email_config())
        ch.send(_make_event("Paused by user", priority="medium"))

        assert len(FakeSMTP.instances) == 1
        smtp = FakeSMTP.instances[0]
        assert len(smtp.sent) == 1

    def test_subject_line_format(self, monkeypatch):
        """Subject line includes project name and summary."""
        monkeypatch.setattr("urika.notifications.email_channel.smtplib.SMTP", FakeSMTP)
        ch = EmailChannel(_email_config())
        ch.send(_make_event("Target reached", priority="high"))

        raw = FakeSMTP.instances[0].sent[0][2]
        # Subject is MIME-encoded; decode it to verify content
        from email import message_from_string
        from email.header import decode_header

        msg = message_from_string(raw)
        subject_parts = decode_header(msg["Subject"])
        subject = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in subject_parts
        )
        assert "[Urika] my-project" in subject
        assert "Target reached" in subject
