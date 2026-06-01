"""Tests for ``core/readme_generator.py``.

The 209-line module had zero direct test coverage before this file —
only exercised indirectly via project-builder tests that check the file
exists, not its contents.
"""

from __future__ import annotations

import json
from pathlib import Path


from urika.core.readme_generator import (
    _format_metrics,
    _get_best_metric,
    _get_key_finding,
    _load_criteria,
    _load_methods,
    write_readme,
)


# ── _load_methods ──────────────────────────────────────────────


def test_load_methods_returns_empty_when_missing(tmp_path: Path) -> None:
    assert _load_methods(tmp_path) == []


def test_load_methods_parses_well_formed(tmp_path: Path) -> None:
    (tmp_path / "methods.json").write_text(
        json.dumps({"methods": [{"name": "lr"}, {"name": "rf"}]})
    )
    methods = _load_methods(tmp_path)
    assert [m["name"] for m in methods] == ["lr", "rf"]


def test_load_methods_corrupt_returns_empty(tmp_path: Path) -> None:
    """Defensive fallback: a malformed methods.json → return []
    rather than crashing the README writer."""
    (tmp_path / "methods.json").write_text("{not valid json")
    assert _load_methods(tmp_path) == []


# ── _load_criteria ─────────────────────────────────────────────


def test_load_criteria_returns_none_when_missing(tmp_path: Path) -> None:
    assert _load_criteria(tmp_path) is None


def test_load_criteria_returns_latest_version(tmp_path: Path) -> None:
    (tmp_path / "criteria.json").write_text(
        json.dumps(
            {
                "versions": [
                    {"version": 1, "criteria": {"r2": ">= 0.5"}},
                    {"version": 2, "criteria": {"r2": ">= 0.7"}},
                ]
            }
        )
    )
    v = _load_criteria(tmp_path)
    assert v["version"] == 2


def test_load_criteria_corrupt_returns_none(tmp_path: Path) -> None:
    (tmp_path / "criteria.json").write_text("not json")
    assert _load_criteria(tmp_path) is None


def test_load_criteria_empty_versions_returns_none(tmp_path: Path) -> None:
    (tmp_path / "criteria.json").write_text(json.dumps({"versions": []}))
    assert _load_criteria(tmp_path) is None


# ── _format_metrics ────────────────────────────────────────────


def test_format_metrics_empty() -> None:
    assert _format_metrics({}) == ""


def test_format_metrics_non_numeric_only() -> None:
    """Non-numeric values are filtered out — empty result."""
    assert _format_metrics({"label": "good"}) == ""


def test_format_metrics_numeric_percentage() -> None:
    """0 < v < 1 floats formatted as percentages."""
    out = _format_metrics({"r2": 0.75})
    assert "75.0%" in out or "75%" in out


def test_format_metrics_numeric_non_percentage() -> None:
    """v >= 1 floats formatted as 2-decimal numbers."""
    out = _format_metrics({"rmse": 12.34})
    assert "12.34" in out


def test_format_metrics_int_values() -> None:
    out = _format_metrics({"n_runs": 5})
    assert "5" in out


def test_format_metrics_caps_at_two_metrics() -> None:
    """Only the first two (alphabetical) numeric metrics are shown."""
    out = _format_metrics({"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.4})
    # First two are "a" and "b" alphabetically; "c"/"d" absent.
    assert "c" not in out and "d" not in out


# ── _get_key_finding ───────────────────────────────────────────


def test_get_key_finding_empty_runs() -> None:
    assert _get_key_finding([]) == ""


def test_get_key_finding_uses_last_observation() -> None:
    runs = [
        {"method": "old", "observation": "ignore me."},
        {"method": "new", "observation": "Recent run: clean fit. Lots more text."},
    ]
    out = _get_key_finding(runs)
    assert "Recent run: clean fit" in out
    # Trailing detail dropped (first-sentence only).
    assert "Lots more text" not in out


def test_get_key_finding_truncates_long_first_sentence() -> None:
    runs = [{"observation": "x" * 200}]
    out = _get_key_finding(runs)
    assert len(out) <= 80
    assert "…" in out


def test_get_key_finding_falls_back_to_method_when_no_observation() -> None:
    runs = [{"method": "ridge_regression"}]
    assert _get_key_finding(runs) == "ridge_regression"


# ── _get_best_metric ───────────────────────────────────────────


def test_get_best_metric_higher_picks_max() -> None:
    methods = [
        {"metrics": {"r2": 0.3}},
        {"metrics": {"r2": 0.8}},
        {"metrics": {"r2": 0.5}},
    ]
    assert _get_best_metric(methods, "r2", "higher") == 0.8


def test_get_best_metric_lower_picks_min() -> None:
    methods = [
        {"metrics": {"rmse": 1.0}},
        {"metrics": {"rmse": 0.5}},
        {"metrics": {"rmse": 1.5}},
    ]
    assert _get_best_metric(methods, "rmse", "lower") == 0.5


def test_get_best_metric_skips_non_numeric() -> None:
    methods = [{"metrics": {"r2": 0.5}}, {"metrics": {"r2": "good"}}]
    assert _get_best_metric(methods, "r2", "higher") == 0.5


def test_get_best_metric_returns_none_when_no_values() -> None:
    methods = [{"metrics": {}}, {"metrics": {"r2": "good"}}]
    assert _get_best_metric(methods, "r2", "higher") is None


# ── write_readme ───────────────────────────────────────────────


def test_write_readme_creates_file(tmp_path: Path) -> None:
    # Need a urika.toml for the generator to find the project name.
    (tmp_path / "urika.toml").write_text(
        '[project]\nname = "demo"\nquestion = "Does X predict Y?"\n'
        'mode = "exploratory"\n',
        encoding="utf-8",
    )
    p = write_readme(tmp_path)
    assert p == tmp_path / "README.md"
    assert p.exists()
    body = p.read_text(encoding="utf-8")
    # Question / project name appears.
    assert "demo" in body or "Does X" in body


def test_write_readme_overwrites_existing(tmp_path: Path) -> None:
    (tmp_path / "urika.toml").write_text(
        '[project]\nname = "x"\nquestion = "?"\nmode = "exploratory"\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "OLD CONTENT — should be replaced", encoding="utf-8"
    )
    write_readme(tmp_path)
    body = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "OLD CONTENT" not in body


def test_write_readme_with_methods_includes_summary(tmp_path: Path) -> None:
    (tmp_path / "urika.toml").write_text(
        '[project]\nname = "demo"\nquestion = "?"\nmode = "exploratory"\n'
    )
    (tmp_path / "methods.json").write_text(
        json.dumps(
            {
                "methods": [
                    {"name": "linear", "metrics": {"r2": 0.6}, "status": "active"},
                    {"name": "ridge", "metrics": {"r2": 0.8}, "status": "active"},
                ]
            }
        )
    )
    write_readme(tmp_path)
    body = (tmp_path / "README.md").read_text(encoding="utf-8")
    # Mentions at least one method name.
    assert "linear" in body or "ridge" in body
