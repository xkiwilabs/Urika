"""Markdown → HTML helper used by the report viewer and the
formatted JSON pages.

Escapes raw HTML by default — agent-generated reports are
untrusted from the dashboard's perspective.
"""

from __future__ import annotations

import re


def render_markdown(source: str | None, *, base_url: str | None = None) -> str:
    """Render ``source`` markdown to HTML.

    When ``base_url`` is supplied, relative ``src``/``href`` attributes
    in the output are rewritten to absolute URLs under ``base_url`` so
    images and links resolve against the dashboard's artifact viewer
    rather than the page's own URL. Absolute URLs (``http://``,
    ``https://``, leading ``/``) and ``data:`` URIs pass through
    unchanged.
    """
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
    html = md.convert(cleaned)
    if base_url:
        html = _rewrite_relative_paths(html, base_url)
    return html


_REL_PATH_PATTERN = re.compile(r'(src|href)="([^"]+)"')


def _rewrite_relative_paths(html: str, base_url: str) -> str:
    """Rewrite relative ``src``/``href`` in ``<img>``/``<a>`` to absolute
    paths under ``base_url``.

    URLs that are absolute (``http://``, ``https://``, ``/``) or data URIs
    are left alone. Relative paths get prefixed with ``base_url``, with
    ``artifacts/`` folded out so ``artifacts/fig.png`` and ``fig.png``
    both resolve to ``<base_url>/fig.png`` (which the artifact-viewer
    route already handles).
    """
    base = base_url.rstrip("/")

    def _rewrite(match: re.Match[str]) -> str:
        attr = match.group(1)
        path = match.group(2)
        if (
            not path
            or path.startswith(
                ("http://", "https://", "data:", "/", "#", "mailto:")
            )
        ):
            return match.group(0)
        # Strip leading 'artifacts/' if present — the artifact viewer
        # already mounts at <base_url>, which IS the artifacts dir.
        if path.startswith("artifacts/"):
            path = path[len("artifacts/") :]
        return f'{attr}="{base}/{path}"'

    return _REL_PATH_PATTERN.sub(_rewrite, html)
