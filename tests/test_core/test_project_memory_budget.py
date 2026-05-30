"""Tests for project memory token-budget primitives (v0.5.0 Track 2).

Covers Tasks 2.1 (estimate_tokens + cap constants), 2.2 (hard-cap
truncation in load_project_memory with "run urika memory curate"
marker), and 2.3 (session-scoped curator-due flag).
"""

from __future__ import annotations


def test_estimate_tokens_uses_bytes_over_3_5():
    from urika.core.project_memory import estimate_tokens

    s = "x" * 350
    assert estimate_tokens(s) == 100  # 350 bytes / 3.5


def test_estimate_tokens_handles_non_ascii():
    from urika.core.project_memory import estimate_tokens

    s = "日本語"  # 9 bytes UTF-8
    assert estimate_tokens(s) > 0


def test_caps_exposed_as_module_constants():
    from urika.core import project_memory as pm

    assert pm.SOFT_CAP_TOKENS == 5_000
    assert pm.HARD_CAP_TOKENS == 10_000
    assert pm.SOFT_CAP_ENTRIES == 30
