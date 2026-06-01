"""Single source of $-per-1M-tokens truth across all adapters.

Gemini rates verified against ai.google.dev/pricing on 2026-06-02.
Both Gemini rows quote the ≤200k-token tier — Google charges more
for prompts above that threshold, but Urika's agent calls stay well
under it; if that changes, add a tiered lookup rather than averaging.
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
    # Google — verified against ai.google.dev/pricing on 2026-06-02
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3.5-flash": (1.50, 9.0),
}


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICES.get(model)
    if rates is None:
        return 0.0
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
