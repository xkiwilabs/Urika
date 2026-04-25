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
