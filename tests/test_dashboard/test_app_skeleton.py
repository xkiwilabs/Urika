"""Tests for the FastAPI app skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def test_create_app_returns_fastapi_instance():
    from fastapi import FastAPI

    app = create_app(project_root=None)
    assert isinstance(app, FastAPI)


def test_health_endpoint_returns_ok():
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
