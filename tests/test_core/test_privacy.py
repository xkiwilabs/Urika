"""Tests for privacy endpoint check utility."""


from urika.core.privacy import check_private_endpoint, requires_private_endpoint


class TestPrivacyCheck:
    def test_open_mode_always_ok(self, tmp_path):
        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "open"\n'
        )
        ok, msg = check_private_endpoint(tmp_path)
        assert ok is True

    def test_hybrid_no_endpoint_fails(self, tmp_path):
        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "hybrid"\n'
        )
        ok, msg = check_private_endpoint(tmp_path)
        assert ok is False
        assert "No private endpoint" in msg

    def test_hybrid_unreachable_fails(self, tmp_path):
        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "hybrid"\n\n'
            '[privacy.endpoints.private]\nbase_url = "http://127.0.0.1:99999"\n'
        )
        ok, msg = check_private_endpoint(tmp_path)
        assert ok is False
        assert "unreachable" in msg.lower()

    def test_requires_private_open(self, tmp_path):
        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "open"\n'
        )
        assert requires_private_endpoint(tmp_path) is False

    def test_requires_private_hybrid(self, tmp_path):
        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "hybrid"\n'
        )
        assert requires_private_endpoint(tmp_path) is True

    def test_no_toml(self, tmp_path):
        ok, msg = check_private_endpoint(tmp_path)
        assert ok is True
        assert requires_private_endpoint(tmp_path) is False

    def test_corrupt_toml_fails_closed(self, tmp_path):
        # Pre-v0.4.2 a corrupt urika.toml was caught by a bare
        # ``except Exception: return True, ""`` and silently treated
        # as open mode — defeating the privacy guard.
        (tmp_path / "urika.toml").write_text("not = valid = toml = at all\n")
        ok, msg = check_private_endpoint(tmp_path)
        assert ok is False
        assert "corrupt" in msg.lower() or "cannot read" in msg.lower()

    def test_corrupt_toml_requires_private(self, tmp_path):
        # Companion to above: the dual-purpose check that decides
        # whether the project NEEDS a private endpoint must also
        # fail closed on parse error.
        (tmp_path / "urika.toml").write_text("[[[broken")
        assert requires_private_endpoint(tmp_path) is True

    def test_hybrid_sends_bearer_token_when_api_key_env_set(
        self, tmp_path, monkeypatch
    ):
        """Regression: auth-protected private endpoints must receive the
        configured bearer token.

        Before this fix, the preflight built ``Request(test_url, method='GET')``
        with no Authorization header, so a vLLM / Ollama / LiteLLM behind an
        API key would 401, urlopen would raise URLError, and the gate would
        report "Local model unreachable" — even though the endpoint was
        running and the agent runtime had the right key. Reported by Cathy
        on Windows; same bug applied to all platforms.
        """
        from unittest.mock import patch, MagicMock
        import urllib.request

        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "hybrid"\n\n'
            '[privacy.endpoints.private]\n'
            'base_url = "http://localhost:4200"\n'
            'api_key_env = "PRIVATE_VLLM_KEY"\n'
        )
        monkeypatch.setenv("PRIVATE_VLLM_KEY", "sk-test-vllm-token")
        # Stub load_secrets so it doesn't pull from real ~/.urika/secrets.env
        monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

        # Capture what Request was called with
        captured: dict = {}

        original_request = urllib.request.Request

        def capturing_request(*args, **kwargs):
            req = original_request(*args, **kwargs)
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            return req

        with patch("urllib.request.Request", side_effect=capturing_request), \
             patch("urllib.request.urlopen", return_value=MagicMock()):
            ok, msg = check_private_endpoint(tmp_path)

        assert ok is True
        # The Authorization header MUST be present with the bearer prefix.
        # urllib normalises header keys via title-case (Authorization).
        auth = captured["headers"].get("Authorization", "")
        assert auth == "Bearer sk-test-vllm-token", (
            f"expected 'Bearer sk-test-vllm-token', got {auth!r}"
        )

    def test_hybrid_no_auth_header_when_api_key_env_blank(
        self, tmp_path, monkeypatch
    ):
        """No api_key_env configured → no Authorization header sent.

        Open / unauthenticated private endpoints (Ollama with default config)
        should still work without any token wiring.
        """
        from unittest.mock import patch, MagicMock
        import urllib.request

        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "hybrid"\n\n'
            '[privacy.endpoints.private]\nbase_url = "http://localhost:11434"\n'
        )

        captured: dict = {}
        original_request = urllib.request.Request

        def capturing_request(*args, **kwargs):
            req = original_request(*args, **kwargs)
            captured["headers"] = dict(req.header_items())
            return req

        with patch("urllib.request.Request", side_effect=capturing_request), \
             patch("urllib.request.urlopen", return_value=MagicMock()):
            ok, msg = check_private_endpoint(tmp_path)

        assert ok is True
        assert "Authorization" not in captured["headers"]

    def test_hybrid_no_auth_header_when_env_var_unset(
        self, tmp_path, monkeypatch
    ):
        """api_key_env names a var that's not set → no Authorization header.

        The endpoint will return 401 anyway, but at least we don't send a
        bogus / empty bearer token. Lets the endpoint's own error get
        through (which is the standard 'unreachable' result on auth fail).
        """
        from unittest.mock import patch, MagicMock
        import urllib.request

        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "test"\nquestion = "q"\nmode = "exploratory"\n\n'
            '[privacy]\nmode = "hybrid"\n\n'
            '[privacy.endpoints.private]\n'
            'base_url = "http://localhost:4200"\n'
            'api_key_env = "DEFINITELY_NOT_SET"\n'
        )
        monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
        monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

        captured: dict = {}
        original_request = urllib.request.Request

        def capturing_request(*args, **kwargs):
            req = original_request(*args, **kwargs)
            captured["headers"] = dict(req.header_items())
            return req

        with patch("urllib.request.Request", side_effect=capturing_request), \
             patch("urllib.request.urlopen", return_value=MagicMock()):
            ok, msg = check_private_endpoint(tmp_path)

        assert "Authorization" not in captured["headers"]
