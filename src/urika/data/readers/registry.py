"""Reader registry with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil

from urika.data.readers.base import IDataReader


class ReaderRegistry:
    """Registry for data readers with auto-discovery by extension."""

    def __init__(self) -> None:
        self._readers: dict[str, IDataReader] = {}
        self._extensions: dict[str, IDataReader] = {}

    def register(self, reader: IDataReader) -> None:
        """Register a reader, mapping all its extensions."""
        self._readers[reader.name()] = reader
        for ext in reader.supported_extensions():
            self._extensions[ext] = reader

    def get_by_extension(self, ext: str) -> IDataReader | None:
        """Get a reader by file extension, or None if unsupported."""
        return self._extensions.get(ext)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered reader names."""
        return sorted(self._readers.keys())

    def discover(self) -> None:
        """Auto-discover readers from readers/ submodules with get_reader()."""
        import urika.data.readers as readers_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(readers_pkg.__path__):
            if modname in ("base", "registry"):
                continue
            module = importlib.import_module(f"urika.data.readers.{modname}")
            get_reader = getattr(module, "get_reader", None)
            if callable(get_reader):
                reader = get_reader()
                if isinstance(reader, IDataReader):
                    self.register(reader)
