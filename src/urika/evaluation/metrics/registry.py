"""Metric registry with auto-discovery."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from urika.evaluation.metrics.base import IMetric


class MetricRegistry:
    """Registry for evaluation metrics with auto-discovery."""

    def __init__(self) -> None:
        self._metrics: dict[str, IMetric] = {}

    def register(self, metric: IMetric) -> None:
        """Register a metric instance by its name."""
        self._metrics[metric.name()] = metric

    def get(self, name: str) -> IMetric | None:
        """Get a metric by name, or None if not found."""
        return self._metrics.get(name)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered metric names."""
        return sorted(self._metrics.keys())

    def discover(self) -> None:
        """Auto-discover and register all IMetric subclasses in metrics submodules."""
        import urika.evaluation.metrics as metrics_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(metrics_pkg.__path__):
            if modname in ("base", "registry"):
                continue
            module = importlib.import_module(f"urika.evaluation.metrics.{modname}")
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, IMetric) and obj is not IMetric:
                    instance = obj()
                    self._metrics[instance.name()] = instance
