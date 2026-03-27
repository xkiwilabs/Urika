"""Prompt loading from markdown files with variable substitution."""

from __future__ import annotations

from pathlib import Path


def load_prompt(
    path: Path,
    variables: dict[str, str] | None = None,
) -> str:
    """Load a markdown prompt file, optionally substituting variables.

    Variables use {name} format. Unmatched placeholders are left as-is.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    if not path.exists():
        msg = f"Prompt file not found: {path}"
        raise FileNotFoundError(msg)

    text = path.read_text(encoding="utf-8")

    if variables:
        text = text.format_map(_SafeDict(variables))

    return text


class _SafeDict(dict):  # type: ignore[type-arg]
    """Dict that returns the key as {key} for missing keys."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
