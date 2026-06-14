"""WCAG-oriented accessibility checks on rendered dashboard HTML.

v0.10.0 Phase 8 (accessibility pass). These pin the structural a11y wins
that are unit-testable from rendered markup without a live browser:

  - the skip-to-content link is present, points at the main landmark, and is
    the FIRST focusable element in the body (so keyboard users hit it first);
  - the primary content is a ``<main id="main-content">`` landmark;
  - a sample of forms have every control labelled (``<label for>``, a wrapping
    ``<label>``, or ``aria-label``) — no placeholder-only inputs;
  - known icon-only buttons (modal close, theme toggle, methods sort-dir)
    carry an ``aria-label``;
  - the stylesheet ships the ``.skip-link`` rule and a global focus-visible
    outline for links + form controls;
  - the light/dark ``--text-subtle`` / ``--text-muted`` tokens meet WCAG AA
    contrast against their backgrounds.

A final live axe-core / WAVE pass against the booted app remains the
authoritative confirmation; this file covers the static, render-time classes.
"""

import re

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


# --------------------------------------------------------------------------
# contrast helper (WCAG relative luminance)
# --------------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# --------------------------------------------------------------------------
# skip link + main landmark
# --------------------------------------------------------------------------


def test_skip_link_present_and_first_focusable(audit_client):
    """The skip link exists, targets #main-content, and is the first
    focusable element (before the sidebar nav) in tab order."""
    r = audit_client.get("/projects")
    soup = BeautifulSoup(r.text, "html.parser")

    skip = soup.select_one("a.skip-link")
    assert skip is not None, "missing skip-to-content link"
    assert skip.get("href") == "#main-content"

    # First focusable element in the document should be the skip link.
    focusable = soup.select("a[href], button, input, select, textarea, [tabindex]")
    focusable = [
        el
        for el in focusable
        if not (el.has_attr("tabindex") and el["tabindex"] == "-1")
    ]
    assert focusable, "no focusable elements found"
    assert "skip-link" in (focusable[0].get("class") or []), (
        "skip link is not the first focusable element in tab order"
    )


def test_main_landmark_present(audit_client):
    """Primary content is wrapped in <main id='main-content'> with role=main,
    and the skip link target resolves to it."""
    r = audit_client.get("/projects")
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.find("main", id="main-content")
    assert main is not None, "missing <main id='main-content'> landmark"
    assert main.get("role") == "main"


# --------------------------------------------------------------------------
# form labels
# --------------------------------------------------------------------------


def _unlabelled_controls(html: str) -> list[str]:
    """Return a list of control descriptions that have NO accessible name."""
    soup = BeautifulSoup(html, "html.parser")
    bad = []
    label_fors = {lbl["for"] for lbl in soup.find_all("label") if lbl.has_attr("for")}
    for ctrl in soup.find_all(["input", "select", "textarea"]):
        if ctrl.name == "input" and ctrl.get("type") == "hidden":
            continue
        if ctrl.has_attr("aria-label") or ctrl.has_attr("aria-labelledby"):
            continue
        cid = ctrl.get("id")
        if cid and cid in label_fors:
            continue
        # wrapping <label> ancestor?
        if ctrl.find_parent("label") is not None:
            continue
        bad.append(f"<{ctrl.name} type={ctrl.get('type')} name={ctrl.get('name')}>")
    return bad


def test_new_project_form_controls_labelled(client_with_projects):
    """Every visible control on the projects page (incl. the New Project
    modal) has an accessible name."""
    r = client_with_projects.get("/projects")
    assert r.status_code == 200
    bad = _unlabelled_controls(r.text)
    assert bad == [], f"unlabelled controls on /projects: {bad}"


def test_project_settings_form_controls_labelled(audit_client):
    r = audit_client.get("/projects/alpha/settings")
    assert r.status_code == 200
    bad = _unlabelled_controls(r.text)
    assert bad == [], f"unlabelled controls on project settings: {bad}"


def test_global_settings_form_controls_labelled(settings_client):
    r = settings_client.get("/settings")
    assert r.status_code == 200
    bad = _unlabelled_controls(r.text)
    assert bad == [], f"unlabelled controls on global settings: {bad}"


def test_experiments_sort_control_labelled(audit_client):
    r = audit_client.get("/projects/alpha/experiments")
    bad = _unlabelled_controls(r.text)
    assert bad == [], f"unlabelled controls on experiments: {bad}"


def test_advisor_textarea_labelled(audit_client):
    r = audit_client.get("/projects/alpha/advisor")
    bad = _unlabelled_controls(r.text)
    assert bad == [], f"unlabelled controls on advisor: {bad}"


# --------------------------------------------------------------------------
# icon-only buttons
# --------------------------------------------------------------------------


def test_theme_toggle_has_aria_label(audit_client):
    r = audit_client.get("/projects")
    soup = BeautifulSoup(r.text, "html.parser")
    toggle = soup.select_one("button.theme-toggle")
    assert toggle is not None
    assert toggle.get("aria-label"), "theme toggle missing aria-label"


def test_modal_close_button_has_aria_label(audit_client):
    """The shared modal macro close button (× glyph) is labelled."""
    r = audit_client.get("/projects/alpha/experiments")
    soup = BeautifulSoup(r.text, "html.parser")
    closers = soup.select("button.modal-close")
    assert closers, "no modal close button rendered"
    for btn in closers:
        assert btn.get("aria-label"), "modal close button missing aria-label"


def test_methods_sort_direction_button_has_aria_label(audit_client):
    """The icon-only ↑/↓ sort-direction toggle uses a dynamic aria-label."""
    r = audit_client.get("/projects/alpha/methods")
    # The Alpine :aria-label binding renders verbatim in the source.
    assert ":aria-label=" in r.text and "Sort " in r.text


# --------------------------------------------------------------------------
# CSS: skip-link rule, focus-visible parity, contrast
# --------------------------------------------------------------------------


def _app_css() -> str:
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/static/app.css")
    assert r.status_code == 200
    return r.text


def test_app_css_defines_skip_link_and_focus_outline():
    css = _app_css()
    assert ".skip-link" in css, "missing .skip-link rule"
    # Global focus-visible outline for non-.btn interactive elements.
    assert "a:focus-visible" in css
    assert "input:focus-visible" in css
    assert "select:focus-visible" in css
    assert "textarea:focus-visible" in css


def test_app_css_underlines_links_in_text_blocks():
    """Links embedded in muted/body text must carry a non-colour affordance
    (underline) to satisfy WCAG 1.4.1, since accent-vs-muted is < 3:1."""
    css = _app_css()
    assert ".text-muted a:not(.btn)" in css
    assert ".empty-state a:not(.btn)" in css
    # The rule block sets text-decoration: underline.
    block = re.search(r"\.text-muted a:not\(\.btn\)[^{]*\{([^}]*)\}", css, re.S)
    assert block and "underline" in block.group(1)


def test_sidebar_active_uses_accent_hover_for_contrast():
    """The active sidebar link uses --accent-hover (not bare --accent), which
    clears 4.5:1 on the 10% accent tint in both themes."""
    css = _app_css()
    block = re.search(r"\.sidebar-link--active\s*\{([^}]*)\}", css, re.S)
    assert block, "missing .sidebar-link--active rule"
    assert "var(--accent-hover)" in block.group(1)


def _extract_token(css: str, scope_re: str, token: str) -> str:
    block = re.search(scope_re + r"\s*\{(.*?)\}", css, re.S)
    assert block, f"scope {scope_re!r} not found"
    m = re.search(rf"{re.escape(token)}\s*:\s*(#[0-9a-fA-F]{{6}})", block.group(1))
    assert m, f"token {token} not found in {scope_re}"
    return m.group(1)


def test_light_theme_subtle_muted_meet_wcag_aa():
    css = _app_css()
    # :root holds the light theme tokens.
    root = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    subtle = re.search(r"--text-subtle:\s*(#[0-9a-fA-F]{6})", root).group(1)
    muted = re.search(r"--text-muted:\s*(#[0-9a-fA-F]{6})", root).group(1)
    for token, value in (("subtle", subtle), ("muted", muted)):
        on_bg = _contrast(value, "#ffffff")
        on_elev = _contrast(value, "#f1f5f9")
        assert on_bg >= 4.5, (
            f"light --text-{token} {value} only {on_bg:.2f}:1 on #ffffff"
        )
        assert on_elev >= 4.5, (
            f"light --text-{token} {value} only {on_elev:.2f}:1 on #f1f5f9"
        )


def test_dark_theme_subtle_muted_meet_wcag_aa():
    css = _app_css()
    subtle = _extract_token(css, r'\[data-theme="dark"\]', "--text-subtle")
    muted = _extract_token(css, r'\[data-theme="dark"\]', "--text-muted")
    for token, value in (("subtle", subtle), ("muted", muted)):
        on_bg = _contrast(value, "#0a0a0a")
        on_elev = _contrast(value, "#1c1c1c")
        assert on_bg >= 4.5, (
            f"dark --text-{token} {value} only {on_bg:.2f}:1 on #0a0a0a"
        )
        assert on_elev >= 4.5, (
            f"dark --text-{token} {value} only {on_elev:.2f}:1 on #1c1c1c"
        )
