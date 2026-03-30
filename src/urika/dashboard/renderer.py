"""Render file content to HTML for dashboard display."""
from __future__ import annotations

from pathlib import Path


def render_file_content(content: str, filename: str) -> str:
    """Render file content to HTML based on file extension.

    Args:
        content: Raw file content as a string.
        filename: Filename (used to detect extension).

    Returns:
        HTML string suitable for display in the dashboard content panel.
    """
    ext = Path(filename).suffix.lower()

    if ext == ".md":
        import markdown

        return markdown.markdown(content, extensions=["tables", "fenced_code"])
    elif ext == ".json":
        try:
            import json

            parsed = json.loads(content)
            formatted = json.dumps(parsed, indent=2)
            return (
                f'<pre><code class="language-json">'
                f"{_escape_html(formatted)}"
                f"</code></pre>"
            )
        except (json.JSONDecodeError, ValueError):
            return f"<pre>{_escape_html(content)}</pre>"
    elif ext == ".py":
        return (
            f'<pre><code class="language-python">'
            f"{_escape_html(content)}"
            f"</code></pre>"
        )
    else:
        return f"<pre>{_escape_html(content)}</pre>"


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
