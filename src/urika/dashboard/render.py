"""Markdown → HTML helper used by the report viewer and the
formatted JSON pages.

Escapes raw HTML by default — agent-generated reports are
untrusted from the dashboard's perspective.
"""

from __future__ import annotations


def render_markdown(source: str | None) -> str:
    if not source:
        return ""
    try:
        import markdown
    except ImportError:
        # Graceful degradation: just escape and pre-wrap.
        from html import escape
        return f"<pre>{escape(source)}</pre>"

    md = markdown.Markdown(
        extensions=["fenced_code", "tables"],
    )
    # Pre-process: strip common dangerous tags
    import re
    cleaned = re.sub(
        r"<(script|iframe|object|embed)\b[^>]*>.*?</\1>",
        "",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"<(script|iframe|object|embed)\b[^>]*/?>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return md.convert(cleaned)
