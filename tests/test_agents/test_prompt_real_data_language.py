"""Pin the "no synthetic data" language across the prompts that read
real data.

``task_agent`` and ``data_agent`` already have dedicated coverage in
``test_real_data_prompt.py``. The other agents that consume real data
indirectly (``finalizer`` reads experiment data, ``report_agent`` /
``presentation_agent`` summarize it, ``literature_agent`` references
it) — pin minimum-required language so a future edit can't quietly
allow fabrication.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_PROMPTS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "urika"
    / "agents"
    / "roles"
    / "prompts"
)


def _read(role: str) -> str:
    return (_PROMPTS / f"{role}_system.md").read_text(encoding="utf-8")


# ── finalizer ──────────────────────────────────────────────────


def test_finalizer_prompt_forbids_fabrication() -> None:
    body = _read("finalizer")
    # The existing pinned phrase at line ~135.
    assert "do not fabricate" in body.lower() or "fabricate metrics" in body.lower()


def test_finalizer_prompt_says_real_data() -> None:
    body = _read("finalizer").lower()
    # "Real" / "actual" / "real experiment data" — any form.
    assert (
        "actual experiment data" in body or "real data" in body or "actual data" in body
    )


def test_finalizer_prompt_requires_zero_argument_scripts() -> None:
    """reproduce.sh and reproduce.ipynb execute the final method
    scripts WITHOUT arguments, so every final_*.py must run with zero
    command-line arguments (flags allowed, but each needs a working
    default pointing at the project's real data)."""
    body = _read("finalizer").lower()
    assert "zero command-line arguments" in body
    assert "working default" in body
    assert "without arguments" in body, (
        "the prompt must say WHY: reproduce.sh / reproduce.ipynb run "
        "the scripts without arguments"
    )
    assert "--data <path>" not in body, (
        "the prompt must not model an invocation that requires arguments"
    )


# ── report_agent ───────────────────────────────────────────────


def test_report_agent_prompt_does_not_enable_synthetic_data() -> None:
    """The report agent reads findings.json + project artifacts and
    writes prose. It must NOT contain language that authorizes
    fabrication (e.g. 'if data is missing, generate plausible
    examples')."""
    body = _read("report_agent").lower()
    bad_phrases = [
        "generate synthetic",
        "fabricate",
        "make up",
        "invent results",
        "plausible example data",
    ]
    for phrase in bad_phrases:
        assert phrase not in body, (
            f"report_agent prompt enables fabrication: {phrase!r}"
        )


# ── presentation_agent ─────────────────────────────────────────


def test_presentation_agent_prompt_does_not_enable_synthetic_data() -> None:
    body = _read("presentation_agent").lower()
    for phrase in ("generate synthetic", "fabricate", "invent results"):
        assert phrase not in body


# ── advisor_agent ──────────────────────────────────────────────


def test_advisor_agent_prompt_does_not_enable_synthetic_data() -> None:
    body = _read("advisor_agent").lower()
    for phrase in ("generate synthetic", "fabricate", "invent results"):
        assert phrase not in body


# ── evaluator ──────────────────────────────────────────────────


def test_evaluator_prompt_grounds_on_real_metrics() -> None:
    body = _read("evaluator").lower()
    grounded = (
        "progress.json" in body
        or "methods.json" in body
        or "actual" in body
        or "real" in body
    )
    assert grounded, "evaluator prompt does not ground its assessment on real run data"
    # "Invent" by itself appears in the legit phrase "do not invent
    # criteria that are not defined" — only flag *data-fabrication* uses.
    for phrase in (
        "generate synthetic",
        "fabricate metrics",
        "invent data",
        "invent results",
    ):
        assert phrase not in body


# ── tool_builder ───────────────────────────────────────────────


def test_tool_builder_prompt_does_not_enable_synthetic_data() -> None:
    body = _read("tool_builder").lower()
    for phrase in ("generate synthetic", "fabricate", "invent"):
        assert phrase not in body


# ── literature_agent ───────────────────────────────────────────


def test_literature_agent_prompt_does_not_enable_synthetic_data() -> None:
    body = _read("literature_agent").lower()
    for phrase in ("generate synthetic", "fabricate", "invent"):
        assert phrase not in body


# ── planning_agent ─────────────────────────────────────────────


def test_planning_agent_prompt_grounds_on_real_data() -> None:
    body = _read("planning_agent").lower()
    for phrase in ("generate synthetic", "fabricate", "invent"):
        assert phrase not in body


# ── meta — every prompt that reads data references it ──────────


@pytest.mark.parametrize("role", ["task_agent", "data_agent", "finalizer", "evaluator"])
def test_prompt_references_real_data_at_some_point(role: str) -> None:
    """A prompt that consumes data must say so somewhere."""
    body = _read(role).lower()
    assert (
        "real data" in body
        or "real dataset" in body
        or "actual data" in body
        or "actual experiment data" in body
        or "progress.json" in body
    )
