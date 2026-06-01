from __future__ import annotations

from urika.agents.pricing import PRICES, cost_for


def test_known_model_returns_dollar_amount():
    # 1M input tokens of claude-opus-4-7 = $15
    assert cost_for("claude-opus-4-7", 1_000_000, 0) == 15.0
    # 1M output tokens of claude-opus-4-7 = $75
    assert cost_for("claude-opus-4-7", 0, 1_000_000) == 75.0


def test_unknown_model_returns_zero():
    assert cost_for("totally-made-up", 5_000, 5_000) == 0.0


def test_all_advertised_defaults_have_prices():
    required = {
        "claude-opus-4-7",
        "claude-sonnet-4-5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
    }
    assert required <= set(PRICES.keys())
