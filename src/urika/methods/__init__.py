"""Analysis method infrastructure."""

from urika.methods.base import IAnalysisMethod, MethodResult
from urika.methods.registry import MethodRegistry

__all__ = ["IAnalysisMethod", "MethodRegistry", "MethodResult"]
