"""Base method interface and result type.

A method is a complete analytical pipeline — the core output of the agent
system.  Methods combine multiple tools into an end-to-end workflow
(preprocessing, modelling, evaluation) and are created by agents, not
shipped as built-ins.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.data.models import DatasetView


@dataclass
class MethodResult:
    """What a method pipeline produced."""

    metrics: dict[str, float]
    artifacts: list[str] = field(default_factory=list)
    valid: bool = True
    error: str | None = None


class IMethod(ABC):
    """Interface for agent-created analytical pipelines.

    Unlike tools (individual building blocks), a method represents a
    complete analysis pipeline: data preparation, feature engineering,
    model fitting, hyperparameter tuning, and evaluation.
    """

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this method."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of the pipeline."""
        ...

    @abstractmethod
    def tools_used(self) -> list[str]:
        """Return names of tools this method uses."""
        ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        """Execute the full pipeline on data with given parameters."""
        ...
