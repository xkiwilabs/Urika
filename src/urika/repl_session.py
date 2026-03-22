"""REPL session state — project context and advisor conversation."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReplSession:
    """Manages state for an interactive REPL session."""

    project_path: Path | None = None
    project_name: str | None = None
    conversation: list[dict[str, str]] = field(default_factory=list)

    @property
    def has_project(self) -> bool:
        return self.project_path is not None

    def load_project(self, path: Path, name: str) -> None:
        self.project_path = path
        self.project_name = name
        self.conversation = []

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
