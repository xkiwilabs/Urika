"""Project Settings -> Secrets tab + /api/projects/<n>/secrets CRUD.

Phase B.2 of the secrets vault rollout. Mirrors the global tab from
B.1 but writes to ``<project>/.urika/secrets.env`` (chmod 0600). The
project list endpoint surfaces the union of project-tier + global-tier
credentials so the user sees the full effective set for the project.
"""

from __future__ import annotations

from pathlib import Path

from urika.core.vault import _read_env_file


# ---- Tab rendering ---------------------------------------------------------


def test_project_secrets_tab_renders(client_with_projects):
    """The Secrets tab appears alongside Basics / Data / Privacy /
    Models / Notifications on the project settings page."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert ">Secrets</button>" in body
    assert "active === 'secrets'" in body


def test_project_secrets_tab_has_add_button(client_with_projects):
    body = client_with_projects.get("/projects/alpha/settings").text
    assert "+ Add project secret" in body


# ---- GET /api/projects/<n>/secrets ----------------------------------------


def test_list_project_secrets_includes_global_tier(
    client_with_projects, monkeypatch, tmp_path
):
    """The project list shows global-tier secrets too (with their
    origin badge), so users see the full effective set."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    # Save a global secret first.
    client_with_projects.post(
        "/api/secrets",
        data={"name": "GLOBAL_ONLY_KEY", "value": "global-value-for-the-test"},
    )

    r = client_with_projects.get("/api/projects/alpha/secrets")
    assert r.status_code == 200, r.text
    items = r.json()["secrets"]
    by_name = {item["name"]: item for item in items}
    assert "GLOBAL_ONLY_KEY" in by_name
    # Global value visible from project view, with the global origin tag.
    assert by_name["GLOBAL_ONLY_KEY"]["origin"] == "global"
    assert by_name["GLOBAL_ONLY_KEY"]["set"] is True


def test_list_project_secrets_404_for_unknown_project(client_with_projects):
    r = client_with_projects.get("/api/projects/does-not-exist/secrets")
    assert r.status_code == 404


# ---- POST /api/projects/<n>/secrets ---------------------------------------


def test_post_project_secret_saves_to_project_dir(
    client_with_projects, monkeypatch, tmp_path
):
    """Saving a project secret writes to <project>/.urika/secrets.env."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("PROJECT_KEY", raising=False)

    r = client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={
            "name": "PROJECT_KEY",
            "value": "project-only-value-padding",
            "description": "alpha-project test",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["name"] == "PROJECT_KEY"
    assert body["origin"] == "project"
    assert "***" in body["masked_preview"]

    # File side-effect: <project>/.urika/secrets.env contains the entry.
    proj_secrets = tmp_path / "alpha" / ".urika" / "secrets.env"
    assert proj_secrets.exists()
    values = _read_env_file(proj_secrets)
    assert values.get("PROJECT_KEY") == "project-only-value-padding"


def test_post_project_secret_rejects_invalid_name(
    client_with_projects, monkeypatch, tmp_path
):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    r = client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={"name": "lower-case", "value": "x"},
    )
    assert r.status_code == 400


def test_post_project_secret_rejects_process_env_overwrite(
    client_with_projects, monkeypatch, tmp_path
):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROJECT_PROCESS_KEY", "from-shell")

    r = client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={"name": "PROJECT_PROCESS_KEY", "value": "from-dashboard"},
    )
    assert r.status_code == 400


def test_post_project_secret_404_for_unknown_project(client_with_projects):
    r = client_with_projects.post(
        "/api/projects/missing/secrets",
        data={"name": "X", "value": "y"},
    )
    assert r.status_code == 404


# ---- Override-from-global flow --------------------------------------------


def test_project_secret_overrides_global_for_same_name(
    client_with_projects, monkeypatch, tmp_path
):
    """When a name has both a global and project entry, the project
    value wins (vault.get returns project)."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("OVERRIDE_KEY", raising=False)

    # Save global first.
    client_with_projects.post(
        "/api/secrets",
        data={"name": "OVERRIDE_KEY", "value": "global-value-padding-here"},
    )
    # Then project override.
    client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={"name": "OVERRIDE_KEY", "value": "project-value-padding-here"},
    )

    # Project list shows the row with origin=project.
    r = client_with_projects.get("/api/projects/alpha/secrets")
    by_name = {item["name"]: item for item in r.json()["secrets"]}
    assert by_name["OVERRIDE_KEY"]["origin"] == "project"


# ---- DELETE /api/projects/<n>/secrets/<name> ------------------------------


def test_delete_project_secret_falls_back_to_global(
    client_with_projects, monkeypatch, tmp_path
):
    """Deleting a project secret leaves the global value intact —
    subsequent reads see the global one again."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("FALLBACK_KEY", raising=False)

    client_with_projects.post(
        "/api/secrets",
        data={"name": "FALLBACK_KEY", "value": "global-value-for-fallback"},
    )
    client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={"name": "FALLBACK_KEY", "value": "project-override-for-fallback"},
    )

    r = client_with_projects.delete("/api/projects/alpha/secrets/FALLBACK_KEY")
    assert r.status_code == 204

    # Project file no longer carries the entry.
    proj_secrets = tmp_path / "alpha" / ".urika" / "secrets.env"
    if proj_secrets.exists():
        values = _read_env_file(proj_secrets)
        assert "FALLBACK_KEY" not in values

    # The global tier is still effective — visible in the project list
    # with origin=global.
    r = client_with_projects.get("/api/projects/alpha/secrets")
    by_name = {item["name"]: item for item in r.json()["secrets"]}
    assert "FALLBACK_KEY" in by_name
    assert by_name["FALLBACK_KEY"]["origin"] == "global"


def test_delete_project_secret_404_when_no_project_entry(
    client_with_projects, monkeypatch, tmp_path
):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("NO_PROJECT_ENTRY", raising=False)
    r = client_with_projects.delete("/api/projects/alpha/secrets/NO_PROJECT_ENTRY")
    assert r.status_code == 404


def test_delete_project_secret_refuses_process_env(
    client_with_projects, monkeypatch, tmp_path
):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROJECT_DELETE_PROCESS", "from-shell")
    r = client_with_projects.delete(
        "/api/projects/alpha/secrets/PROJECT_DELETE_PROCESS"
    )
    assert r.status_code == 400


def test_delete_project_secret_404_for_unknown_project(client_with_projects):
    r = client_with_projects.delete("/api/projects/missing/secrets/ANY_KEY")
    assert r.status_code == 404


# ---- Defense in depth -----------------------------------------------------


def test_project_secret_value_never_returned_in_list(
    client_with_projects, monkeypatch, tmp_path
):
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    secret_value = "do-not-leak-this-project-value"
    client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={"name": "PROJECT_LEAK_TEST", "value": secret_value},
    )
    r = client_with_projects.get("/api/projects/alpha/secrets")
    assert secret_value not in r.text


def test_project_secrets_file_is_chmod_0600(
    client_with_projects, monkeypatch, tmp_path
):
    """The project secrets file inherits the vault's chmod-0600 policy."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    client_with_projects.post(
        "/api/projects/alpha/secrets",
        data={"name": "CHMOD_KEY", "value": "chmod-test-value-padding"},
    )
    proj_secrets: Path = tmp_path / "alpha" / ".urika" / "secrets.env"
    assert proj_secrets.exists()
    mode = oct(proj_secrets.stat().st_mode & 0o777)
    # On POSIX systems the file should be 0600. On Windows or unusual
    # filesystems chmod may be a no-op — vault tolerates that, so we
    # only assert the strict mode when we're on a POSIX-y mount.
    if mode != "0o600":
        # If chmod didn't take effect we still want the test to fail
        # noisily on the platforms where it should — Linux test boxes.
        import sys
        if sys.platform.startswith("linux") or sys.platform == "darwin":
            assert mode == "0o600", f"expected 0o600, got {mode}"
