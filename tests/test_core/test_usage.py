"""Tests for usage tracking."""

from __future__ import annotations

from pathlib import Path

from urika.core.usage import (
    estimate_cost,
    format_usage,
    get_last_session,
    get_totals,
    load_usage,
    record_session,
)


class TestRecordSession:
    def test_creates_file(self, tmp_path: Path) -> None:
        record_session(
            tmp_path,
            started="2026-01-01T00:00:00Z",
            ended="2026-01-01T01:00:00Z",
            duration_ms=3600000,
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.50,
            agent_calls=5,
        )
        assert (tmp_path / "usage.json").exists()

    def test_appends_sessions(self, tmp_path: Path) -> None:
        for i in range(3):
            record_session(
                tmp_path,
                started=f"2026-01-0{i + 1}T00:00:00Z",
                ended=f"2026-01-0{i + 1}T01:00:00Z",
                duration_ms=1000,
                agent_calls=1,
            )
        data = load_usage(tmp_path)
        assert len(data["sessions"]) == 3

    def test_updates_totals(self, tmp_path: Path) -> None:
        record_session(
            tmp_path,
            started="a",
            ended="b",
            duration_ms=1000,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.10,
            agent_calls=2,
            experiments_run=1,
        )
        record_session(
            tmp_path,
            started="c",
            ended="d",
            duration_ms=2000,
            tokens_in=200,
            tokens_out=100,
            cost_usd=0.20,
            agent_calls=3,
            experiments_run=2,
        )
        totals = get_totals(tmp_path)
        assert totals["sessions"] == 2
        assert totals["total_tokens_in"] == 300
        assert totals["total_tokens_out"] == 150
        assert totals["total_cost_usd"] == 0.30
        assert totals["total_agent_calls"] == 5
        assert totals["total_experiments"] == 3


class TestGetLastSession:
    def test_returns_none_when_empty(self, tmp_path: Path) -> None:
        assert get_last_session(tmp_path) is None

    def test_returns_last(self, tmp_path: Path) -> None:
        record_session(
            tmp_path, started="a", ended="b", duration_ms=1000, agent_calls=1
        )
        record_session(
            tmp_path, started="c", ended="d", duration_ms=2000, agent_calls=2
        )
        last = get_last_session(tmp_path)
        assert last["agent_calls"] == 2


class TestEstimateCost:
    def test_sonnet_default(self) -> None:
        cost = estimate_cost(1_000_000, 100_000)
        assert cost > 0

    def test_opus_more_expensive(self) -> None:
        sonnet = estimate_cost(1000, 1000)
        opus = estimate_cost(1000, 1000, model="opus")
        assert opus > sonnet


class TestFormatUsage:
    def test_formats_with_session(self) -> None:
        last = {
            "duration_ms": 60000,
            "tokens_in": 1000,
            "tokens_out": 500,
            "cost_usd": 0.5,
            "agent_calls": 3,
        }
        totals = {
            "sessions": 1,
            "total_duration_ms": 60000,
            "total_tokens_in": 1000,
            "total_tokens_out": 500,
            "total_cost_usd": 0.5,
            "total_agent_calls": 3,
            "total_experiments": 1,
        }
        text = format_usage(last, totals)
        assert "Last session" in text
        assert "All time" in text

    def test_subscription_note(self) -> None:
        last = {
            "duration_ms": 1000,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0,
            "agent_calls": 1,
        }
        totals = {
            "sessions": 1,
            "total_duration_ms": 1000,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost_usd": 0,
            "total_agent_calls": 1,
            "total_experiments": 0,
        }
        text = format_usage(last, totals, is_subscription=True)
        assert "plan" in text.lower() or "estimated" in text.lower()


# ── per_session_cost_distribution (v0.4 Track 4) ─────────────────────


class TestPerSessionCostDistribution:
    """``per_session_cost_distribution`` powers ``urika run --dry-run``'s
    cost estimate. Returns the last N non-zero session costs in
    chronological order.
    """

    def test_empty_when_no_sessions(self, tmp_path):
        from urika.core.usage import per_session_cost_distribution

        assert per_session_cost_distribution(tmp_path) == []

    def test_returns_recent_costs(self, tmp_path):
        from urika.core.usage import (
            per_session_cost_distribution,
            record_session,
        )

        for cost in (0.10, 0.20, 0.30):
            record_session(
                tmp_path,
                started="2026-04-30T00:00:00Z",
                ended="2026-04-30T00:00:01Z",
                duration_ms=1000,
                cost_usd=cost,
            )
        costs = per_session_cost_distribution(tmp_path)
        assert costs == [0.1, 0.2, 0.3]

    def test_filters_zero_cost_sessions(self, tmp_path):
        """Sessions with no recorded cost (smoke tests) shouldn't
        anchor the distribution at zero."""
        from urika.core.usage import (
            per_session_cost_distribution,
            record_session,
        )

        for cost in (0.0, 0.0, 0.50):
            record_session(
                tmp_path,
                started="2026-04-30T00:00:00Z",
                ended="2026-04-30T00:00:01Z",
                duration_ms=1000,
                cost_usd=cost,
            )
        costs = per_session_cost_distribution(tmp_path)
        assert costs == [0.5]

    def test_last_n_clipping(self, tmp_path):
        from urika.core.usage import (
            per_session_cost_distribution,
            record_session,
        )

        for i in range(10):
            record_session(
                tmp_path,
                started="2026-04-30T00:00:00Z",
                ended="2026-04-30T00:00:01Z",
                duration_ms=1000,
                cost_usd=float(i + 1) * 0.1,
            )
        costs = per_session_cost_distribution(tmp_path, last_n=3)
        assert len(costs) == 3
        # Most-recent three: cost_usd = 0.8, 0.9, 1.0
        assert costs[-1] > costs[0]
