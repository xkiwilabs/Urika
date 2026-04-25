"""Unit tests for the relative-path rewrite in render_markdown.

When a report renders, relative ``<img src>`` paths must be rewritten
to absolute artifact-viewer URLs so the browser can resolve them.
URLs that are already absolute (http://, https://, /) or data URIs
are left alone.
"""

from urika.dashboard.render import render_markdown


def test_rewrite_bare_filename_prefixed_with_base_url():
    """A bare ``fig.png`` resolves under base_url."""
    html = render_markdown(
        "![](fig.png)",
        base_url="/projects/alpha/experiments/exp-001/artifacts",
    )
    assert (
        'src="/projects/alpha/experiments/exp-001/artifacts/fig.png"'
        in html
    )


def test_rewrite_artifacts_prefix_folded():
    """``artifacts/fig.png`` should fold so it doesn't double-up."""
    html = render_markdown(
        "![](artifacts/fig.png)",
        base_url="/projects/alpha/experiments/exp-001/artifacts",
    )
    assert (
        'src="/projects/alpha/experiments/exp-001/artifacts/fig.png"'
        in html
    )
    # The unrewritten artifacts/ form must NOT survive.
    assert 'src="artifacts/fig.png"' not in html


def test_rewrite_leaves_absolute_urls_alone():
    """http(s):// and rooted / URLs must pass through unchanged."""
    html = render_markdown(
        "![](https://example.com/x.png)\n\n![](/static/y.png)",
        base_url="/projects/alpha/experiments/exp-001/artifacts",
    )
    assert 'src="https://example.com/x.png"' in html
    assert 'src="/static/y.png"' in html


def test_rewrite_leaves_data_uris_alone():
    """Inline data URIs must not be touched by the rewrite."""
    html = render_markdown(
        "![](data:image/png;base64,iVBORw0KGgo=)",
        base_url="/projects/alpha/experiments/exp-001/artifacts",
    )
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in html


def test_no_base_url_leaves_paths_unchanged():
    """When base_url is omitted, relative paths render verbatim."""
    html = render_markdown("![](fig.png)")
    assert 'src="fig.png"' in html


def test_rewrite_also_applies_to_anchor_hrefs():
    """Relative ``<a href>`` should be rewritten the same way."""
    html = render_markdown(
        "[link](report.txt)",
        base_url="/projects/alpha/experiments/exp-001/artifacts",
    )
    assert (
        'href="/projects/alpha/experiments/exp-001/artifacts/report.txt"'
        in html
    )
