"""Context summarization for inter-agent communication."""

from __future__ import annotations


def summarize_task_output(text: str) -> str:
    """Extract structured content from task agent output, stripping verbose code/logs.

    Keeps JSON run record blocks and brief observations, removes code blocks and
    pip install output.
    """
    import re

    # Extract JSON blocks (the structured data we need)
    json_blocks = []
    for match in re.finditer(r"```(?:json|JSON)\s*\n(.*?)```", text, re.DOTALL):
        json_blocks.append(match.group(0))

    # Extract non-code text (observations, summaries)
    # Remove code blocks and their content
    cleaned = re.sub(
        r"```(?:python|bash|sh|pip)?\s*\n.*?```", "", text, flags=re.DOTALL
    )
    # Remove long pip install output lines
    cleaned = re.sub(
        r"(?:Successfully installed|Collecting|Downloading|Installing).*\n?",
        "",
        cleaned,
    )
    # Collapse multiple newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # Combine: observations + JSON blocks
    parts = []
    if cleaned:
        # Truncate observations to keep context reasonable
        if len(cleaned) > 1000:
            cleaned = cleaned[:1000] + "\n... (truncated)"
        parts.append(cleaned)
    parts.extend(json_blocks)

    return "\n\n".join(parts)
