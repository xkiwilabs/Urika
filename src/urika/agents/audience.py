"""Audience-level instruction blocks for agent prompts."""

AUDIENCE_INSTRUCTIONS: dict[str, str] = {
    "expert": (
        "Assume domain expertise. Use technical terminology freely. "
        "Focus on results and methodology. Keep explanations concise."
    ),
    "novice": (
        "Explain every method in plain language as if the reader has no "
        "statistics or ML background. For each method or model, add a "
        "'What this means' explanation. Define all technical terms on first use. "
        "Explain why each approach was chosen and what the results mean practically. "
        "Walk through results step by step. For presentations, include 1-2 extra "
        "slides per method explaining the approach conceptually before showing results."
    ),
}
