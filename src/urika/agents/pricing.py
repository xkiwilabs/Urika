"""Single source of $-per-1M-tokens truth across all adapters.

Gemini prices are placeholders — verify against published rates
before tagging v0.7.0.
"""

from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    # Anthropic — (input $/1M, output $/1M)
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    # OpenAI
    "gpt-5.4": (2.50, 15.0),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-pro": (30.0, 180.0),
    "gpt-5.4-thinking": (2.50, 15.0),
    # Google — placeholders, verify at impl time
    "gemini-3-pro": (5.0, 25.0),
    "gemini-3-flash": (0.50, 2.50),
}


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICES.get(model)
    if rates is None:
        return 0.0
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
