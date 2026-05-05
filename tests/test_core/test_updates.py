"""Tests for ``urika.core.updates`` version comparison.

Pre-v0.4.2 used a hand-rolled tuple parser that broke on PEP 440 pre-
releases (rc/dev/a/b suffixes). The fix delegates to
``packaging.version.Version`` which is PEP 440-compliant.
"""

from __future__ import annotations

import pytest

from urika.core.updates import _parse_version


class TestParseVersion:
    def test_simple_release(self) -> None:
        assert _parse_version("0.4.0") == _parse_version("0.4.0")

    def test_strips_v_prefix(self) -> None:
        assert _parse_version("v0.4.0") == _parse_version("0.4.0")

    def test_release_greater_than_rc(self) -> None:
        # Regression for v0.4.2 H4: pre-fix returned (0, 4) for rc and
        # (0, 4, 0) for the release, so rc compared LESS than release —
        # the same as PEP 440's contract — but only by accident. The
        # parser also returned (0, 4) for "0.4" which then equalled
        # "0.4.0rc1", giving wrong answers in the other direction.
        assert _parse_version("0.4.0") > _parse_version("0.4.0rc1")
        assert _parse_version("0.4.0") > _parse_version("0.4.0a1")
        assert _parse_version("0.4.0") > _parse_version("0.4.0b2")

    def test_rc_greater_than_dev(self) -> None:
        assert _parse_version("0.4.0rc1") > _parse_version("0.4.0.dev0")

    def test_minor_bump_greater_than_dev(self) -> None:
        assert _parse_version("0.4.1") > _parse_version("0.4.0")
        assert _parse_version("0.4.1") > _parse_version("0.4.0.dev0")

    def test_pre_release_ordering(self) -> None:
        assert _parse_version("0.5.0a1") < _parse_version("0.5.0a2")
        assert _parse_version("0.5.0a2") < _parse_version("0.5.0b1")
        assert _parse_version("0.5.0b1") < _parse_version("0.5.0rc1")
        assert _parse_version("0.5.0rc1") < _parse_version("0.5.0")

    def test_garbage_input_returns_zero_baseline(self) -> None:
        # Update checks must never crash the CLI on a malformed tag.
        zero = _parse_version("0.0.0")
        assert _parse_version("not-a-version") == zero
        assert _parse_version("") == zero
        assert _parse_version("v") == zero


class TestUpdateBannerComparison:
    """Spot-check the comparison the banner code actually performs."""

    @pytest.mark.parametrize(
        "current,latest,update_expected",
        [
            ("0.4.0", "0.4.1", True),
            ("0.4.1", "0.4.0", False),
            ("0.4.0", "0.4.0", False),
            ("0.4.0.dev0", "0.4.0", True),
            ("0.4.0rc1", "0.4.0", True),
            ("0.4.0", "0.4.0rc1", False),
            ("0.5.0a1", "0.5.0", True),
        ],
    )
    def test_update_available_logic(
        self, current: str, latest: str, update_expected: bool
    ) -> None:
        assert (_parse_version(latest) > _parse_version(current)) is update_expected
