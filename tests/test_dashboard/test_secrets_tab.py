"""Settings -> Secrets tab + /api/secrets CRUD endpoints.

Phase B.1 of the secrets vault rollout. Covers:

* The new Secrets tab renders alongside the existing tabs.
* GET /api/secrets returns origin-tagged metadata + masked previews
  (never raw values).
* POST /api/secrets validates name format, rejects process-env
  overwrites, and round-trips set -> list.
* DELETE /api/secrets/<name> removes the entry, 404s on unknowns,
  and refuses to clear a process-env-only secret.
"""

from __future__ import annotations


# ---- Tab rendering ---------------------------------------------------------


def test_secrets_tab_renders_in_global_settings(settings_client, monkeypatch):
    """The Secrets tab appears alongside Privacy / Models / Preferences /
    Notifications, with the dashboard's tab macro structure."""
    body = settings_client.get("/settings").text
    # New tab button is present.
    assert ">Secrets</button>" in body
    # Tab structure (the panel uses x-show like the others).
    assert "active === 'secrets'" in body


def test_secrets_tab_shows_backend_label(settings_client):
    """The tab surfaces which backend is active (file vs OS keyring)."""
    body = settings_client.get("/settings").text
    assert "Storage backend" in body
    # Fallback wording when keyring isn't available; either label is fine
    # (the test box may or may not have keyring), but at least one of the
    # two known strings should render.
    assert (
        "file fallback (chmod 0600)" in body
        or "OS keyring" in body
    )


def test_secrets_tab_has_add_button(settings_client):
    body = settings_client.get("/settings").text
    assert "+ Add secret" in body


# ---- GET /api/secrets ------------------------------------------------------


def test_list_secrets_endpoint_returns_provider_plus_set(
    settings_client, monkeypatch, tmp_path
):
    """LLM provider rows always appear; vault-stored values surface
    with their storage-tier origin."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-value-with-enough-bytes")

    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    body = r.json()
    items = body["secrets"]
    by_name = {item["name"]: item for item in items}

    # Provider rows always render.
    assert "ANTHROPIC_API_KEY" in by_name
    assert by_name["ANTHROPIC_API_KEY"]["origin"] == "process"
    assert by_name["ANTHROPIC_API_KEY"]["set"] is True
    assert by_name["ANTHROPIC_API_KEY"]["category"] == "provider"
    assert "OPENAI_API_KEY" in by_name
    assert by_name["OPENAI_API_KEY"]["category"] == "provider"

    # Random KNOWN_SECRETS that aren't providers and aren't referenced
    # do NOT pre-render rows any more.
    assert "HUGGINGFACE_HUB_TOKEN" not in by_name


def test_list_secrets_returns_backend_label(settings_client, tmp_path, monkeypatch):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body
    assert isinstance(body["backend"], str)


# ---- POST /api/secrets -----------------------------------------------------


def test_post_secret_creates_with_metadata(settings_client, tmp_path, monkeypatch):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    r = settings_client.post(
        "/api/secrets",
        data={
            "name": "MY_TEST_KEY",
            "value": "secret-value-of-sufficient-length",
            "description": "test purposes",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["name"] == "MY_TEST_KEY"
    assert "***" in body["masked_preview"]


def test_post_secret_rejects_invalid_name_format(settings_client, tmp_path, monkeypatch):
    """Name must be uppercase letters / digits / underscores only."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    r = settings_client.post(
        "/api/secrets",
        data={"name": "lowercase-name", "value": "x"},
    )
    assert r.status_code == 400


def test_post_secret_rejects_missing_value(settings_client, tmp_path, monkeypatch):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    r = settings_client.post(
        "/api/secrets",
        data={"name": "MY_KEY", "value": ""},
    )
    assert r.status_code == 400


def test_post_secret_rejects_overwrite_of_process_env(
    settings_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROCESS_SET_KEY", "from-shell")

    r = settings_client.post(
        "/api/secrets",
        data={"name": "PROCESS_SET_KEY", "value": "from-dashboard"},
    )
    # Should refuse — process env wins anyway, so saving via vault is
    # misleading.
    assert r.status_code == 400
    body_text = r.text.lower()
    assert "shell" in body_text or "process" in body_text


def test_post_then_get_round_trip(settings_client, tmp_path, monkeypatch):
    """A saved secret appears in subsequent list responses."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    settings_client.post(
        "/api/secrets",
        data={"name": "ROUND_TRIP_KEY", "value": "round-trip-value-padding"},
    )
    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    by_name = {item["name"]: item for item in r.json()["secrets"]}
    assert "ROUND_TRIP_KEY" in by_name
    assert by_name["ROUND_TRIP_KEY"]["set"] is True


# ---- DELETE /api/secrets/<name> --------------------------------------------


def test_delete_secret_removes_from_vault(settings_client, tmp_path, monkeypatch):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    settings_client.post(
        "/api/secrets",
        data={"name": "TO_DELETE", "value": "delete-me-value-padding"},
    )
    r = settings_client.delete("/api/secrets/TO_DELETE")
    assert r.status_code == 204


def test_delete_secret_404_when_unknown(settings_client, tmp_path, monkeypatch):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    # Make sure the name isn't lurking in the test process env.
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    r = settings_client.delete("/api/secrets/DOES_NOT_EXIST")
    assert r.status_code == 404


def test_delete_secret_refuses_process_env(settings_client, monkeypatch, tmp_path):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROCESS_SECRET", "from-shell")
    r = settings_client.delete("/api/secrets/PROCESS_SECRET")
    assert r.status_code == 400
    assert "shell" in r.text.lower() or "process" in r.text.lower()


# ---- Defense in depth: values never returned ------------------------------


def test_list_secrets_does_not_leak_random_shell_env(
    settings_client, monkeypatch, tmp_path
):
    """Random shell exports must NOT appear in the Secrets list — only
    vault-stored, provider, or referenced names are candidates."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    # The kind of nonsense the user has in their shell.
    monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/local/lib")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("GTK_MODULES", "canberra-gtk-module")
    monkeypatch.setenv("RANDOM_SHELL_VAR_ABC", "garbage")

    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    names = {item["name"] for item in r.json()["secrets"]}
    for leak in (
        "LD_LIBRARY_PATH",
        "XDG_RUNTIME_DIR",
        "GTK_MODULES",
        "RANDOM_SHELL_VAR_ABC",
    ):
        assert leak not in names, f"{leak} leaked into the Secrets list"


def test_referenced_endpoint_secret_appears_under_used_by_config(
    settings_client, monkeypatch, tmp_path
):
    """An ``api_key_env`` reference on a privacy endpoint shows up
    under the "used_by_config" category with a referenced_by note.

    Uses a synthetic env-var name unlikely to exist anywhere on the
    test machine + isolates ``urika.core.secrets`` from the developer's
    real ``~/.urika/secrets.env`` (which load_secrets() reads from a
    module-level path that doesn't honor URIKA_HOME).
    """
    test_env_name = "URIKA_TEST_ONLY_XYZ_KEY_99"
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    # Stub load_secrets so the developer's real secrets.env can't
    # accidentally export the test name into os.environ.
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)
    monkeypatch.delenv(test_env_name, raising=False)
    (tmp_path / "home" / "settings.toml").write_text(
        f"[privacy.endpoints.test_vllm]\n"
        f'base_url = "http://example.com:4200"\n'
        f'api_key_env = "{test_env_name}"\n',
        encoding="utf-8",
    )

    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    by_name = {i["name"]: i for i in r.json()["secrets"]}
    assert test_env_name in by_name
    row = by_name[test_env_name]
    assert row["category"] == "used_by_config"
    assert "test_vllm" in row["referenced_by"]
    assert row["origin"] == "unset"


# ---- Three-section categorization + locked providers ----------------------


def test_secrets_tab_has_three_sections(settings_client):
    """The Secrets tab template renders three labelled sections."""
    body = settings_client.get("/settings").text
    assert "LLM Providers" in body
    assert "Used by your config" in body
    assert "Other Integrations" in body
    # The Alpine filter functions are wired up.
    assert "providerRows" in body
    assert "usedByConfigRows" in body
    assert "otherRows" in body


def test_locked_provider_row_marks_unavailable(settings_client, tmp_path, monkeypatch):
    """OPENAI_API_KEY / GOOGLE_API_KEY are flagged available=False so
    the template can render the 'coming v0.5' badge instead of action
    buttons."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    by_name = {item["name"]: item for item in r.json()["secrets"]}
    assert by_name["OPENAI_API_KEY"]["available"] is False
    assert by_name["GOOGLE_API_KEY"]["available"] is False
    assert by_name["ANTHROPIC_API_KEY"]["available"] is True


def test_post_secret_refuses_unavailable_provider_name(
    settings_client, monkeypatch, tmp_path
):
    """Saving a value for a locked provider returns 400 with a
    roadmap-aware message."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    r = settings_client.post(
        "/api/secrets",
        data={"name": "OPENAI_API_KEY", "value": "sk-fake-test-value-padding"},
    )
    assert r.status_code == 400
    body_text = r.text
    assert "OPENAI_API_KEY" in body_text or "OpenAI" in body_text
    assert "v0.5" in body_text


def test_used_by_config_row_shows_annotation(
    settings_client, monkeypatch, tmp_path
):
    """A referenced env-var carries a referenced_by annotation in the
    JSON payload that the template surfaces as ``↳ used by ...``."""
    test_env_name = "URIKA_TEST_REF_KEY_88"
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)
    monkeypatch.delenv(test_env_name, raising=False)
    (tmp_path / "home" / "settings.toml").write_text(
        f"[notifications.email]\n"
        f'from_addr = "x@y.com"\n'
        f"smtp_port = 587\n"
        f'password_env = "{test_env_name}"\n',
        encoding="utf-8",
    )
    r = settings_client.get("/api/secrets")
    by_name = {item["name"]: item for item in r.json()["secrets"]}
    assert test_env_name in by_name
    assert by_name[test_env_name]["category"] == "used_by_config"
    assert "email password" in by_name[test_env_name]["referenced_by"]


def test_paired_input_save_writes_value_to_vault(
    settings_client, monkeypatch, tmp_path
):
    """Saving the global settings form with a privacy-endpoint
    api_key_env + api_key_value pair writes the value to the vault
    under that name; no value lands in settings.toml."""
    import json

    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("TEST_VLLM_KEY", raising=False)

    payload = json.dumps(
        [
            {
                "name": "test_vllm",
                "base_url": "http://example.com:4200",
                "api_key_env": "TEST_VLLM_KEY",
                "api_key_value": "sk-test-12345-abcdef",
                "default_model": "qwen3:14b",
            }
        ]
    )
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints_json": payload,
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200, r.text

    # settings.toml should have the env-var NAME, not the value.
    settings_toml = (tmp_path / "home" / "settings.toml").read_text()
    assert "TEST_VLLM_KEY" in settings_toml
    assert "sk-test-12345-abcdef" not in settings_toml

    # The vault should have the value under the name.
    secrets_env = (tmp_path / "home" / "secrets.env").read_text()
    assert "TEST_VLLM_KEY=sk-test-12345-abcdef" in secrets_env


def test_paired_input_sentinel_does_not_overwrite_existing_vault_value(
    settings_client, monkeypatch, tmp_path
):
    """When the user submits ``********`` (the sentinel) the form
    treats it as 'no change' and the vault value stays."""
    import json

    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("TEST_KEEP_KEY", raising=False)

    # First, store an initial value via the secrets endpoint.
    r1 = settings_client.post(
        "/api/secrets",
        data={"name": "TEST_KEEP_KEY", "value": "original-stored-value-padding"},
    )
    assert r1.status_code == 200, r1.text

    # Now PUT settings with the sentinel — should NOT overwrite.
    payload = json.dumps(
        [
            {
                "name": "test_keep",
                "base_url": "http://example.com:4200",
                "api_key_env": "TEST_KEEP_KEY",
                "api_key_value": "********",
                "default_model": "qwen3:14b",
            }
        ]
    )
    r2 = settings_client.put(
        "/api/settings",
        data={
            "endpoints_json": payload,
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r2.status_code == 200, r2.text

    # Vault value unchanged.
    secrets_env = (tmp_path / "home" / "secrets.env").read_text()
    assert "TEST_KEEP_KEY=original-stored-value-padding" in secrets_env


def test_secret_value_never_returned_in_list(settings_client, tmp_path, monkeypatch):
    """The full value never round-trips through the list endpoint —
    only metadata + masked preview leaves the server."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    secret_value = "highly-secret-value-do-not-leak"
    settings_client.post(
        "/api/secrets",
        data={"name": "LEAK_TEST", "value": secret_value},
    )

    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    # The whole response body must not contain the raw value.
    assert secret_value not in r.text
    items = r.json()["secrets"]
    leak_test = next((i for i in items if i["name"] == "LEAK_TEST"), None)
    assert leak_test is not None
    assert secret_value not in leak_test["masked_preview"]
