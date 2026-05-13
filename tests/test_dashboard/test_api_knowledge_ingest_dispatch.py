"""Dashboard /api/projects/{name}/knowledge — URL + PDF + 500 paths.

The existing ``test_api_knowledge.py`` only exercises the text-file
happy path, 404 (unknown project), and 422 (blank source). Three real
code paths in :meth:`KnowledgeStore.ingest` are unexercised:

* **URL source** — dispatch through ``_extract`` → ``extract_url``.
* **PDF source** — dispatch through ``_extract`` → ``extract_pdf``.
* **Ingest exception** — ``store.ingest`` raises (network failure,
  unreadable PDF, unknown extension); the endpoint catches it and
  returns 500 with ``detail="Ingest failed: ..."``.

We mock the extractors so the test stays hermetic (no network, no PDF
library required), then assert the endpoint round-trips correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def kn_client(tmp_path: Path, monkeypatch):
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


# ── URL source ─────────────────────────────────────────────────────


def test_knowledge_add_with_http_url(kn_client, monkeypatch):
    """A source starting with ``http://`` is detected as a URL and
    dispatched to ``extract_url``. The URL is captured + a stub
    body is returned — confirms the route reaches the URL branch."""
    client, proj = kn_client
    captured: list[str] = []

    def _fake_extract_url(source: str) -> str:
        captured.append(source)
        return "Stub URL body — abstract here."

    # The store imports extract_url at module level — patch the binding
    # in urika.knowledge.store (not urika.knowledge.extractors).
    monkeypatch.setattr("urika.knowledge.store.extract_url", _fake_extract_url)
    r = client.post(
        "/api/projects/alpha/knowledge",
        data={"source": "https://example.com/paper.html"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "id" in body
    # The URL reached the extractor.
    assert captured == ["https://example.com/paper.html"]
    # An index entry was written.
    index = json.loads((proj / "knowledge" / "index.json").read_text())
    assert any(
        e.get("source") == "https://example.com/paper.html"
        for e in index.get("entries", [])
    )


def test_knowledge_add_with_https_url(kn_client, monkeypatch):
    """https:// schemes also dispatch to the URL branch (mirror coverage)."""
    client, _ = kn_client
    monkeypatch.setattr(
        "urika.knowledge.store.extract_url", lambda url: f"body for {url}"
    )
    r = client.post(
        "/api/projects/alpha/knowledge",
        data={"source": "https://arxiv.org/abs/2103.12345"},
    )
    assert r.status_code == 201


def test_knowledge_add_url_extractor_failure_returns_500(kn_client, monkeypatch):
    """Network failure inside the extractor surfaces as 500 with
    ``detail="Ingest failed: ..."`` — the endpoint must not crash
    the dashboard process."""
    client, _ = kn_client

    def _raise(_url: str) -> str:
        raise RuntimeError("timeout fetching URL")

    monkeypatch.setattr("urika.knowledge.store.extract_url", _raise)
    r = client.post(
        "/api/projects/alpha/knowledge",
        data={"source": "https://example.com/down"},
    )
    assert r.status_code == 500
    assert "Ingest failed" in r.json()["detail"]
    assert "timeout fetching URL" in r.json()["detail"]


# ── PDF source ─────────────────────────────────────────────────────


def test_knowledge_add_with_pdf_dispatches_to_pdf_extractor(
    kn_client, monkeypatch, tmp_path
):
    """A ``.pdf`` file dispatches to ``extract_pdf``. Stub the
    extractor so the test doesn't need a real PDF or pypdf at runtime."""
    client, _ = kn_client
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    captured: list[Path] = []

    def _fake_extract_pdf(p: Path) -> str:
        captured.append(p)
        return "Stub PDF abstract."

    monkeypatch.setattr("urika.knowledge.store.extract_pdf", _fake_extract_pdf)
    r = client.post("/api/projects/alpha/knowledge", data={"source": str(pdf)})
    assert r.status_code == 201
    assert len(captured) == 1
    # The extractor was given the same path the user submitted.
    assert str(captured[0]) == str(pdf)


def test_knowledge_add_pdf_extractor_failure_returns_500(
    kn_client, monkeypatch, tmp_path
):
    """PDF parse failure → 500 with the exception message in detail."""
    client, _ = kn_client
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"not really a pdf")

    def _raise(_p: Path) -> str:
        raise ValueError("PdfReadError: invalid header")

    monkeypatch.setattr("urika.knowledge.store.extract_pdf", _raise)
    r = client.post("/api/projects/alpha/knowledge", data={"source": str(pdf)})
    assert r.status_code == 500
    assert "Ingest failed" in r.json()["detail"]
    assert "PdfReadError" in r.json()["detail"]


# ── Unknown extension → 500 ────────────────────────────────────────


def test_knowledge_add_unknown_extension_500s(kn_client, tmp_path):
    """A local file whose suffix isn't in ``_EXTENSION_TYPES`` triggers
    ``_detect_type`` ValueError — the endpoint catches it and returns
    500 with the original error message in ``detail``."""
    client, _ = kn_client
    blob = tmp_path / "data.xyz"
    blob.write_bytes(b"garbage")
    r = client.post("/api/projects/alpha/knowledge", data={"source": str(blob)})
    assert r.status_code == 500
    assert "Ingest failed" in r.json()["detail"]
    # The underlying message comes from _detect_type.
    assert "Cannot detect source type" in r.json()["detail"]


def test_knowledge_add_file_not_found_500s(kn_client, monkeypatch):
    """Path the user submitted doesn't exist → the text extractor
    raises FileNotFoundError → 500."""
    client, _ = kn_client

    def _raise(_p: Path) -> str:
        raise FileNotFoundError("/nope/missing.md")

    monkeypatch.setattr("urika.knowledge.store.extract_text", _raise)
    r = client.post(
        "/api/projects/alpha/knowledge",
        data={"source": "/tmp/definitely-not-there-12345.md"},
    )
    assert r.status_code == 500
    assert "Ingest failed" in r.json()["detail"]


# ── Response payload contract ──────────────────────────────────────


def test_knowledge_add_response_includes_id_and_title(kn_client, tmp_path):
    """JSONResponse fields: ``id`` (str) + ``title`` (derived from
    source filename). Asserts the API contract HTMX/Alpine consumes."""
    client, _ = kn_client
    md = tmp_path / "MyNote.md"
    md.write_text("body")
    r = client.post("/api/projects/alpha/knowledge", data={"source": str(md)})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "MyNote.md"


def test_knowledge_add_hx_redirect_no_body(kn_client, tmp_path):
    """When ``hx-request: true``, the response uses
    ``HX-Redirect`` and may have an empty body — pin that no
    redirect-vs-JSON conflict happens."""
    client, _ = kn_client
    md = tmp_path / "h.md"
    md.write_text("body")
    r = client.post(
        "/api/projects/alpha/knowledge",
        data={"source": str(md)},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 201
    assert r.headers.get("hx-redirect") == "/projects/alpha/knowledge"
