"""Audience-level instruction blocks for agent prompts.

Agents that produce narrative output (reports, presentations, finalized
write-ups) vary their prose style and depth by audience. The instruction
blocks here are injected into prompts as ``{audience_instructions}``.

The three levels map roughly to academic personas:

* ``novice`` — undergraduate with no background. Assumes nothing.
* ``standard`` — senior undergraduate / early Masters or PhD student.
  May have heard of common methods but doesn't know their specifics.
  This is the default.
* ``expert`` — PhD-level researcher in the sub-domain. Shared
  vocabulary, focus on results.
"""

from __future__ import annotations

AUDIENCE_INSTRUCTIONS: dict[str, str] = {
    "expert": (
        "Write for a PhD-level researcher in this sub-domain. Assume "
        "shared technical vocabulary; do not define standard methods or "
        "metrics. Focus on results, design choices, and trade-offs that "
        "another expert would care about — what's novel, what's "
        "surprising, what failed and why. Keep prose dense and concise. "
        "Speaker notes: 1-2 sentences per slide, only where non-obvious."
    ),
    "standard": (
        "Write for a senior undergraduate or early Masters / PhD student. "
        "Assume the reader has heard of common methods (e.g., random "
        "forests, mixed-effects models, cross-validation) but does NOT "
        "know their specifics — they cannot explain the method to "
        "someone else. For each method, walk through what it actually "
        "does, what assumptions it makes, what its key parameters or "
        "design choices mean, and why it's appropriate for this "
        "problem. Define domain-specific jargon on first use "
        "(e.g., 'LOSO (Leave-One-Session-Out)'). Slides stay clean and "
        "headline-style, but speaker notes carry the substance: 3-5 "
        "sentences per slide explaining what was done, why, and what "
        "the result means in plain language — enough that a reader "
        "with the right background but no prior exposure to the method "
        "can follow without external references. For methodology slides, "
        "describe the approach end-to-end in the notes so a presenter "
        "could speak to the slide cold."
    ),
    "novice": (
        "Write for an undergraduate with no statistics or machine "
        "learning background. Assume nothing. For each method or model, "
        "add a 'What this means' explainer slide before the results "
        "that use it. Define every technical term on first use. Explain "
        "why each approach was chosen and what the results mean "
        "practically, both in absolute terms and relative to baselines. "
        "Walk through results step by step. Include 1-2 extra slides "
        "per method explaining the approach conceptually before showing "
        "results. Speaker notes are long: 4-6 sentences per slide, "
        "written as if narrating to someone new to the field. Use "
        "analogies where they help — statistics mapped to everyday "
        "experience, ML models compared to familiar decision processes. "
        "Define any term you introduce, even ones you think are "
        "obvious. Avoid Greek letters and formulas in speaker notes."
    ),
}

_DEFAULT = "standard"


def get_audience_instruction(audience: str | None) -> str:
    """Return the instruction block for an audience, defaulting to 'standard'."""
    if not audience:
        return AUDIENCE_INSTRUCTIONS[_DEFAULT]
    return AUDIENCE_INSTRUCTIONS.get(audience, AUDIENCE_INSTRUCTIONS[_DEFAULT])


def format_audience_context(audience: str | None) -> str:
    """Build the per-turn user-message prefix carrying audience guidance.

    Returns a "Audience Style Guidance" block ready to prepend to the
    prompt sent to report/presentation/finalizer agents.

    Pre-this-helper the audience block was substituted directly into
    each system prompt at ``{audience_instructions}``. Three audience
    modes (novice / standard / expert) produced three different system
    prompts per role — a project that generated a report for one
    audience and then another paid full cache-creation cost on the
    second. With the audience block in the user message, the system
    prompt stays byte-stable across audiences and the cached prefix
    covers ~95-98% of the per-role base prompt.
    """
    block = get_audience_instruction(audience)
    return (
        "## Audience Style Guidance\n\n"
        f"{block}\n\n"
        "(Apply this audience style throughout the output. The system "
        "prompt may also reference \"audience guidance\" — that refers "
        "to this block.)\n\n"
        "---\n\n"
    )
