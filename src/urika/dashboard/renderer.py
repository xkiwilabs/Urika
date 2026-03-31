"""Render file content to HTML for dashboard display."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote


def _rewrite_image_paths(html: str, base_dir: str = "") -> str:
    """Rewrite relative image paths in rendered markdown to use /api/raw."""

    def _replace(match: re.Match[str]) -> str:
        src = match.group(1)
        if src.startswith(("http://", "https://", "/api/")):
            return match.group(0)  # Already absolute
        # Resolve relative path against the file's directory
        if base_dir:
            resolved = base_dir.rstrip("/") + "/" + src
            # Normalize (remove ../ segments)
            parts: list[str] = []
            for part in resolved.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part != ".":
                    parts.append(part)
            resolved = "/".join(parts)
        else:
            resolved = src
        return f'src="/api/raw?path={quote(resolved)}"'

    return re.sub(r'src="([^"]*)"', _replace, html)


def render_file_content(content: str, filename: str, base_dir: str = "") -> str:
    """Render file content to HTML based on file extension.

    Args:
        content: Raw file content as a string.
        filename: Filename (used to detect extension).
        base_dir: Directory containing the file (relative to project root),
            used to resolve relative image paths in markdown.

    Returns:
        HTML string suitable for display in the dashboard content panel.
    """
    ext = Path(filename).suffix.lower()

    if ext == ".md":
        import markdown

        html = markdown.markdown(content, extensions=["tables", "fenced_code"])
        return _rewrite_image_paths(html, base_dir)
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
