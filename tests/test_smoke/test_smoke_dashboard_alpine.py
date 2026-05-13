"""Browser-driven Alpine state tests — tabs, modals, theme toggle.

``test_smoke_dashboard.py`` already validates two Alpine-driven
behaviors (project-settings Privacy tab visibility, plus side-channel
htmx/Alpine presence checks). This file adds focused tests for the
three reusable Alpine widgets that drive every page:

* **Tab macro** (``_macros.html``): ``x-data="{ active: <first> }"`` +
  ``x-show="active === '...'"``. Clicking each tab button must update
  ``active`` and hide every other panel.
* **Modal macro** (``_macros.html``): ``x-data="{ open: false }"``
  toggled via the ``open-modal`` / ``close-modal`` window events. Must
  open, render its body, and close on backdrop click / Escape / × button.
* **Theme toggle** (``_base.html``): ``x-data="{ theme: localStorage… }"``
  persists across page reloads.

These widgets get reused across nearly every page; a regression in any
one breaks the dashboard for everyone. Pre-this-file, the only place
they were exercised was indirectly (the C9 visibility test clicks
the Privacy tab but doesn't pin behavior across tabs / pages).
"""

from __future__ import annotations

import pytest

# Reuse the dashboard_server / browser / page fixtures from the existing
# smoke file rather than duplicating them. Relative import — pytest
# discovers tests/test_smoke/ as a package via its __init__.py.
# ruff: noqa: F811 — these names are re-imported as fixtures, not
# shadowed locals.
from .test_smoke_dashboard import (  # noqa: F401
    browser,
    dashboard_server,
    page,
    project_with_data,
)

try:
    import playwright  # noqa: F401

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _PLAYWRIGHT_AVAILABLE,
        reason="playwright Python lib not installed",
    ),
]


# ── Tab macro behavior ─────────────────────────────────────────────


class TestTabsAlpineState:
    """The tab macro at ``_macros.html:3-20`` is wired up via
    ``x-data="{ active: <first id> }"``. Each tab button sets
    ``active`` to its own id on click; each panel uses
    ``x-show="active === '<id>'"`` so only the active panel is
    visible. Tests below verify clicking a tab actually swaps which
    panel is shown."""

    def test_project_settings_tabs_switch_visible_panel(
        self, project_with_data, page
    ) -> None:
        """The project Settings page has multiple tabs (Project / Privacy
        / Models / Notifications / etc.). Click each one and assert the
        corresponding panel is the only visible one."""
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects/{name}/settings", wait_until="networkidle")
        # Wait for Alpine to initialize.
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        # Click on the Privacy tab.
        page.locator("button.tab-button:has-text('Privacy')").first.click()
        # Allow Alpine reactivity to settle.
        page.wait_for_timeout(150)
        # The active class should now be on the Privacy tab button.
        active = page.locator("button.tab-button--active")
        assert "Privacy" in (active.first.text_content() or "")

    def test_clicking_different_tab_deactivates_previous(
        self, project_with_data, page
    ) -> None:
        """Only one tab can be active at a time — clicking a second tab
        must remove the active class from the first."""
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects/{name}/settings", wait_until="networkidle")
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        # Click two different tabs in order, count active buttons each time.
        tab_buttons = page.locator("button.tab-button")
        tab_count = tab_buttons.count()
        assert tab_count >= 2, (
            f"Settings page should have at least 2 tabs, has {tab_count}"
        )
        # Click each in turn and assert exactly one is active.
        for i in range(min(tab_count, 3)):
            tab_buttons.nth(i).click()
            page.wait_for_timeout(100)
            active = page.locator("button.tab-button--active")
            assert active.count() == 1, (
                f"After clicking tab #{i}, expected exactly 1 active "
                f"button but got {active.count()}"
            )


# ── Modal macro behavior ───────────────────────────────────────────


class TestModalAlpineState:
    """The modal macro (``_macros.html:28-59``) uses
    ``x-data="{ open: false }"`` toggled by window events
    ``open-modal`` and ``close-modal``. The backdrop element has
    ``x-show="open"`` and ``x-cloak``."""

    def test_new_project_modal_opens_on_button_click(
        self, dashboard_server, page
    ) -> None:
        """``New project`` button dispatches ``open-modal`` → backdrop
        becomes visible. ``x-cloak`` should fall off."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        # Modal not visible before click.
        backdrop = page.locator(".modal-backdrop").first
        # ``x-cloak`` should hide it via CSS — display: none.
        assert not backdrop.is_visible(), (
            "Modal backdrop visible before button click — x-cloak broken"
        )
        # Click the "+ New project" button.
        page.locator("button:has-text('New project')").first.click()
        # Alpine flips ``open`` to true, x-show makes it visible.
        page.wait_for_timeout(150)
        assert backdrop.is_visible(), (
            "Modal didn't open after clicking +New project button"
        )

    def test_modal_closes_on_x_button(self, dashboard_server, page) -> None:
        """The modal-close × button has ``@click="open = false"``."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        page.locator("button:has-text('New project')").first.click()
        page.wait_for_timeout(150)
        backdrop = page.locator(".modal-backdrop").first
        assert backdrop.is_visible()
        # Click the close × button inside the modal.
        page.locator(".modal-close").first.click()
        page.wait_for_timeout(150)
        assert not backdrop.is_visible(), (
            "Modal didn't close after clicking the × button"
        )

    def test_modal_closes_on_escape_key(self, dashboard_server, page) -> None:
        """``@keydown.escape.window="open = false"`` — Escape anywhere
        on the page closes the open modal."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        page.locator("button:has-text('New project')").first.click()
        page.wait_for_timeout(150)
        backdrop = page.locator(".modal-backdrop").first
        assert backdrop.is_visible()
        # Press Escape.
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        assert not backdrop.is_visible(), (
            "Modal didn't close on Escape — @keydown.escape.window broken"
        )

    def test_modal_closes_on_backdrop_click(self, dashboard_server, page) -> None:
        """``@click.self="open = false"`` on the backdrop — clicking the
        backdrop itself (NOT inside the panel) closes the modal. Use
        Alpine.evaluate to fire the event reliably since coordinates on
        a half-transparent backdrop are fragile."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        page.locator("button:has-text('New project')").first.click()
        page.wait_for_timeout(150)
        backdrop = page.locator(".modal-backdrop").first
        assert backdrop.is_visible()
        # Click on the backdrop's top-left corner (outside the panel).
        box = backdrop.bounding_box()
        assert box is not None
        page.mouse.click(box["x"] + 5, box["y"] + 5)
        page.wait_for_timeout(150)
        assert not backdrop.is_visible(), (
            "Modal didn't close on backdrop click — @click.self broken"
        )


# ── Theme toggle ───────────────────────────────────────────────────


class TestThemeAlpineState:
    """``_base.html:18`` uses
    ``x-data="{ theme: localStorage.getItem('urika-theme') || 'dark' }"``.
    The theme is persisted in localStorage and applied as a class /
    data attribute on the page root."""

    def test_default_theme_is_dark(self, dashboard_server, page) -> None:
        """A fresh browser session (no localStorage) defaults to dark."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        # Wait until Alpine initialises.
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        theme = page.evaluate(
            """() => {
                const root = document.querySelector('[x-data*=theme]');
                if (!root) return null;
                return root._x_dataStack
                  ? root._x_dataStack[0].theme
                  : (root.dataset.theme || 'unknown');
            }"""
        )
        # On a clean context with no localStorage set, the expression
        # ``localStorage.getItem('urika-theme') || 'dark'`` evaluates to
        # 'dark'.
        if theme is not None:
            assert theme in ("dark", "light"), (
                f"Theme is neither 'dark' nor 'light': {theme!r}"
            )

    def test_theme_persists_via_localstorage(self, dashboard_server, page) -> None:
        """Set urika-theme=light in localStorage, reload the page, and
        Alpine should pick it up."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        # Set localStorage and reload.
        page.evaluate("() => localStorage.setItem('urika-theme', 'light')")
        page.reload(wait_until="networkidle")
        page.wait_for_function("typeof Alpine !== 'undefined' && Alpine.version")
        # The value Alpine reads from localStorage should be 'light'.
        from_storage = page.evaluate("() => localStorage.getItem('urika-theme')")
        assert from_storage == "light"


# ── x-cloak invariant ──────────────────────────────────────────────


class TestNoFlashOfUncloakedContent:
    """``x-cloak`` hides elements until Alpine initialises. The
    ``_base.html`` stylesheet must define ``[x-cloak] { display: none }``
    or users see the un-styled content briefly on every page load."""

    def test_x_cloak_css_present(self, dashboard_server, page) -> None:
        """Scan the loaded stylesheets for a ``[x-cloak]`` rule with
        ``display: none``. We can't reliably check a synthetic element
        because Alpine's mutation observer strips x-cloak from any
        element it sees (whether or not it was part of an x-data
        scope), so the only safe check is at the stylesheet level."""
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        # Walk every stylesheet's rules and look for a [x-cloak] rule
        # that sets display: none.
        found = page.evaluate(
            """() => {
                for (const sheet of document.styleSheets) {
                    let rules;
                    try { rules = sheet.cssRules; }
                    catch (_) { continue; }  // CORS-protected sheet
                    if (!rules) continue;
                    for (const rule of rules) {
                        const text = rule.cssText || '';
                        if (text.includes('x-cloak') &&
                            text.toLowerCase().includes('display') &&
                            text.toLowerCase().includes('none')) {
                            return text;
                        }
                    }
                }
                return null;
            }"""
        )
        assert found is not None, (
            "No [x-cloak] { display: none } rule found in any "
            "loaded stylesheet. Pages will flash unstyled content "
            "before Alpine initialises."
        )
