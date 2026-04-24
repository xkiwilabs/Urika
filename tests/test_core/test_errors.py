"""Tests for the typed-error hierarchy in urika.core.errors."""

from __future__ import annotations

import pytest

from urika.core.errors import (
    AgentError,
    ConfigError,
    UrikaError,
    ValidationError,
)


class TestHierarchy:
    def test_urika_error_is_the_base(self) -> None:
        assert issubclass(ConfigError, UrikaError)
        assert issubclass(AgentError, UrikaError)
        assert issubclass(ValidationError, UrikaError)

    def test_urika_error_is_exception(self) -> None:
        assert issubclass(UrikaError, Exception)

    def test_subclasses_can_be_raised_and_caught_as_urika_error(self) -> None:
        for cls in (ConfigError, AgentError, ValidationError):
            try:
                raise cls("boom")
            except UrikaError as exc:
                assert isinstance(exc, cls)


class TestMessageAndHint:
    def test_message_is_str_of_exception(self) -> None:
        err = ConfigError("project file missing")
        assert "project file missing" in str(err)

    def test_hint_defaults_to_none(self) -> None:
        err = ConfigError("msg")
        assert err.hint is None

    def test_hint_is_accessible_attribute(self) -> None:
        err = ConfigError("project file missing", hint="Run `urika new` first.")
        assert err.hint == "Run `urika new` first."

    def test_hint_is_keyword_only(self) -> None:
        # Positional second arg should fail — hint must be passed by keyword.
        with pytest.raises(TypeError):
            ConfigError("msg", "hint as positional")  # type: ignore[misc]


class TestSubclassSpecifics:
    """Subclasses exist for pattern-matching in except-blocks; they carry no
    extra behavior. These tests document that contract so we don't
    accidentally sprout subclass-specific features."""

    @pytest.mark.parametrize(
        "cls",
        [ConfigError, AgentError, ValidationError],
    )
    def test_subclasses_behave_identically(self, cls: type[UrikaError]) -> None:
        err = cls("msg", hint="hint")
        assert isinstance(err, UrikaError)
        assert str(err) == "msg" or "msg" in str(err)
        assert err.hint == "hint"
