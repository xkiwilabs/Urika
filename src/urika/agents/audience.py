"""Audience-level instruction blocks for agent prompts.

Agents that produce narrative output (reports, presentations, finalized
write-ups) vary their prose style and depth by audience. The instruction
blocks here are injected into prompts as ``{audience_instructions}``.

``standard`` is the default for researchers who know general statistics
and ML but may not be experts in the specific sub-domain. It is more
verbose than ``expert`` (especially in speaker notes for slides) but
assumes more prior knowledge than ``novice``.
"""

from __future__ import annotations

AUDIENCE_INSTRUCTIONS: dict[str, str] = {
    "expert": (
        "Assume domain expertise. Use technical terminology freely. "
        "Focus on results and methodology. Keep explanations concise. "
        "Speaker notes: 1-2 sentences per slide, only where non-obvious."
    ),
    "standard": (
        "Write for a researcher familiar with general statistics and ML "
        "but not necessarily this specific sub-domain. Define domain-"
        "specific jargon on first use (e.g., 'LOSO (Leave-One-Session-Out)'). "
        "Slides remain concise, but speaker notes should be verbose: write "
        "2-4 sentences per slide explaining what was done, why, and what "
        "the result means in plain language. Notes are where the real "
        "explanation lives — the slide is the headline. For methodology "
        "slides, the notes should describe the approach end-to-end so a "
        "presenter could talk to the slide without extra prep."
    ),
    "novice": (
        "Explain every method in plain language as if the reader has no "
        "statistics or ML background. For each method or model, add a "
        "'What this means' explainer slide before the results that use it. "
        "Define all technical terms on first use. Explain why each approach "
        "was chosen and what the results mean practically, both in absolute "
        "terms and relative to baselines. Walk through results step by step. "
        "Include 1-2 extra slides per method explaining the approach "
        "conceptually before showing results. Speaker notes are long: "
        "4-6 sentences per slide, written as if narrating to someone new "
        "to the field. Use analogies where they help — statistics mapped "
        "to everyday experience, ML models compared to familiar decision "
        "processes. Define any term you introduce, even ones you think are "
        "obvious. Avoid Greek letters and formulas in speaker notes."
    ),
}

_DEFAULT = "standard"


def get_audience_instruction(audience: str | None) -> str:
    """Return the instruction block for an audience, defaulting to 'standard'."""
    if not audience:
        return AUDIENCE_INSTRUCTIONS[_DEFAULT]
    return AUDIENCE_INSTRUCTIONS.get(audience, AUDIENCE_INSTRUCTIONS[_DEFAULT])
