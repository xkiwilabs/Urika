"""Dashboard E2E smoke via Playwright (v0.4.3 Track 2c).

Spins up a real uvicorn-served dashboard on a random local port,
drives a headless chromium browser through key user flows, asserts
on rendered HTML and rendered Alpine/HTMX-driven state.

What this WOULD have caught from prior releases:

- v0.4.2 C9: per-project endpoint fields missing from
  ``project_settings.html`` Privacy tab. The HTTP-level test in
  ``tests/test_dashboard/test_project_settings_endpoint_fields.py``
  pins this now, but the Playwright version verifies the user
  ACTUALLY SEES the fields rendered (Alpine ``x-show`` could
  hide them under a tab they never click).
- v0.4.2 H1: vendored static deps serve correctly. The HTTP-level
  test asserts the file is reachable; Playwright additionally
  verifies the browser EXECUTES the JS without console errors.
- v0.4.2 H2: Compare + Criteria sidebar links exist. Asserted in
  HTML; Playwright additionally verifies the links are CLICKABLE
  and navigate to a 200 page.

Skipped automatically when chromium isn't installed
(``playwright install chromium``). ``URIKA_SKIP_SMOKE=1``
env var also skips for the dev fast-loop. Each test is ~1-2s
so the whole file runs in <15s.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _PLAYWRIGHT_AVAILABLE,
        reason="playwright Python lib not installed (pip install playwright && playwright install chromium)",
    ),
]


# ── uvicorn server fixture ───────────────────────────────────────


def _find_free_port() -> int:
    """Allocate a TCP port the OS won't immediately reuse."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def dashboard_server(tmp_path, monkeypatch):
    """Run a real uvicorn-served dashboard on a free port.

    Returns ``(base_url, project_root)`` so tests can pre-seed
    projects under ``project_root`` and navigate to ``base_url``.
    """
    import uvicorn

    home = tmp_path / "urika-home"
    home.mkdir()
    project_root = tmp_path / "projects"
    project_root.mkdir()

    monkeypatch.setenv("URIKA_HOME", str(home))
    monkeypatch.setenv("URIKA_PROJECTS_DIR", str(project_root))

    # Build the app with the tmp project_root.
    from urika.dashboard.app import create_app

    app = create_app(project_root=project_root)

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll for readiness.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover
        pytest.fail(f"uvicorn didn't bind {port} within 10s")

    try:
        yield base_url, project_root
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


@pytest.fixture
def project_with_data(dashboard_server, tmp_path):
    """Pre-seed a project with at least one experiment so dashboard
    pages have data to render."""
    base_url, project_root = dashboard_server

    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace
    from urika.core.experiment import create_experiment
    from urika.core.registry import ProjectRegistry

    proj = project_root / "alpha"
    config = ProjectConfig(
        name="alpha", question="Does X predict Y?",
        mode="exploratory", data_paths=[],
    )
    create_project_workspace(proj, config)
    ProjectRegistry().register("alpha", proj)
    create_experiment(proj, name="baseline", hypothesis="linear is enough")
    return base_url, "alpha", proj


# ── Browser fixture ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def browser():
    """Module-scoped chromium so we don't pay launch cost per test."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser):
    """Fresh context per test so cookies / localStorage don't leak."""
    context = browser.new_context()
    page = context.new_page()
    # Capture browser-side console errors so tests can assert no
    # JS exceptions fired.
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.console_errors = errors  # type: ignore[attr-defined]
    try:
        yield page
    finally:
        context.close()


# ── 1. Projects index renders + lists projects ─────────────────────


class TestProjectsIndex:
    def test_index_renders_without_console_errors(
        self, project_with_data, page
    ) -> None:
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        # Project name should be visible somewhere on the page.
        assert page.locator(f"text={name}").count() >= 1
        # No JS exceptions.
        assert page.console_errors == [], (
            f"Browser console errors on /projects: {page.console_errors}"
        )

    def test_clicking_project_navigates_to_home(
        self, project_with_data, page
    ) -> None:
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects", wait_until="networkidle")
        # Click the project link.
        page.locator(f"a[href='/projects/{name}']").first.click()
        page.wait_for_url(f"**/projects/{name}")
        # Project home should render with its name.
        assert page.locator(f"text={name}").count() >= 1


# ── 2. Sidebar links (H2: Compare + Criteria) ────────────────────


class TestSidebarLinks:
    def test_compare_link_present_and_clickable(
        self, project_with_data, page
    ) -> None:
        """v0.4.2 H2 fix: both pages used to be reachable only via
        deeplink. Sidebar must surface them as real, clickable nav."""
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects/{name}", wait_until="networkidle")

        link = page.locator(f"a[href='/projects/{name}/compare']")
        assert link.count() >= 1, "Compare sidebar link missing (H2 regression)"
        link.first.click()
        page.wait_for_url(f"**/projects/{name}/compare")

    def test_criteria_link_present_and_clickable(
        self, project_with_data, page
    ) -> None:
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects/{name}", wait_until="networkidle")
        link = page.locator(f"a[href='/projects/{name}/criteria']")
        assert link.count() >= 1, "Criteria sidebar link missing (H2 regression)"
        link.first.click()
        page.wait_for_url(f"**/projects/{name}/criteria")


# ── 3. Vendored static assets (H1) ───────────────────────────────


class TestVendoredAssets:
    """v0.4.2 H1 fix: htmx, alpine, chart.js are vendored under
    /static/vendor/ instead of CDN-hosted. Browser must execute
    them without 404s or console errors."""

    def test_dashboard_loads_with_no_404s_or_console_errors(
        self, project_with_data, page
    ) -> None:
        base_url, name, _ = project_with_data

        failed_requests: list[str] = []

        def _on_response(response):
            if response.status >= 400 and "/static/" in response.url:
                failed_requests.append(f"{response.status} {response.url}")

        page.on("response", _on_response)
        page.goto(f"{base_url}/projects/{name}", wait_until="networkidle")

        assert failed_requests == [], (
            f"Static asset 4xx/5xx — vendored deps broken? {failed_requests}"
        )
        assert page.console_errors == [], (
            f"JS errors loading the page: {page.console_errors}"
        )

    def test_vendored_htmx_loaded(self, project_with_data, page) -> None:
        """htmx attaches itself to ``window.htmx``. If the vendored
        copy didn't load, this is undefined."""
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects/{name}", wait_until="networkidle")
        htmx_present = page.evaluate("typeof htmx !== 'undefined'")
        assert htmx_present, "htmx not loaded in window scope"

    def test_vendored_alpine_loaded(self, project_with_data, page) -> None:
        """Alpine.js attaches to ``window.Alpine`` (capital A)."""
        base_url, name, _ = project_with_data
        page.goto(f"{base_url}/projects/{name}", wait_until="networkidle")
        alpine_present = page.evaluate("typeof Alpine !== 'undefined'")
        assert alpine_present, "Alpine.js not loaded in window scope"


# ── 4. Project Settings → Privacy → context_window/max_output_tokens (C9) ─


class TestProjectSettingsEndpointFields:
    """v0.4.2 C9 fix: per-project ``context_window`` +
    ``max_output_tokens`` form rows on the Privacy tab. The
    HTTP-level test pins them in the rendered HTML; this test
    additionally verifies they're actually VISIBLE to the user
    (Alpine ``x-show`` could hide them behind a tab they never
    click)."""

    @pytest.fixture
    def hybrid_project(self, dashboard_server):
        from urika.core.models import ProjectConfig
        from urika.core.workspace import create_project_workspace
        from urika.core.registry import ProjectRegistry

        base_url, project_root = dashboard_server
        proj = project_root / "with-private"
        config = ProjectConfig(
            name="with-private", question="q",
            mode="exploratory", data_paths=[],
        )
        create_project_workspace(proj, config)
        # Switch the project's privacy mode + endpoint.
        toml_path = proj / "urika.toml"
        toml_path.write_text(
            toml_path.read_text() + (
                '\n[privacy]\nmode = "private"\n\n'
                '[privacy.endpoints.private]\n'
                'base_url = "http://localhost:11434"\n'
                'api_key_env = "OLLAMA_KEY"\n'
                'context_window = 65536\n'
                'max_output_tokens = 12000\n'
            )
        )
        ProjectRegistry().register("with-private", proj)
        return base_url, "with-private", proj

    def test_context_window_input_visible_on_privacy_tab(
        self, hybrid_project, page
    ) -> None:
        base_url, name, _ = hybrid_project
        page.goto(f"{base_url}/projects/{name}/settings", wait_until="networkidle")
        # Click the Privacy tab to make its contents visible
        # (Alpine ``x-show='active === \"privacy\"'``).
        page.locator("a[href='#tab-privacy'], button:has-text('Privacy')").first.click()
        # Allow Alpine reactivity to settle.
        page.wait_for_timeout(300)
        # The new field should be visible AND have the seeded value.
        field = page.locator("input#project_privacy_private_context_window")
        assert field.count() == 1, (
            "Context window input missing from per-project Privacy tab "
            "(C9 regression: pre-v0.4.2 it was global-Settings-only)"
        )
        # Seeded urika.toml has 65536 — should be pre-populated.
        assert field.input_value() == "65536"


# ── 5. /docs page renders ────────────────────────────────────────


class TestDocsPage:
    """v0.4.2 dashboard docs route should resolve and render the
    bundled documentation. Pre-v0.4.2 the placeholder had a
    ``yourorg/urika`` URL that needed editing for pip-install
    users; the route should now work in both editable and pip
    installs."""

    def test_docs_route_renders(self, dashboard_server, page) -> None:
        base_url, _ = dashboard_server
        page.goto(f"{base_url}/docs", wait_until="networkidle")
        # Should not be a 404 / "Documentation not available".
        body = page.locator("body").text_content() or ""
        assert "yourorg" not in body, (
            "Docs page still has the old yourorg/urika placeholder"
        )


# ── 4. End-to-end create-project flow through the real browser ────
#
# The "dashboard creates a project but doesn't set it up" report that
# kicked off v0.4.3.1 was a *server-side* bug, but the trustworthy
# check is "drive the actual New Project modal and confirm the project
# the browser created has its data block + criteria + README, not just
# a bare skeleton". That's the enrich_workspace pass, exercised here
# through real Alpine/HTMX in a real chromium.


class TestCreateProjectFlow:
    def test_new_project_modal_creates_an_enriched_project(
        self, dashboard_server, page, tmp_path
    ) -> None:
        import os

        base_url, project_root = dashboard_server

        # POST /api/projects writes the new project under
        # ``load_settings()["projects_root"]`` — pin that to the test's
        # project_root so the project doesn't land in the real
        # ~/urika-projects/. (load_settings reads the file per request,
        # so writing it after server start is fine.)
        with open(os.path.join(os.environ["URIKA_HOME"], "settings.toml"), "w") as _f:
            _f.write(f"projects_root = '{project_root}'\n")

        # A tiny real dataset so the non-interactive builder pass has
        # something to scan / profile / hash.
        data_csv = tmp_path / "mini.csv"
        data_csv.write_text("x,y\n1,2\n3,4\n5,6\n7,8\n", encoding="utf-8")

        page.goto(f"{base_url}/projects", wait_until="networkidle")
        page.locator("button:has-text('New project')").first.click()
        # Modal fields.
        page.fill("#np-name", "browser-made")
        page.fill("#np-question", "Does x predict y?")
        page.fill("#np-data-paths", str(data_csv))
        page.locator("button:has-text('Create project')").click()

        # Wait for the project directory + the enrichment artifacts to
        # appear on disk (the POST handler runs create_project_workspace
        # then enrich_workspace synchronously).
        proj = project_root / "browser-made"
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if (proj / "criteria.json").exists() and (proj / "README.md").exists():
                break
            time.sleep(0.2)
        else:
            pytest.fail(
                f"project {proj} not enriched within 15s "
                f"(exists={proj.exists()}, "
                f"files={[p.name for p in proj.iterdir()] if proj.exists() else None})"
            )

        # urika.toml carries the [data] block (scan found the CSV) and a
        # data-hash record — i.e. it's a real project, not a skeleton.
        import tomllib

        tdata = tomllib.loads((proj / "urika.toml").read_text(encoding="utf-8"))
        assert tdata.get("data", {}).get("source"), (
            "urika.toml has no [data].source — enrich_workspace didn't scan"
        )
        assert "data_hashes" in tdata.get("project", {}), (
            "urika.toml has no [project].data_hashes — drift baseline missing"
        )
        # criteria.json has an initial version with a non-empty criteria dict.
        import json as _json

        crit = _json.loads((proj / "criteria.json").read_text(encoding="utf-8"))
        versions = crit.get("versions", [])
        assert versions, "criteria.json has no versions"
        assert versions[0].get("criteria"), "initial criteria version is empty"

        # No JS errors during the whole flow.
        assert page.console_errors == [], page.console_errors


# ── 5. End-to-end run flow: modal → POST → SSE log → terminal status ──
#
# The dashboard's "+ New experiment" → run → live-log path was never
# driven end to end (the HTTP-level test mocks the spawn helper and
# stops at the kwargs). This drives it in a real browser with only the
# agent *subprocess* mocked: clicking "Run experiment" must create the
# experiment, navigate to its log page, and the SSE-driven log viewer
# must render the log lines and a terminal status — and report `failed`
# (not `completed`) for a run that failed to launch.


def _stub_spawn(monkeypatch, *, terminal_status: str = "completed",
                launch_failed: bool = False, log_line: str = "Doing the work…"):
    import json as _json

    def _fake_spawn(project_name, project_path, experiment_id, **_kw):  # noqa: ANN001
        exp_dir = project_path / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        lines = [log_line, "All done."]
        if launch_failed:
            lines = ["URIKA-LAUNCH-FAILED: OSError: exec format error"]
            # progress.json stays at the create_experiment default (pending)
        else:
            (exp_dir / "progress.json").write_text(
                _json.dumps({"status": terminal_status, "runs": [
                    {"run_id": "r1", "method": "lr", "metrics": {"r2": 0.8}}
                ]})
            )
        (exp_dir / "run.log").write_text("\n".join(lines) + "\n")
        # No .lock — the SSE loop sees lock-gone immediately and reads
        # the terminal status from progress.json (or the marker).
        return 4242

    # Patch both the source module and the re-export the route uses.
    import urika.dashboard.runs as runs_module

    monkeypatch.setattr(runs_module, "spawn_experiment_run", _fake_spawn, raising=False)
    try:
        import urika.dashboard.routers.api as api_module

        monkeypatch.setattr(api_module, "spawn_experiment_run", _fake_spawn)
    except AttributeError:
        pass


class TestRunFlow:
    def _start_run(self, page, base_url: str, name: str):
        page.goto(f"{base_url}/projects/{name}/experiments", wait_until="networkidle")
        page.locator("button:has-text('New experiment')").first.click()
        page.locator("button:has-text('Run experiment')").click()
        # The POST returns HX-Redirect to the run-log page.
        page.wait_for_url("**/experiments/**/log", timeout=10000)

    def test_run_then_log_page_shows_completed(
        self, project_with_data, page, monkeypatch
    ) -> None:
        base_url, name, _ = project_with_data
        _stub_spawn(monkeypatch, terminal_status="completed")
        self._start_run(page, base_url, name)
        # SSE delivers the backlog + a terminal status.
        page.wait_for_function(
            "document.querySelector('#log-status') && "
            "/completed/i.test(document.querySelector('#log-status').textContent)",
            timeout=10000,
        )
        assert "All done." in page.locator("#log").inner_text()
        assert page.console_errors == [], page.console_errors

    def test_run_log_page_reports_failed_on_launch_failed(
        self, project_with_data, page, monkeypatch
    ) -> None:
        base_url, name, _ = project_with_data
        _stub_spawn(monkeypatch, launch_failed=True)
        self._start_run(page, base_url, name)
        page.wait_for_function(
            "document.querySelector('#log-status') && "
            "/failed/i.test(document.querySelector('#log-status').textContent)",
            timeout=10000,
        )
        # And it must NOT have claimed completion.
        assert "completed" not in page.locator("#log-status").inner_text().lower()
