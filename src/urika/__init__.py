"""Urika: Agentic scientific analysis platform."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("urika")
except PackageNotFoundError:
    __version__ = "0.1.0"  # Fallback for development
