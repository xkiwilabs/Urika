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


def test_list_secrets_endpoint_returns_known_plus_set(
    settings_client, monkeypatch, tmp_path
):
    """Known + set secrets surface with their origin badges."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-value-with-enough-bytes")

    r = settings_client.get("/api/secrets")
    assert r.status_code == 200
    body = r.json()
    items = body["secrets"]
    by_name = {item["name"]: item for item in items}

    # Known + set: ANTHROPIC_API_KEY should appear with origin=process.
    assert "ANTHROPIC_API_KEY" in by_name
    assert by_name["ANTHROPIC_API_KEY"]["origin"] == "process"
    assert by_name["ANTHROPIC_API_KEY"]["set"] is True

    # Known + unset: HUGGINGFACE_HUB_TOKEN should appear with origin=unset
    # (assuming the test env doesn't already export it).
    if "HUGGINGFACE_HUB_TOKEN" not in __import__("os").environ:
        assert "HUGGINGFACE_HUB_TOKEN" in by_name
        assert by_name["HUGGINGFACE_HUB_TOKEN"]["origin"] == "unset"


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
