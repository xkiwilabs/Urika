"""Tests for /projects/<n>/data and /projects/<n>/data/inspect — Phase 13E.1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _write_csv(path: Path) -> None:
    """Tiny 3-column / 5-row CSV used across the data-inspect tests."""
    path.write_text(
        "a,b,c\n1,2.0,x\n2,3.0,y\n3,4.0,z\n4,5.0,w\n5,6.0,v\n",
        encoding="utf-8",
    )


def _make_project(
    root: Path,
    name: str,
    *,
    data_paths: list[str] | None = None,
) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    dp_lines = ""
    if data_paths is not None:
        rendered = ", ".join(f'"{p}"' for p in data_paths)
        dp_lines = f"data_paths = [{rendered}]\n"
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\n'
        f'mode = "exploratory"\ndescription = ""\n{dp_lines}\n'
        f'[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def data_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Project ``alpha`` with a registered CSV data source under tmp."""
    csv = tmp_path / "data.csv"
    _write_csv(csv)
    proj = _make_project(tmp_path, "alpha", data_paths=[str(csv)])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_data_list_renders_registered_files(data_client, tmp_path):
    r = data_client.get("/projects/alpha/data")
    assert r.status_code == 200
    body = r.text
    assert "Data sources" in body
    assert "data.csv" in body
    # Inspect link uses the absolute path as a query param.
    assert "/projects/alpha/data/inspect?path=" in body


def test_data_list_empty_state_when_no_data_paths(tmp_path, monkeypatch):
    proj = _make_project(tmp_path, "alpha", data_paths=[])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/data")
    assert r.status_code == 200
    assert "No data sources registered" in r.text


def test_data_list_404_unknown_project(data_client):
    r = data_client.get("/projects/nope/data")
    assert r.status_code == 404


def test_data_list_lists_directory_entries(tmp_path, monkeypatch):
    """A data_paths entry that's a directory expands to its supported files."""
    data_dir = tmp_path / "ds"
    data_dir.mkdir()
    _write_csv(data_dir / "first.csv")
    _write_csv(data_dir / "second.csv")
    # Unsupported file inside the directory should NOT show up in the listing
    # (we only list files whose extension is in the loader registry).
    (data_dir / "ignore.bin").write_bytes(b"\x00")
    proj = _make_project(tmp_path, "alpha", data_paths=[str(data_dir)])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/data")
    assert r.status_code == 200
    body = r.text
    assert "first.csv" in body
    assert "second.csv" in body
    assert "ignore.bin" not in body


def test_data_inspect_renders_schema_and_preview(data_client, tmp_path):
    csv = tmp_path / "data.csv"
    r = data_client.get("/projects/alpha/data/inspect", params={"path": str(csv)})
    assert r.status_code == 200
    body = r.text
    # Schema table — column names render as table cells.
    assert "<th>Column</th>" in body
    for col in ("a", "b", "c"):
        assert col in body
    # Numeric columns surface stats. Pandas 3.0 forward-compat: dtype
    # for the string column may render as ``object`` (pandas 2.x) or
    # ``string``/``str`` (pandas 3.0) — accept any of those.
    assert "mean=" in body
    assert ("object" in body) or ("string" in body) or ("str" in body)
    # 5-row CSV: head AND tail should both render data rows.
    assert "First 10 rows" in body
    assert "Last 10 rows" in body
    # Specific values from the CSV.
    assert ">1<" in body or ">1.0<" in body  # first row "a" cell
    assert ">v<" in body  # last row "c" cell
    # n_rows / n_columns counter.
    assert "5 rows" in body
    assert "3 columns" in body


def test_data_inspect_400_for_path_outside_data_paths(data_client, tmp_path):
    """Path traversal protection — a path not under data_paths must 400."""
    outside = tmp_path / "outside.csv"
    _write_csv(outside)
    r = data_client.get("/projects/alpha/data/inspect", params={"path": str(outside)})
    assert r.status_code == 400


def test_data_inspect_400_for_dotdot_traversal(data_client, tmp_path):
    """A literal ``..`` segment in the requested path is rejected."""
    csv = tmp_path / "data.csv"
    bad = f"{csv.parent}/../{csv.parent.name}/data.csv"
    r = data_client.get("/projects/alpha/data/inspect", params={"path": bad})
    assert r.status_code == 400


def test_data_inspect_404_for_missing_file(tmp_path, monkeypatch):
    """A registered-but-missing file 404s the inspect handler."""
    missing = tmp_path / "missing.csv"  # never created
    proj = _make_project(tmp_path, "alpha", data_paths=[str(missing)])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/data/inspect", params={"path": str(missing)})
    assert r.status_code == 404


def test_data_inspect_unsupported_format_renders_message(tmp_path, monkeypatch):
    """An unsupported extension shows the "Unsupported format" message
    rather than crashing."""
    blob = tmp_path / "data.bin"
    blob.write_bytes(b"\x00\x01\x02")
    proj = _make_project(tmp_path, "alpha", data_paths=[str(blob)])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/data/inspect", params={"path": str(blob)})
    assert r.status_code == 200
    assert "Unsupported format" in r.text


def test_data_inspect_400_when_path_missing(data_client):
    r = data_client.get("/projects/alpha/data/inspect")
    assert r.status_code == 400
