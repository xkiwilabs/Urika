"""Tests for v0.4.2 C9 — per-project context_window / max_output_tokens.

Pre-v0.4.2 the global Settings page (``global_settings.html`` lines
247-269) had ``context_window`` and ``max_output_tokens`` form rows
on each endpoint, but the per-project Privacy tab template
(``project_settings.html``) did NOT. The per-project API parser at
``api.py:670-686`` also built endpoints inline with only
``base_url`` + ``api_key_env`` and silently dropped any v0.4.1
fields a user typed. These tests pin both halves of the fix.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def project_with_private_endpoint(
    tmp_path: Path, monkeypatch
) -> tuple[TestClient, Path]:
    """A dashboard pre-seeded with a private-mode project."""
    proj = tmp_path / "myproj"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "myproj"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[privacy]\n'
        'mode = "private"\n'
        '\n'
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = "OLLAMA_KEY"\n'
        'context_window = 65536\n'
        'max_output_tokens = 12000\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"myproj": str(proj)}))

    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


class TestProjectSettingsTemplateRendersFields:
    def test_template_includes_context_window_input(
        self, project_with_private_endpoint
    ) -> None:
        client, _ = project_with_private_endpoint
        resp = client.get("/projects/myproj/settings")
        assert resp.status_code == 200, resp.text
        # The new input must be in the rendered HTML for both Private
        # and Hybrid blocks.
        assert "project_privacy_private_context_window" in resp.text, (
            "Pre-v0.4.2 the template was missing this field even though "
            "the global settings page had it for v0.4.1."
        )
        assert "project_privacy_hybrid_private_context_window" in resp.text

    def test_template_includes_max_output_tokens_input(
        self, project_with_private_endpoint
    ) -> None:
        client, _ = project_with_private_endpoint
        resp = client.get("/projects/myproj/settings")
        assert resp.status_code == 200
        assert "project_privacy_private_max_output_tokens" in resp.text
        assert "project_privacy_hybrid_private_max_output_tokens" in resp.text

    def test_existing_values_are_preselected(
        self, project_with_private_endpoint
    ) -> None:
        """Saved values must round-trip back into the form so the user
        can see what's currently configured."""
        client, _ = project_with_private_endpoint
        resp = client.get("/projects/myproj/settings")
        # The seeded urika.toml has 65536 / 12000.
        assert "65536" in resp.text
        assert "12000" in resp.text


class TestProjectSettingsApiPersistsFields:
    def test_post_writes_context_window_to_toml(
        self, project_with_private_endpoint
    ) -> None:
        """v0.4.2 C9 fix: the per-project /settings PUT now reads the
        v0.4.1 endpoint fields from the form and writes them into
        ``[privacy.endpoints.private]``. Pre-fix the parser silently
        dropped them.
        """
        client, proj = project_with_private_endpoint

        resp = client.put(
            "/api/projects/myproj/settings",
            data={
                "question": "q",
                "description": "",
                "mode": "exploratory",
                "audience": "expert",
                "project_privacy_mode": "private",
                "project_privacy_private_url": "http://localhost:8080",
                "project_privacy_private_key_env": "MY_KEY",
                "project_privacy_private_context_window": "131072",
                "project_privacy_private_max_output_tokens": "16000",
            },
        )
        assert resp.status_code in (200, 204), resp.text

        toml_text = (proj / "urika.toml").read_text()
        data = tomllib.loads(toml_text)
        ep = data["privacy"]["endpoints"]["private"]
        assert ep["base_url"] == "http://localhost:8080"
        assert ep["context_window"] == 131072
        assert ep["max_output_tokens"] == 16000

    def test_blank_fields_are_not_written(
        self, project_with_private_endpoint
    ) -> None:
        """Blank or 0 means "use auto-default" — the parser must not
        write a 0 entry that overrides the URL-based default."""
        client, proj = project_with_private_endpoint

        resp = client.put(
            "/api/projects/myproj/settings",
            data={
                "question": "q",
                "description": "",
                "mode": "exploratory",
                "audience": "expert",
                "project_privacy_mode": "private",
                "project_privacy_private_url": "http://localhost:8080",
                "project_privacy_private_key_env": "",
                "project_privacy_private_context_window": "",
                "project_privacy_private_max_output_tokens": "",
            },
        )
        assert resp.status_code in (200, 204)

        data = tomllib.loads((proj / "urika.toml").read_text())
        ep = data["privacy"]["endpoints"]["private"]
        # base_url written; the optional fields should be absent.
        assert ep["base_url"] == "http://localhost:8080"
        assert "context_window" not in ep
        assert "max_output_tokens" not in ep

    def test_hybrid_endpoint_fields_persist(
        self, project_with_private_endpoint
    ) -> None:
        client, proj = project_with_private_endpoint

        resp = client.put(
            "/api/projects/myproj/settings",
            data={
                "question": "q",
                "description": "",
                "mode": "exploratory",
                "audience": "expert",
                "project_privacy_mode": "hybrid",
                "project_privacy_hybrid_cloud_model": "claude-opus-4-7",
                "project_privacy_hybrid_private_url": "http://localhost:9000",
                "project_privacy_hybrid_private_key_env": "HYB_KEY",
                "project_privacy_hybrid_private_context_window": "100000",
                "project_privacy_hybrid_private_max_output_tokens": "20000",
            },
        )
        assert resp.status_code in (200, 204)

        data = tomllib.loads((proj / "urika.toml").read_text())
        ep = data["privacy"]["endpoints"]["private"]
        assert ep["context_window"] == 100000
        assert ep["max_output_tokens"] == 20000
