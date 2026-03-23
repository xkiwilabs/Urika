"""REPL session state — project context, advisor conversation, usage tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ReplSession:
    """Manages state for an interactive REPL session."""

    project_path: Path | None = None
    project_name: str | None = None
    conversation: list[dict[str, str]] = field(default_factory=list)

    # Usage tracking
    session_start: float = field(default_factory=time.monotonic)
    session_start_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    agent_calls: int = 0
    experiments_run: int = 0
    model: str = ""

    @property
    def has_project(self) -> bool:
        return self.project_path is not None

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.session_start) * 1000)

    def load_project(self, path: Path, name: str) -> None:
        self.save_usage()  # save current project's usage first
        self.project_path = path
        self.project_name = name
        self.conversation = []
        # Reset usage for new project
        self.session_start = time.monotonic()
        self.session_start_iso = datetime.now(timezone.utc).isoformat()
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost_usd = 0.0
        self.agent_calls = 0
        self.experiments_run = 0

    def clear_project(self) -> None:
        self.project_path = None
        self.project_name = None
        self.conversation = []

    def add_message(self, role: str, text: str) -> None:
        self.conversation.append({"role": role, "text": text})

    def get_conversation_context(self, max_exchanges: int = 10) -> str:
        recent = self.conversation[-max_exchanges:]
        lines = []
        for msg in recent:
            prefix = "User" if msg["role"] == "user" else "Advisor"
            lines.append(f"{prefix}: {msg['text']}")
        return "\n".join(lines)

    def record_agent_call(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        model: str = "",
    ) -> None:
        """Record an agent call's usage stats."""
        self.agent_calls += 1
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost_usd
        if model:
            self.model = model

    def save_usage(self) -> None:
        """Save session usage to project's usage.json."""
        if not self.has_project:
            return
        from urika.core.usage import record_session

        record_session(
            self.project_path,
            started=self.session_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=self.elapsed_ms,
            tokens_in=self.total_tokens_in,
            tokens_out=self.total_tokens_out,
            cost_usd=self.total_cost_usd,
            agent_calls=self.agent_calls,
            experiments_run=self.experiments_run,
        )
