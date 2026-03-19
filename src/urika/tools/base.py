"""Base tool interface and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.data.models import DatasetView


@dataclass
class ToolResult:
    """What a tool execution produced."""

    outputs: dict[str, Any]
    artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    valid: bool = True
    error: str | None = None


class ITool(ABC):
    """Interface for all analysis tools."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this tool."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description."""
        ...

    @abstractmethod
    def category(self) -> str:
        """Return the tool category (e.g. 'exploration', 'statistical')."""
        ...

    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """Return default parameters for this tool."""
        ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        """Run the tool on data with given parameters."""
        ...
