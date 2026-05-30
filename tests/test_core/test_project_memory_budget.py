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


def test_load_memory_hard_cap_truncates_and_appends_marker(tmp_path):
    from urika.core import project_memory as pm

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    # 15K tokens worth of body: each big entry is ~16800 tokens
    big = "x" * 60_000  # 60000 / 3.5 ≈ 17142 tokens
    for i in range(3):
        pm.save_entry(proj, mem_type="user", description=f"big-{i}", body=big)
    out = pm.load_project_memory(proj)
    assert pm.estimate_tokens(out) <= pm.HARD_CAP_TOKENS + 500  # ±slack for marker
    assert "Project Memory (over budget — run urika memory curate)" in out


def test_load_memory_soft_cap_does_not_truncate(tmp_path):
    from urika.core import project_memory as pm

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    # ~6K tokens — over soft (5K) but under hard (10K)
    body = "x" * 21_000  # 21000/3.5 = 6000 tokens
    pm.save_entry(proj, mem_type="user", description="medium", body=body)
    out = pm.load_project_memory(proj)
    assert "over budget" not in out  # no marker at soft cap
    assert body in out  # full body still present


def test_soft_cap_sets_session_flag(tmp_path):
    from urika.core import project_memory as pm

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    body = "x" * 21_000  # ~6K tokens
    pm.save_entry(proj, mem_type="user", description="m", body=body)
    pm.load_project_memory(proj, session_id="s1")
    assert pm.is_curator_due(proj, session_id="s1") is True
    assert pm.is_curator_due(proj, session_id="s2") is False  # other session


def test_under_soft_cap_does_not_set_flag(tmp_path):
    from urika.core import project_memory as pm

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="m", body="small body")
    pm.load_project_memory(proj, session_id="s1")
    assert pm.is_curator_due(proj, session_id="s1") is False


def test_mark_curator_ran_clears_session(tmp_path):
    from urika.core import project_memory as pm

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    body = "x" * 21_000
    pm.save_entry(proj, mem_type="user", description="m", body=body)
    pm.load_project_memory(proj, session_id="s1")
    pm.mark_curator_ran(proj, session_id="s1")
    assert pm.is_curator_due(proj, session_id="s1") is False


def test_load_memory_session_id_optional(tmp_path):
    """Existing callers that pass no session_id must still work."""
    from urika.core import project_memory as pm

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="m", body="b")
    # No session_id arg — must not raise, must not write flag file.
    out = pm.load_project_memory(proj)
    assert "m" in out or "b" in out  # entry present
    flag = proj / "memory" / ".curator-flag.json"
    assert not flag.exists()  # no signal because session_id=None
