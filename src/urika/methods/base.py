"""Base method interface and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.data.models import DatasetView


@dataclass
class MethodResult:
    """What a method run produced."""

    metrics: dict[str, float]
    artifacts: list[str] = field(default_factory=list)
    valid: bool = True
    error: str | None = None


class IAnalysisMethod(ABC):
    """Interface for all analysis methods."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this method."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description."""
        ...

    @abstractmethod
    def category(self) -> str:
        """Return the method category (e.g. 'regression', 'classification')."""
        ...

    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """Return default parameters for this method."""
        ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        """Run the method on data with given parameters."""
        ...
