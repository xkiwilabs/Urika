"""Tests for methods package public API."""

from __future__ import annotations


class TestPublicAPI:
    """Test that key types are importable from urika.methods."""

    def test_import_method(self) -> None:
        from urika.methods import IMethod

        assert IMethod is not None

    def test_import_method_result(self) -> None:
        from urika.methods import MethodResult

        assert MethodResult is not None

    def test_import_method_registry(self) -> None:
        from urika.methods import MethodRegistry

        assert MethodRegistry is not None
