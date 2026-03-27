"""Usage tracking — records session costs, tokens, and duration per project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.core.filelock import locked_json_update


def _usage_path(project_dir: Path) -> Path:
    return project_dir / "usage.json"


def load_usage(project_dir: Path) -> dict[str, Any]:
    """Load usage data for a project."""
    path = _usage_path(project_dir)
    if not path.exists():
        return {"sessions": [], "totals": _empty_totals()}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return {"sessions": [], "totals": _empty_totals()}


def record_session(
    project_dir: Path,
    *,
    started: str,
    ended: str,
    duration_ms: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    agent_calls: int = 0,
    experiments_run: int = 0,
) -> None:
    """Append a session record and update totals."""
    path = _usage_path(project_dir)
    with locked_json_update(path):
        data = load_usage(project_dir)

        session = {
            "started": started,
            "ended": ended,
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 4),
            "agent_calls": agent_calls,
            "experiments_run": experiments_run,
        }
        data["sessions"].append(session)

        # Update totals
        totals = data.get("totals", _empty_totals())
        totals["sessions"] = len(data["sessions"])
        totals["total_duration_ms"] += duration_ms
        totals["total_tokens_in"] += tokens_in
        totals["total_tokens_out"] += tokens_out
        totals["total_cost_usd"] = round(totals["total_cost_usd"] + cost_usd, 4)
        totals["total_agent_calls"] += agent_calls
        totals["total_experiments"] += experiments_run
        data["totals"] = totals

        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_last_session(project_dir: Path) -> dict[str, Any] | None:
    """Get the most recent session record."""
    data = load_usage(project_dir)
    sessions = data.get("sessions", [])
    return sessions[-1] if sessions else None


def get_totals(project_dir: Path) -> dict[str, Any]:
    """Get cumulative totals."""
    data = load_usage(project_dir)
    return data.get("totals", _empty_totals())


def estimate_cost(tokens_in: int, tokens_out: int, model: str = "") -> float:
    """Estimate cost at API rates from token counts.

    Uses Claude Sonnet pricing as default. Returns USD.
    """
    # Claude Sonnet 4 pricing (as of 2026)
    if "opus" in model.lower():
        price_in = 15.0 / 1_000_000  # $15 per 1M input tokens
        price_out = 75.0 / 1_000_000  # $75 per 1M output tokens
    elif "haiku" in model.lower():
        price_in = 0.80 / 1_000_000
        price_out = 4.0 / 1_000_000
    else:
        # Sonnet default
        price_in = 3.0 / 1_000_000
        price_out = 15.0 / 1_000_000

    return tokens_in * price_in + tokens_out * price_out


def format_usage(
    last_session: dict[str, Any] | None,
    totals: dict[str, Any],
    is_subscription: bool = False,
) -> str:
    """Format usage data for display."""
    from urika.cli_display import _format_duration

    lines = []

    if last_session:
        dur = _format_duration(last_session.get("duration_ms", 0))
        tokens = last_session.get("tokens_in", 0) + last_session.get("tokens_out", 0)
        cost = last_session.get("cost_usd", 0)
        calls = last_session.get("agent_calls", 0)
        cost_str = f"~${cost:.2f}"
        if is_subscription:
            cost_str += " (estimated at API rates — does not apply on your plan)"
        lines.append(
            f"  Last session: {dur} · {_fmt_tokens(tokens)} tokens · "
            f"{cost_str} · {calls} agent calls"
        )

    total_dur = _format_duration(totals.get("total_duration_ms", 0))
    total_tokens = totals.get("total_tokens_in", 0) + totals.get("total_tokens_out", 0)
    total_cost = totals.get("total_cost_usd", 0)
    total_calls = totals.get("total_agent_calls", 0)
    total_sessions = totals.get("sessions", 0)
    total_exps = totals.get("total_experiments", 0)
    cost_str = f"~${total_cost:.2f}"
    if is_subscription:
        cost_str += " (estimated)"
    lines.append(
        f"  All time:     {total_sessions} sessions · {total_dur} · "
        f"{_fmt_tokens(total_tokens)} tokens · {cost_str} · "
        f"{total_calls} agent calls · {total_exps} experiments"
    )

    return "\n".join(lines)


def _fmt_tokens(n: int) -> str:
    """Format token count as human-readable."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _empty_totals() -> dict[str, Any]:
    return {
        "sessions": 0,
        "total_duration_ms": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_cost_usd": 0.0,
        "total_agent_calls": 0,
        "total_experiments": 0,
    }
