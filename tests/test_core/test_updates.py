"""Tests for ``urika.core.updates`` — version parsing, cache I/O, GitHub
Releases JSON parsing, network-failure tolerance, banner formatting.

Pre-v0.4.2 used a hand-rolled tuple parser that broke on PEP 440 pre-
releases (rc/dev/a/b suffixes). The fix delegates to
``packaging.version.Version`` which is PEP 440-compliant. Beyond that
regression, the module has cache-file I/O, urllib-driven release
fetching (with a tags-endpoint fallback), and a banner formatter — all
previously untested. Failures in any of these would silently break the
update-banner contract: never crash the CLI on a malformed tag, a
broken cache, or a network error.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from urika.core import updates
from urika.core.updates import (
    _fetch_latest_release,
    _installed_version,
    _load_cache,
    _parse_version,
    _save_cache,
    _strip_v_prefix,
    check_for_updates,
    format_update_message,
)


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


# ── _installed_version ─────────────────────────────────────────────


class TestInstalledVersion:
    def test_returns_string(self) -> None:
        """When ``urika`` is installed, returns its version string."""
        v = _installed_version()
        assert isinstance(v, str)
        assert v  # non-empty

    def test_fallback_when_metadata_unavailable(self, monkeypatch) -> None:
        """If importlib.metadata.version raises (e.g. urika not on path),
        returns the safe ``0.0.0`` baseline rather than crashing."""
        import importlib.metadata

        def _raise(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError("urika")

        monkeypatch.setattr(importlib.metadata, "version", _raise)
        assert _installed_version() == "0.0.0"


# ── _strip_v_prefix ────────────────────────────────────────────────


class TestStripVPrefix:
    def test_strips_leading_v(self) -> None:
        assert _strip_v_prefix("v0.3.0") == "0.3.0"
        assert _strip_v_prefix("v1.2.3rc1") == "1.2.3rc1"

    def test_passthrough_when_no_prefix(self) -> None:
        assert _strip_v_prefix("0.3.0") == "0.3.0"
        assert _strip_v_prefix("") == ""

    def test_does_not_strip_v_in_middle(self) -> None:
        """Only the *leading* ``v`` is stripped — embedded ``v`` is kept."""
        assert _strip_v_prefix("1.0v2") == "1.0v2"


# ── _load_cache / _save_cache ──────────────────────────────────────


class TestCacheRoundTrip:
    @pytest.fixture(autouse=True)
    def _redirect_cache(self, tmp_path: Path, monkeypatch) -> None:
        """Point cache dir/file at tmp_path so tests don't touch the
        real ``~/.urika/update_cache.json``."""
        cache_dir = tmp_path / ".urika"
        monkeypatch.setattr(updates, "_CACHE_DIR", cache_dir)
        monkeypatch.setattr(updates, "_CACHE_FILE", cache_dir / "update_cache.json")

    def test_empty_when_no_cache_file(self) -> None:
        assert _load_cache() == {}

    def test_round_trip(self) -> None:
        payload = {
            "latest": "v0.5.0",
            "current": "0.4.0",
            "update_available": True,
            "checked_at": 12345.6,
        }
        _save_cache(payload)
        loaded = _load_cache()
        assert loaded == payload

    def test_corrupt_cache_returns_empty_dict(self, tmp_path: Path) -> None:
        """A corrupt cache file must not crash the CLI — load returns
        ``{}`` rather than propagating the JSON decode error."""
        updates._CACHE_DIR.mkdir(parents=True, exist_ok=True)
        updates._CACHE_FILE.write_text("not json {{", encoding="utf-8")
        assert _load_cache() == {}

    def test_save_creates_parent_directory(self) -> None:
        """``_CACHE_DIR`` may not exist on a fresh install — save
        creates it via ``mkdir(parents=True, exist_ok=True)``."""
        assert not updates._CACHE_DIR.exists()
        _save_cache({"x": 1})
        assert updates._CACHE_FILE.exists()

    def test_save_swallows_oserror(self, monkeypatch) -> None:
        """If the cache write fails (read-only fs, permission denied),
        ``_save_cache`` must swallow the error so the CLI keeps going."""

        def _raise(_self, *_a, **_k):
            raise OSError("EROFS")

        monkeypatch.setattr(Path, "write_text", _raise)
        # Must not raise.
        _save_cache({"x": 1})


# ── check_for_updates — cache + fetch interaction ──────────────────


class TestCheckForUpdates:
    @pytest.fixture(autouse=True)
    def _redirect_cache(self, tmp_path: Path, monkeypatch) -> None:
        cache_dir = tmp_path / ".urika"
        monkeypatch.setattr(updates, "_CACHE_DIR", cache_dir)
        monkeypatch.setattr(updates, "_CACHE_FILE", cache_dir / "update_cache.json")

    def test_uses_cache_when_fresh(self, monkeypatch) -> None:
        """A cache file <24h old short-circuits the fetch."""
        _save_cache(
            {
                "latest": "v0.9.0",
                "current": "0.4.0",
                "update_available": True,
                "checked_at": time.time(),  # right now
            }
        )

        def _should_not_fetch() -> str | None:  # pragma: no cover
            raise AssertionError("fetch should not be called when cache fresh")

        monkeypatch.setattr(updates, "_fetch_latest_release", _should_not_fetch)
        out = check_for_updates()
        assert out is not None
        assert out["latest"] == "v0.9.0"
        assert out["update_available"] is True

    def test_cache_says_no_update_returns_none(self, monkeypatch) -> None:
        _save_cache(
            {
                "latest": "v0.4.0",
                "current": "0.4.0",
                "update_available": False,
                "checked_at": time.time(),
            }
        )
        monkeypatch.setattr(
            updates,
            "_fetch_latest_release",
            lambda: (_ for _ in ()).throw(  # pragma: no cover
                AssertionError("should not fetch")
            ),
        )
        assert check_for_updates() is None

    def test_stale_cache_triggers_fetch(self, monkeypatch) -> None:
        """A cache file >24h old does NOT short-circuit — fetch runs."""
        _save_cache(
            {
                "latest": "v0.4.0",
                "current": "0.4.0",
                "update_available": False,
                "checked_at": time.time() - 90000,  # > 24h ago
            }
        )
        monkeypatch.setattr(updates, "_fetch_latest_release", lambda: "v0.5.0")
        monkeypatch.setattr(updates, "_installed_version", lambda: "0.4.0")
        out = check_for_updates()
        assert out is not None
        assert out["latest"] == "v0.5.0"
        assert out["update_available"] is True

    def test_force_bypasses_cache(self, monkeypatch) -> None:
        _save_cache(
            {
                "latest": "v0.4.0",
                "current": "0.4.0",
                "update_available": False,
                "checked_at": time.time(),
            }
        )
        called: list[bool] = []

        def _fake_fetch() -> str:
            called.append(True)
            return "v0.6.0"

        monkeypatch.setattr(updates, "_fetch_latest_release", _fake_fetch)
        monkeypatch.setattr(updates, "_installed_version", lambda: "0.4.0")
        out = check_for_updates(force=True)
        assert called == [True]
        assert out is not None
        assert out["latest"] == "v0.6.0"

    def test_fetch_returns_none_returns_none(self, monkeypatch) -> None:
        """When the network fetch fails (returns None), the function
        propagates a clean ``None`` rather than crashing or writing a
        corrupt cache entry."""
        monkeypatch.setattr(updates, "_fetch_latest_release", lambda: None)
        assert check_for_updates(force=True) is None

    def test_no_update_when_versions_equal(self, monkeypatch) -> None:
        monkeypatch.setattr(updates, "_installed_version", lambda: "0.4.0")
        monkeypatch.setattr(updates, "_fetch_latest_release", lambda: "v0.4.0")
        assert check_for_updates(force=True) is None

    def test_no_update_when_local_is_newer(self, monkeypatch) -> None:
        """Local dev install can be newer than the latest released tag."""
        monkeypatch.setattr(updates, "_installed_version", lambda: "0.9.0")
        monkeypatch.setattr(updates, "_fetch_latest_release", lambda: "v0.5.0")
        assert check_for_updates(force=True) is None

    def test_writes_cache_after_successful_check(self, monkeypatch) -> None:
        monkeypatch.setattr(updates, "_installed_version", lambda: "0.4.0")
        monkeypatch.setattr(updates, "_fetch_latest_release", lambda: "v0.5.0")
        check_for_updates(force=True)
        cache = _load_cache()
        assert cache["latest"] == "v0.5.0"
        assert cache["update_available"] is True
        assert cache["checked_at"] > 0


# ── _fetch_latest_release — urllib mocking ─────────────────────────


class TestFetchLatestRelease:
    def test_returns_tag_name_on_success(self) -> None:
        body = json.dumps({"tag_name": "v0.4.5"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda *_a: None
        with patch("urllib.request.urlopen", return_value=resp):
            assert _fetch_latest_release() == "v0.4.5"

    def test_falls_back_to_tags_endpoint_on_release_failure(self) -> None:
        """If ``/releases/latest`` errors, the function tries
        ``/tags?per_page=1`` and returns the first tag's ``name``."""
        import urllib.error

        tags_body = json.dumps([{"name": "v0.3.9"}]).encode()
        tags_resp = MagicMock()
        tags_resp.read.return_value = tags_body
        tags_resp.__enter__ = lambda self: self
        tags_resp.__exit__ = lambda *_a: None

        call_count = [0]

        def _urlopen(req, *_a, **_k):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.URLError("releases 404")
            return tags_resp

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            assert _fetch_latest_release() == "v0.3.9"

    def test_returns_none_when_both_endpoints_fail(self) -> None:
        import urllib.error

        def _always_fail(*_a, **_k):
            raise urllib.error.URLError("offline")

        with patch("urllib.request.urlopen", side_effect=_always_fail):
            assert _fetch_latest_release() is None

    def test_returns_none_when_tags_response_is_empty_list(self) -> None:
        """``/tags`` returning ``[]`` (a brand-new repo) should yield
        ``None`` rather than IndexError."""
        import urllib.error

        empty_resp = MagicMock()
        empty_resp.read.return_value = b"[]"
        empty_resp.__enter__ = lambda self: self
        empty_resp.__exit__ = lambda *_a: None

        call_count = [0]

        def _urlopen(req, *_a, **_k):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.URLError("releases 404")
            return empty_resp

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            assert _fetch_latest_release() is None

    def test_returns_empty_string_when_tag_name_missing(self) -> None:
        """``data.get("tag_name", "")`` returns ``""`` (not None) when
        the field is absent — pin that contract so callers don't see a
        sudden type change."""
        body = json.dumps({"name": "no tag here"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda *_a: None
        with patch("urllib.request.urlopen", return_value=resp):
            assert _fetch_latest_release() == ""

    def test_swallows_json_decode_error_and_falls_back(self) -> None:
        """A 200 with garbage body triggers the tags-endpoint fallback."""
        bad_resp = MagicMock()
        bad_resp.read.return_value = b"not json {{"
        bad_resp.__enter__ = lambda self: self
        bad_resp.__exit__ = lambda *_a: None

        tags_resp = MagicMock()
        tags_resp.read.return_value = json.dumps([{"name": "v0.1.0"}]).encode()
        tags_resp.__enter__ = lambda self: self
        tags_resp.__exit__ = lambda *_a: None

        call_count = [0]

        def _urlopen(req, *_a, **_k):
            call_count[0] += 1
            return bad_resp if call_count[0] == 1 else tags_resp

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            assert _fetch_latest_release() == "v0.1.0"

    def test_sends_user_agent_and_accept_headers(self) -> None:
        """GitHub rate-limits unidentified clients — pin the headers."""
        body = json.dumps({"tag_name": "v0.4.0"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda *_a: None

        captured: list = []

        def _urlopen(req, *_a, **_k):
            captured.append(req)
            return resp

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            _fetch_latest_release()

        assert captured, "urlopen was not called"
        req = captured[0]
        # urllib Request stores headers case-folded with the first
        # letter upper.
        ua = req.get_header("User-agent")
        accept = req.get_header("Accept")
        assert "urika" in (ua or "").lower()
        assert "application/vnd.github" in (accept or "")


# ── format_update_message ──────────────────────────────────────────


class TestFormatUpdateMessage:
    def test_renders_versions_with_v_prefix(self) -> None:
        msg = format_update_message(
            {"current": "0.4.0", "latest": "v0.5.0", "update_available": True}
        )
        assert "v0.4.0" in msg
        assert "v0.5.0" in msg
        assert "Update available" in msg

    def test_strips_double_v(self) -> None:
        """Both current and latest are normalized — even if caller
        passed ``v`` already, output has exactly one ``v`` per version."""
        msg = format_update_message(
            {"current": "v0.4.0", "latest": "v0.5.0", "update_available": True}
        )
        # No "vv" anywhere.
        assert "vv" not in msg

    def test_includes_install_hint(self) -> None:
        msg = format_update_message(
            {"current": "0.1.0", "latest": "v0.2.0", "update_available": True}
        )
        assert "git pull" in msg or "pip install" in msg

    def test_handles_missing_keys_gracefully(self) -> None:
        """info.get(..., "") returns "" — the formatter must not crash
        on partial cache entries (e.g. shape changes across versions)."""
        msg = format_update_message({})
        # No keyerror, no None — just an emptyish message.
        assert isinstance(msg, str)
