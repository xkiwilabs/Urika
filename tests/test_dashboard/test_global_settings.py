"""Tests for the global settings page and PUT /api/settings.

The page is a 4-tab layout (Privacy / Models / Preferences / Notifications)
that writes the full ~/.urika/settings.toml in a single PUT.
"""

from __future__ import annotations

import tomllib


# ---- Page rendering --------------------------------------------------------


def test_global_settings_page_returns_200_and_renders_form(settings_client):
    r = settings_client.get("/settings")
    assert r.status_code == 200
    body = r.text
    assert 'hx-put="/api/settings"' in body


def test_global_settings_page_has_four_tab_buttons(settings_client):
    """Page renders with 4 tabs: Privacy / Models / Preferences / Notifications."""
    body = settings_client.get("/settings").text
    for label in ("Privacy", "Models", "Preferences", "Notifications"):
        assert f">{label}</button>" in body, f"missing tab button: {label}"


def test_global_settings_uses_tabs_macro(settings_client):
    """The page uses the tabs macro from _macros.html (Alpine x-data scope)."""
    body = settings_client.get("/settings").text
    assert 'x-data="{ active:' in body
    assert "tab-button" in body


def test_global_settings_privacy_tab_multi_endpoint_editor(settings_client, tmp_path):
    """Privacy tab is a multi-endpoint editor.  Each row defines a
    named endpoint under ``[privacy.endpoints.<name>]``.  Pre-existing
    endpoints render as Alpine-bound rows so the user can edit / remove
    them; an "+ Add endpoint" button appends a fresh empty row.
    """
    # Pre-seed one endpoint so the page renders with a row pre-filled.
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # The Alpine x-data carries the named endpoints list.
    assert "endpoints:" in body
    # Pre-seeded endpoint surfaces in the Alpine state.
    assert "private" in body
    assert "http://localhost:11434" in body
    # The Privacy tab now serializes the endpoints array to a single
    # JSON field at submit time (avoids Alpine :name= timing edge cases
    # that prevented the form from including dynamically-added rows).
    # Each row has x-model bindings on its inputs.
    assert 'x-model="ep.name"' in body
    assert 'x-model="ep.base_url"' in body
    assert 'x-model="ep.api_key_env"' in body
    assert 'x-model="ep.default_model"' in body
    # The configRequest hook injects endpoints_json into the request.
    assert "endpoints_json" in body
    # The "+ Add endpoint" button is present.
    assert "+ Add endpoint" in body
    # Mode picker MUST NOT be on the global Privacy tab any more.
    assert 'name="privacy_mode"' not in body
    # Per-mode model fields are gone from this tab.
    assert 'name="privacy_open_model"' not in body
    assert 'name="privacy_private_model"' not in body
    assert 'name="privacy_hybrid_cloud_model"' not in body
    assert 'name="privacy_hybrid_private_url"' not in body
    assert 'name="privacy_hybrid_private_key_env"' not in body
    assert 'name="privacy_hybrid_private_model"' not in body
    # Legacy single-endpoint form fields are gone.
    assert 'name="privacy_private_url"' not in body
    assert 'name="privacy_private_key_env"' not in body


def test_global_settings_models_tab_has_per_mode_grids(settings_client, tmp_path):
    """Models tab renders three grids (open / private / hybrid).

    Per the per-mode shape redesign:
      * Open mode rows submit ``[model]`` (cloud-models <select>) plus
        a hidden ``[endpoint]=open``.  No endpoint <select>.
      * Private mode rows submit ``[endpoint]`` (a <select> of named
        private endpoints) plus a hidden ``[model]`` derived (via
        Alpine) from the chosen endpoint's default_model.
      * Hybrid mode rows submit BOTH ``[endpoint]`` and ``[model]``
        (the model widget swaps per chosen endpoint).
    """
    # Pre-seed a private endpoint with a default_model so the private
    # grid actually renders the per-agent rows (it shows an empty-state
    # otherwise).
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # Sub-tabs (UI-only; not posted to the server).
    assert ">Open</button>" in body
    assert ">Private</button>" in body
    assert ">Hybrid</button>" in body
    # One default-model field per mode.
    for mode_name in ("open", "private", "hybrid"):
        assert f'name="runtime_modes_{mode_name}_model"' in body
    agents = (
        "planning_agent",
        "task_agent",
        "evaluator",
        "advisor_agent",
        "tool_builder",
        "literature_agent",
        "presentation_agent",
        "report_agent",
        "project_builder",
        "data_agent",
        "finalizer",
    )
    # Open mode: each row sends a model field + hidden endpoint.
    for agent in agents:
        assert f'name="runtime_modes_open_models[{agent}][model]"' in body
        assert f'name="runtime_modes_open_models[{agent}][endpoint]"' in body
    # Private mode: each row sends an endpoint + (Alpine-derived) model.
    for agent in agents:
        assert f'name="runtime_modes_private_models[{agent}][model]"' in body
        assert (
            f'name="runtime_modes_private_models[{agent}][endpoint]"' in body
        )
    # Hybrid mode: each row sends both endpoint and model.
    for agent in agents:
        assert f'name="runtime_modes_hybrid_models[{agent}][model]"' in body
        assert f'name="runtime_modes_hybrid_models[{agent}][endpoint]"' in body


def _seed_private_endpoint(tmp_path, *, with_default_model: bool = True):
    """Pre-seed ~/.urika/settings.toml with a single ``private`` endpoint
    so the per-agent endpoint dropdowns have a value to render.

    ``with_default_model`` controls whether the endpoint also gets a
    ``default_model`` — required for the private-mode grid to render
    its per-agent rows (the grid shows an empty-state otherwise).
    """
    body = (
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
    )
    if with_default_model:
        body += 'default_model = "qwen3:14b"\n'
    (tmp_path / "home" / "settings.toml").write_text(body, encoding="utf-8")


def test_global_settings_models_tab_hybrid_data_agent_locked_private(
    settings_client, tmp_path
):
    """In the hybrid grid, data_agent's Endpoint <select> is hard-locked
    to private (only ``private`` option, disabled). tool_builder
    defaults to private but the user can switch it to open — its
    <select> includes BOTH options.

    The visible Endpoint <select> in hybrid is a UI category dropdown
    (open / private) with NO ``name=`` attribute — it doesn't carry a
    server value directly. Hidden inputs (``name="runtime_modes_hybrid_models[<agent>][endpoint]"``)
    are bound (Alpine) to the local state.
    """
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Scope to the hybrid grid (open + private grids share the DOM
    # under x-show, but each row's hidden [endpoint] input bears the
    # right name regardless of which grid is active).
    grid_match = re.search(
        r'<h4>Hybrid mode</h4>.*?</table>', body, flags=re.DOTALL
    )
    assert grid_match is not None
    grid = grid_match.group(0)

    # Locate the data_agent row.
    m = re.search(
        r'<tr[^>]*x-data=[^>]*>\s*<td><code>data_agent</code></td>'
        r'.*?'
        r'name="runtime_modes_hybrid_models\[data_agent\]\[endpoint\]"',
        grid,
        flags=re.DOTALL,
    )
    assert m is not None, "data_agent row not found"
    block = m.group(0)
    # The visible category select for data_agent: only private + disabled.
    m_sel = re.search(
        r'<select[^>]*x-model="cat"[^>]*>(.*?)</select>',
        block,
        flags=re.DOTALL,
    )
    assert m_sel is not None
    sel_open_tag = m_sel.group(0).split(">", 1)[0]
    assert "disabled" in sel_open_tag
    assert 'value="private"' in m_sel.group(1)
    assert 'value="open"' not in m_sel.group(1)

    # tool_builder row: NOT locked. Visible select has both open + private.
    m = re.search(
        r'<tr[^>]*x-data=[^>]*>\s*<td><code>tool_builder</code></td>'
        r'.*?'
        r'name="runtime_modes_hybrid_models\[tool_builder\]\[endpoint\]"',
        grid,
        flags=re.DOTALL,
    )
    assert m is not None, "tool_builder row not found"
    block = m.group(0)
    m_sel = re.search(
        r'<select[^>]*x-model="cat"[^>]*>(.*?)</select>',
        block,
        flags=re.DOTALL,
    )
    assert m_sel is not None
    sel_open_tag = m_sel.group(0).split(">", 1)[0]
    assert "disabled" not in sel_open_tag
    assert 'value="private"' in m_sel.group(1)
    assert 'value="open"' in m_sel.group(1)


def test_global_settings_models_tab_private_mode_hides_open_for_all_agents(
    settings_client, tmp_path
):
    """In the private grid, every agent's Model (Endpoint) <select>
    offers ONLY named private endpoints — the cloud option never
    appears. The hidden [endpoint] input mirrors the chosen private
    endpoint name via Alpine ``:value="ep"``."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Scope to the private-mode grid (all three grids share the DOM,
    # toggled via x-show). The grid is delimited by its <h4> header
    # and the closing </table>.
    grid_match = re.search(
        r'<h4>Private mode</h4>.*?</table>', body, flags=re.DOTALL
    )
    assert grid_match is not None
    grid = grid_match.group(0)
    for agent in ("task_agent", "evaluator", "advisor_agent"):
        # Each row contains: <code>agent</code> ... a visible <select>
        # ... two hidden inputs (one for [endpoint], one for [model]).
        m = re.search(
            r'<td><code>' + agent + r'</code></td>'
            r'.*?'
            r'name="runtime_modes_private_models\[' + agent + r'\]\[model\]"',
            grid,
            flags=re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        # Private endpoints appear as options; cloud "open" does not.
        assert 'value="private"' in block
        assert 'value="open"' not in block
        # The hidden [endpoint] input is :value-bound to ``ep``.
        assert (
            'name="runtime_modes_private_models['
            + agent
            + '][endpoint]"' in block
        )


def test_global_settings_models_open_default_model_is_select(settings_client):
    """Open mode's per-mode default model field is a <select> dropdown
    of known Claude models — not a free-text input."""
    import re

    body = settings_client.get("/settings").text
    # The <select> wraps known cloud model options.
    m = re.search(
        r'<select[^>]*name="runtime_modes_open_model"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, "open-mode default model is not a <select>"
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block
    assert 'value="claude-sonnet-4-5"' in block
    assert 'value="claude-haiku-4-5"' in block


def test_global_settings_models_hybrid_default_model_is_select(
    settings_client, tmp_path
):
    """Hybrid mode's per-mode default model field is a <select> of
    known Claude models (the cloud-side default). Hybrid mode is only
    enabled when at least one private endpoint exists, so we seed
    one before checking."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_modes_hybrid_model"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, "hybrid-mode default model is not a <select>"
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block


def test_global_settings_models_open_mode_per_agent_model_is_cloud_select(
    settings_client,
):
    """Open mode rows are all cloud (no endpoint column).  Each row's
    model field is a <select> of known cloud Claude models — the user
    is always picking a Claude variant in open mode."""
    import re

    body = settings_client.get("/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_modes_open_models\[task_agent\]\[model\]"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, (
        "open-mode per-agent model field should be a <select> of cloud models"
    )
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block
    assert 'value="claude-sonnet-4-5"' in block
    assert 'value="claude-haiku-4-5"' in block


def test_global_settings_models_open_mode_endpoint_cell_is_text(
    settings_client,
):
    """In open mode every agent uses the cloud endpoint, so the
    Endpoint cell renders the literal text ``open`` (a read-only
    `<span>`) plus a hidden ``[endpoint]=open`` input. There is NO
    <select> bearing the endpoint field name."""
    import re

    body = settings_client.get("/settings").text
    # Hidden input present, value "open".
    m = re.search(
        r'<input[^>]*type="hidden"[^>]*name="runtime_modes_open_models\[task_agent\]\[endpoint\]"[^>]*value="open"',
        body,
    )
    assert m is not None
    # No <select> for the open-mode endpoint — read-only text only.
    m_select = re.search(
        r'<select[^>]*name="runtime_modes_open_models\[task_agent\]\[endpoint\]"',
        body,
    )
    assert m_select is None
    # The literal "open" text is rendered in the Endpoint column.
    assert "<span>open</span>" in body


def test_global_settings_models_private_mode_endpoint_cell_is_text(
    settings_client, tmp_path
):
    """Private mode's Endpoint cell is the literal text ``private`` (a
    read-only `<span>`), NOT a dropdown. The Model column ("Model
    (Endpoint)") drives both the [endpoint] and [model] hidden inputs.
    """
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # The visible Model select has no name= (Alpine drives hidden inputs).
    # Locate the task_agent row and assert its options carry the
    # "<default_model> (<endpoint_name>)" labels.
    m = re.search(
        r'<td><code>task_agent</code></td>'
        r'.*?'
        r'name="runtime_modes_private_models\[task_agent\]\[model\]"',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    # Model select option label is "<default_model> (<endpoint_name>)".
    assert "qwen3:14b (private)" in block
    # Both hidden inputs are present: [endpoint] (Alpine :value="ep")
    # and [model] (Alpine :value=opts.find(...).default_model).
    assert (
        'name="runtime_modes_private_models[task_agent][endpoint]"' in block
    )
    assert (
        'name="runtime_modes_private_models[task_agent][model]"' in block
    )
    # The Endpoint cell renders the literal text "private".
    # The row's <td><span>private</span></td> sits between the agent
    # <code> and the Model <select>.
    assert "<span>private</span>" in block


def test_global_settings_models_private_mode_empty_state_when_no_endpoints(
    settings_client,
):
    """When no private endpoints have a default_model defined, the
    private grid renders an empty state pointing at the Privacy tab.
    Same applies to the Hybrid grid."""
    body = settings_client.get("/settings").text
    # Empty-state phrasing for both private and hybrid.
    assert "Private mode is unavailable" in body
    assert "Hybrid mode is unavailable" in body
    assert "Add one on the Privacy tab" in body


def test_global_settings_models_hybrid_row_has_alpine_state(
    settings_client, tmp_path
):
    """Hybrid rows carry an Alpine ``x-data`` block whose ``cat`` field
    drives the Endpoint category (open / private) and the conditional
    Model widget (cloud-models <select> vs named-private-endpoint
    <select>). ``ep`` and ``cloud_model`` track the chosen values."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Alpine state declared per row — task_agent is non-forced.
    m = re.search(
        r'<tr[^>]*x-data=\'{ cat:[^\']*\'[^>]*>\s*<td><code>task_agent</code></td>',
        body,
    )
    assert m is not None
    # The hybrid row carries hidden inputs for both [endpoint] and
    # [model] — Alpine :value bindings resolve them based on ``cat``.
    assert (
        'name="runtime_modes_hybrid_models[task_agent][model]"' in body
    )
    assert (
        'name="runtime_modes_hybrid_models[task_agent][endpoint]"' in body
    )


def test_global_settings_models_private_default_is_endpoint_select(
    settings_client, tmp_path
):
    """Private mode's per-mode default field is a <select> of the
    user's defined private endpoints (label = '<default_model>
    (<endpoint_name>)', value = the endpoint's default_model). The
    first defined endpoint is selected by default."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_modes_private_model"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, "private-mode default is not a <select>"
    block = m.group(1)
    # The seeded endpoint shows up with model + endpoint name in the label.
    assert "qwen3:14b (private)" in block
    # The legacy text input shape is gone.
    m_input = re.search(
        r'<input[^>]*type="text"[^>]*name="runtime_modes_private_model"',
        body,
    )
    assert m_input is None


def test_global_settings_models_tab_hybrid_mode_offers_both_endpoints(
    settings_client, tmp_path
):
    """Hybrid mode's Endpoint cell is a UI category dropdown (open /
    private) — non-forced agents can pick either category. The model
    column then swaps shape based on the choice."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Locate the task_agent row block.
    m = re.search(
        r'<tr[^>]*x-data=[^>]*>\s*<td><code>task_agent</code></td>'
        r'.*?'
        r'name="runtime_modes_hybrid_models\[task_agent\]\[endpoint\]"',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    # The visible category select has both options.
    assert 'value="open"' in block
    assert 'value="private"' in block


def test_global_settings_models_tab_hybrid_mode_lists_all_named_endpoints(
    settings_client, tmp_path
):
    """When multiple named endpoints are defined, the hybrid-mode
    Model (Endpoint) dropdown (visible only when category=private)
    lists every one of them. The Endpoint category dropdown still
    only carries the two UI categories (open / private)."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n'
        'default_model = "llama3:8b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # The task_agent row's full fragment (from agent <code> through
    # its hidden [model] input) carries every named endpoint as a
    # private-variant model option, plus the cloud category option.
    m = re.search(
        r'<td><code>task_agent</code></td>'
        r'.*?'
        r'name="runtime_modes_hybrid_models\[task_agent\]\[model\]"',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    # Category select: both UI categories.
    assert 'value="open"' in block
    # Private-variant model select: every defined endpoint.
    assert 'value="private"' in block
    assert 'value="ollama"' in block
    # Labels carry the bundled default_model.
    assert "qwen3:14b (private)" in block
    assert "llama3:8b (ollama)" in block


def test_global_settings_models_tab_private_mode_lists_all_named_endpoints(
    settings_client, tmp_path
):
    """Private mode's Model (Endpoint) <select> lists every defined
    private endpoint (the model field IS the endpoint chooser). No
    ``open`` option appears."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n'
        'default_model = "llama3:8b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # Scope to the private-mode grid.
    grid_match = re.search(
        r'<h4>Private mode</h4>.*?</table>', body, flags=re.DOTALL
    )
    assert grid_match is not None
    grid = grid_match.group(0)
    # task_agent row block (agent <code> through hidden [model] input).
    m = re.search(
        r'<td><code>task_agent</code></td>'
        r'.*?'
        r'name="runtime_modes_private_models\[task_agent\]\[model\]"',
        grid,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    assert 'value="open"' not in block
    assert 'value="private"' in block
    assert 'value="ollama"' in block
    # Labels carry the default_model in parens.
    assert "qwen3:14b (private)" in block
    assert "llama3:8b (ollama)" in block


# ---- New always-three-columns layout: explicit shape assertions ---------


def test_global_settings_models_open_mode_three_column_table(
    settings_client,
):
    """Open mode grid is a 3-column table: Agent / Endpoint / Model.
    Endpoint cell shows literal "open" text; Model cell is a cloud-
    models <select>."""
    import re

    body = settings_client.get("/settings").text
    # Locate the open grid (its h4 anchors it).
    m = re.search(
        r'<h4>Open mode</h4>.*?</table>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    grid = m.group(0)
    # 3-column header.
    assert "<th>Agent</th>" in grid
    assert "<th>Endpoint</th>" in grid
    assert "<th>Model</th>" in grid
    # Each row has the literal "open" span and a hidden [endpoint]=open.
    assert "<span>open</span>" in grid
    assert (
        'name="runtime_modes_open_models[task_agent][endpoint]"' in grid
    )
    # Hidden input carries value="open" for the task_agent row.
    assert re.search(
        r'<input[^>]*type="hidden"[^>]*'
        r'name="runtime_modes_open_models\[task_agent\]\[endpoint\]"'
        r'[^>]*value="open"',
        grid,
        flags=re.DOTALL,
    ) is not None
    # Model select carries cloud models.
    m_sel = re.search(
        r'<select[^>]*name="runtime_modes_open_models\[task_agent\]\[model\]"[^>]*>(.*?)</select>',
        grid,
        flags=re.DOTALL,
    )
    assert m_sel is not None
    assert 'value="claude-opus-4-7"' in m_sel.group(1)


def test_global_settings_models_private_mode_three_column_table(
    settings_client, tmp_path
):
    """Private mode grid is a 3-column table: Agent / Endpoint /
    Model (Endpoint). Endpoint cell shows literal "private" text;
    Model cell is a <select> of named private endpoints."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    m = re.search(
        r'<h4>Private mode</h4>.*?</table>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    grid = m.group(0)
    # 3-column header — Model column header is "Model (Endpoint)".
    assert "<th>Agent</th>" in grid
    assert "<th>Endpoint</th>" in grid
    assert "<th>Model (Endpoint)</th>" in grid
    # Endpoint cell renders the literal "private" text.
    assert "<span>private</span>" in grid
    # Two hidden inputs per row carry [endpoint] and [model].
    assert (
        'name="runtime_modes_private_models[task_agent][endpoint]"' in grid
    )
    assert (
        'name="runtime_modes_private_models[task_agent][model]"' in grid
    )


def test_global_settings_models_hybrid_mode_three_column_table(
    settings_client, tmp_path
):
    """Hybrid mode grid is a 3-column table: Agent / Endpoint /
    Model (Endpoint). Endpoint cell is a UI category <select> (open
    / private). Model cell is conditional."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    m = re.search(
        r'<h4>Hybrid mode</h4>.*?</table>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    grid = m.group(0)
    # 3-column header (with explicit per-column widths so endpoint and
    # model columns balance equally).
    assert ">Agent</th>" in grid
    assert ">Endpoint</th>" in grid
    assert ">Model (Endpoint)</th>" in grid
    # task_agent's Endpoint column is a UI category <select> with two
    # options (open / private) — the visible select has no name= and
    # is x-modeled to the local ``cat`` variable.
    m_row = re.search(
        r'<tr[^>]*x-data=[^>]*>\s*<td><code>task_agent</code></td>'
        r'.*?'
        r'name="runtime_modes_hybrid_models\[task_agent\]\[endpoint\]"',
        grid,
        flags=re.DOTALL,
    )
    assert m_row is not None
    row_block = m_row.group(0)
    assert 'x-model="cat"' in row_block
    assert 'value="open"' in row_block
    assert 'value="private"' in row_block


def test_global_settings_models_hybrid_data_agent_locked_only_private(
    settings_client, tmp_path
):
    """In hybrid mode, data_agent's Endpoint <select> is `disabled`
    and offers ONLY ``private``."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Scope to the hybrid grid first.
    grid_match = re.search(
        r'<h4>Hybrid mode</h4>.*?</table>', body, flags=re.DOTALL
    )
    assert grid_match is not None
    grid = grid_match.group(0)
    # Locate data_agent's row block.
    m = re.search(
        r'<tr[^>]*x-data=[^>]*>\s*<td><code>data_agent</code></td>'
        r'.*?</tr>',
        grid,
        flags=re.DOTALL,
    )
    assert m is not None
    row = m.group(0)
    # Visible category select: disabled + only private option.
    m_sel = re.search(
        r'<select[^>]*x-model="cat"[^>]*>(.*?)</select>',
        row,
        flags=re.DOTALL,
    )
    assert m_sel is not None
    sel_open_tag = m_sel.group(0).split(">", 1)[0]
    assert "disabled" in sel_open_tag
    assert 'value="private"' in m_sel.group(1)
    assert 'value="open"' not in m_sel.group(1)


def test_global_settings_models_hybrid_tool_builder_defaults_private(
    settings_client, tmp_path
):
    """In hybrid mode, tool_builder's Endpoint <select> has BOTH
    options and the ``private`` option starts selected."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Scope to the hybrid grid first.
    grid_match = re.search(
        r'<h4>Hybrid mode</h4>.*?</table>', body, flags=re.DOTALL
    )
    assert grid_match is not None
    grid = grid_match.group(0)
    m = re.search(
        r'<tr[^>]*x-data=[^>]*>\s*<td><code>tool_builder</code></td>'
        r'.*?</tr>',
        grid,
        flags=re.DOTALL,
    )
    assert m is not None
    row = m.group(0)
    # Visible category select: both options, NOT disabled.
    m_sel = re.search(
        r'<select[^>]*x-model="cat"[^>]*>(.*?)</select>',
        row,
        flags=re.DOTALL,
    )
    assert m_sel is not None
    open_tag = m_sel.group(0).split(">", 1)[0]
    sel_body = m_sel.group(1)
    assert "disabled" not in open_tag
    assert 'value="open"' in sel_body
    assert 'value="private"' in sel_body
    # ``private`` option is pre-selected.
    m_priv = re.search(
        r'<option value="private"[^>]*>private</option>',
        sel_body,
    )
    assert m_priv is not None
    assert "selected" in m_priv.group(0)


def test_global_settings_preferences_tab_has_expected_fields(settings_client):
    """Preferences tab exposes audience, max_turns, web_search, venv."""
    body = settings_client.get("/settings").text
    assert 'name="default_audience"' in body
    assert 'name="default_max_turns"' in body
    assert 'name="web_search"' in body
    assert 'name="venv"' in body


def test_global_settings_venv_checkbox_unset_means_unchecked(settings_client):
    """venv default is OFF — when settings.toml has no venv preference,
    the checkbox renders unchecked. (The default is to use the global
    urika venv, not per-project.)"""
    import re

    body = settings_client.get("/settings").text
    m = re.search(r'<input[^>]*name="venv"[^>]*>', body)
    assert m is not None, "venv checkbox not found"
    assert "checked" not in m.group(0)


def test_global_settings_notifications_tab_has_channels(settings_client):
    """Notifications tab exposes per-channel CONNECTION fields plus
    a per-channel ``auto_enable`` checkbox that decides whether new
    projects start with the channel turned on. Per-project run-time
    enablement still lives on the project Notifications tab.
    """
    body = settings_client.get("/settings").text
    # Email — connection details
    assert 'name="notifications_email_from"' in body
    assert 'name="notifications_email_to"' in body
    assert 'name="notifications_email_smtp_host"' in body
    assert 'name="notifications_email_smtp_port"' in body
    # Slack — connection details
    assert 'name="notifications_slack_channel"' in body
    assert 'name="notifications_slack_token_env"' in body
    # Telegram — connection details
    assert 'name="notifications_telegram_chat_id"' in body
    assert 'name="notifications_telegram_bot_token_env"' in body
    # Per-channel auto_enable checkboxes (NEW)
    assert 'name="notifications_email_auto_enable"' in body
    assert 'name="notifications_slack_auto_enable"' in body
    assert 'name="notifications_telegram_auto_enable"' in body
    # The legacy per-channel "enabled" checkboxes are still NOT on the
    # global form — channel enablement is per-project.
    assert 'name="notifications_email_enabled"' not in body
    assert 'name="notifications_slack_enabled"' not in body
    assert 'name="notifications_telegram_enabled"' not in body


def test_global_settings_renders_send_test_notification_button(settings_client):
    """The Notifications tab includes a Send-test button wired to
    ``POST /api/settings/notifications/test-send`` so users can verify
    their channel config without leaving the page. The button uses the
    same Alpine ``endpoint-test`` pattern as the Privacy tab's Test
    endpoint button."""
    body = settings_client.get("/settings").text
    assert "Send test notification" in body
    assert "/api/settings/notifications/test-send" in body
    # Click handler is wired and posts the surrounding form's values.
    assert "sendTest()" in body


def test_global_settings_auto_enable_checkbox_reflects_saved_value(
    settings_client, tmp_path
):
    """When ``[notifications.email].auto_enable`` is true in settings.toml,
    the checkbox renders pre-checked."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        "[notifications.email]\n"
        'from_addr = "x@y.com"\n'
        "auto_enable = true\n",
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    m = re.search(
        r'<input[^>]*name="notifications_email_auto_enable"[^>]*>', body
    )
    assert m is not None, "email auto_enable checkbox not found"
    assert "checked" in m.group(0)

    # Slack/telegram unset → unchecked.
    m_slack = re.search(
        r'<input[^>]*name="notifications_slack_auto_enable"[^>]*>', body
    )
    assert m_slack is not None
    assert "checked" not in m_slack.group(0)


# ---- Privacy tab round-trips -----------------------------------------------


def test_global_settings_put_single_endpoint_writes_section(
    settings_client, tmp_path
):
    """Submitting a single named endpoint via the multi-endpoint form
    writes ``[privacy.endpoints.<name>]``. No mode is written to globals."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["privacy"]["endpoints"]["private"]["base_url"]
        == "http://localhost:11434"
    )
    # No system-wide default mode is persisted any more.
    assert "mode" not in s.get("privacy", {})


def test_global_settings_put_multiple_endpoints_writes_each(
    settings_client, tmp_path
):
    """Submitting two endpoints (private + ollama) writes both blocks
    under ``[privacy.endpoints]``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "qwen3:14b",
            "endpoints[1][name]": "ollama",
            "endpoints[1][base_url]": "http://localhost:11435",
            "endpoints[1][api_key_env]": "",
            "endpoints[1][default_model]": "llama3:8b",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    eps = s["privacy"]["endpoints"]
    assert eps["private"]["base_url"] == "http://localhost:11434"
    assert eps["private"]["default_model"] == "qwen3:14b"
    assert eps["ollama"]["base_url"] == "http://localhost:11435"
    assert eps["ollama"]["default_model"] == "llama3:8b"


def test_global_settings_put_omitting_endpoint_deletes_it(
    settings_client, tmp_path
):
    """An endpoint present in the previous TOML but absent from the
    new submission is REMOVED — diff-apply semantics so the user can
    delete an endpoint by simply unmounting its row."""
    # Pre-seed two endpoints.
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n',
        encoding="utf-8",
    )
    # Submit only one of the two — the other should be deleted.
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    eps = s["privacy"]["endpoints"]
    assert "private" in eps
    assert "ollama" not in eps


def test_global_settings_put_reserved_endpoint_name_rejected(settings_client):
    """The name ``open`` is reserved (it's the implicit cloud endpoint
    name) and submitting it returns 422."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "open",
            "endpoints[0][base_url]": "http://example.com",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_invalid_endpoint_name_rejected(settings_client):
    """An endpoint name with spaces (or any character outside
    ``[a-z0-9_-]``) returns 422."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "Has Spaces",
            "endpoints[0][base_url]": "http://example.com",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_drops_legacy_privacy_mode(settings_client, tmp_path):
    """Saving never writes [privacy].mode — and an existing legacy
    value is dropped on the next save."""
    # Pre-seed with a legacy [privacy].mode that older code wrote
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy]\nmode = "private"\n', encoding="utf-8"
    )
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert "mode" not in s.get("privacy", {})


def test_global_settings_put_ignores_unknown_privacy_mode_field(settings_client):
    """Old clients posting a privacy_mode= value get ignored, not 422.
    The field is no longer part of the global form."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "bogus",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200


# ---- Models tab round-trip --------------------------------------------------


def test_global_settings_put_per_agent_override_writes_runtime_models(
    settings_client, tmp_path
):
    """[runtime.models.<agent>] is populated from model[<agent>] form fields.

    Requires the named endpoint ``private`` to actually exist — multi-
    endpoint validation rejects per-agent endpoint values that don't
    match a defined endpoint or the implicit ``open``.
    """
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "model[task_agent]": "qwen3-coder",
            "endpoint[task_agent]": "private",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["runtime"]["models"]["task_agent"]["model"] == "qwen3-coder"
    assert s["runtime"]["models"]["task_agent"]["endpoint"] == "private"


def test_global_settings_put_runtime_model_override_writes_runtime_model(
    settings_client, tmp_path
):
    """runtime_model field sets [runtime].model directly."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_model": "claude-haiku-4-5",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    # runtime_model overrides whatever the privacy block computed
    assert s["runtime"]["model"] == "claude-haiku-4-5"


# ---- Per-mode model defaults round-trip ------------------------------------


def test_global_settings_put_per_mode_default_model_writes_runtime_modes(
    settings_client, tmp_path
):
    """``runtime_modes_<mode>_model`` populates
    ``[runtime.modes.<mode>].model``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_private_model": "qwen3:14b",
            "runtime_modes_hybrid_model": "claude-sonnet-4-5",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["runtime"]["modes"]["open"]["model"] == "claude-opus-4-7"
    assert s["runtime"]["modes"]["private"]["model"] == "qwen3:14b"
    assert s["runtime"]["modes"]["hybrid"]["model"] == "claude-sonnet-4-5"


def test_global_settings_put_per_mode_per_agent_writes_models_subtable(
    settings_client, tmp_path
):
    """``runtime_modes_<mode>_models[<agent>][model|endpoint]`` populates
    ``[runtime.modes.<mode>.models.<agent>]``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_open_models[task_agent][model]": "claude-haiku-4-5",
            "runtime_modes_open_models[task_agent][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["open"]["models"]["task_agent"]["model"]
        == "claude-haiku-4-5"
    )
    assert (
        s["runtime"]["modes"]["open"]["models"]["task_agent"]["endpoint"]
        == "open"
    )


def test_global_settings_put_hybrid_forces_data_agent_private(
    settings_client, tmp_path
):
    """A hybrid-mode submission that tries endpoint=open for data_agent
    is silently coerced to endpoint=private — server-side enforcement of
    the forced-private rule."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_hybrid_model": "claude-sonnet-4-5",
            "runtime_modes_hybrid_models[data_agent][model]": "qwen3:14b",
            # UI shouldn't allow this, but defensive enforcement matters.
            "runtime_modes_hybrid_models[data_agent][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["hybrid"]["models"]["data_agent"]["endpoint"]
        == "private"
    )


def test_global_settings_put_hybrid_allows_tool_builder_open(
    settings_client, tmp_path
):
    """tool_builder DEFAULTS to private but the user is free to flip
    it to open. Only data_agent is hard-locked private in hybrid."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_hybrid_model": "claude-sonnet-4-5",
            "runtime_modes_hybrid_models[tool_builder][model]": "claude-opus-4-7",
            "runtime_modes_hybrid_models[tool_builder][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["hybrid"]["models"]["tool_builder"]["endpoint"]
        == "open"
    )


def test_global_settings_put_per_agent_endpoint_accepts_named_endpoint(
    settings_client, tmp_path
):
    """A per-agent endpoint value matching a defined named endpoint
    (anything beyond ``open`` / ``private``) round-trips to the TOML."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "endpoints[1][name]": "ollama",
            "endpoints[1][base_url]": "http://localhost:11435",
            "endpoints[1][api_key_env]": "",
            "endpoints[1][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_open_models[task_agent][model]": "llama3:8b",
            "runtime_modes_open_models[task_agent][endpoint]": "ollama",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["open"]["models"]["task_agent"]["endpoint"]
        == "ollama"
    )


def test_global_settings_put_per_agent_endpoint_strips_undefined_name(
    settings_client, tmp_path
):
    """A per-agent endpoint pointing at an undefined endpoint name is
    silently stripped (drops the override) — Privacy-tab edits like
    rename/remove must not 422 the rest of the form. Save still
    succeeds; the agent just falls back to the mode default."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_open_models[task_agent][model]": "llama3:8b",
            # Undefined endpoint name → silently stripped, save still 200.
            "runtime_modes_open_models[task_agent][endpoint]": "does_not_exist",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    ta = s["runtime"]["modes"]["open"]["models"]["task_agent"]
    assert ta.get("model") == "llama3:8b"
    # endpoint key is absent (stripped) — no override, falls back to mode default.
    assert "endpoint" not in ta


def test_global_settings_put_private_mode_coerces_open_endpoint_to_private(
    settings_client, tmp_path
):
    """Private mode hides the cloud option in the UI; the API enforces
    the same rule (any endpoint=open submission is coerced)."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_private_model": "qwen3:14b",
            "runtime_modes_private_models[task_agent][model]": "qwen3-coder",
            "runtime_modes_private_models[task_agent][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["private"]["models"]["task_agent"]["endpoint"]
        == "private"
    )


# ---- Preferences tab round-trip --------------------------------------------


def test_global_settings_put_preferences_writes_audience_and_max_turns(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "novice",
            "default_max_turns": "20",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["preferences"]["audience"] == "novice"
    assert s["preferences"]["max_turns_per_experiment"] == 20


def test_global_settings_put_preferences_writes_web_search_and_venv(
    settings_client, tmp_path
):
    """web_search and venv checkboxes round-trip as booleans."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "web_search": "on",
            "venv": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["preferences"]["web_search"] is True
    assert s["preferences"]["venv"] is True


def test_global_settings_put_preferences_unchecked_writes_false(
    settings_client, tmp_path
):
    """An unchecked checkbox arrives absent → field stored as False."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            # web_search and venv intentionally omitted
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["preferences"]["web_search"] is False
    assert s["preferences"]["venv"] is False


def test_global_settings_put_invalid_audience_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "junior",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_invalid_max_turns_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "-1",
        },
    )
    assert r.status_code == 422


# ---- Notifications tab round-trip ------------------------------------------


def test_global_settings_put_notifications_email_writes_section(
    settings_client, tmp_path
):
    """Email connection details → [notifications.email] table.

    Channel enablement is per-project (handled elsewhere); the global
    form only persists connection details.
    """
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com, bob@example.com",
            "notifications_email_smtp_host": "smtp.example.com",
            "notifications_email_smtp_port": "587",
            "notifications_email_smtp_user": "bot",
            "notifications_email_smtp_password_env": "SMTP_PW",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    email = s["notifications"]["email"]
    assert email["from_addr"] == "bot@example.com"
    assert email["to"] == ["alice@example.com", "bob@example.com"]
    assert email["smtp_host"] == "smtp.example.com"
    assert email["smtp_port"] == 587


def test_global_settings_put_notifications_slack_writes_section(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_slack_channel": "#urika",
            "notifications_slack_token_env": "SLACK_TOKEN",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["slack"]["channel"] == "#urika"
    assert s["notifications"]["slack"]["token_env"] == "SLACK_TOKEN"


def test_global_settings_put_notifications_telegram_writes_section(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_telegram_chat_id": "12345",
            "notifications_telegram_bot_token_env": "TG_TOKEN",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["telegram"]["chat_id"] == "12345"
    assert s["notifications"]["telegram"]["bot_token_env"] == "TG_TOKEN"


def test_global_settings_put_email_auto_enable_writes_flag(
    settings_client, tmp_path
):
    """``notifications_email_auto_enable=on`` round-trips to
    ``[notifications.email].auto_enable = true``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
            "notifications_email_auto_enable": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["email"]["auto_enable"] is True


def test_global_settings_put_slack_auto_enable_writes_flag(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_slack_channel": "#urika",
            "notifications_slack_auto_enable": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["slack"]["auto_enable"] is True


def test_global_settings_put_telegram_auto_enable_writes_flag(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_telegram_chat_id": "12345",
            "notifications_telegram_auto_enable": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["telegram"]["auto_enable"] is True


def test_global_settings_put_auto_enable_unchecked_writes_false(
    settings_client, tmp_path
):
    """Omitting ``notifications_<ch>_auto_enable`` from the form (i.e.
    unchecked checkbox) writes ``auto_enable = false``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
            # email auto_enable intentionally omitted
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["email"]["auto_enable"] is False


def test_global_settings_put_notifications_does_not_write_channels(
    settings_client, tmp_path
):
    """The global form never writes [notifications].channels — that
    list is per-project and managed elsewhere."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    # Email section is written (connection details set) but no channels list.
    assert "email" in s.get("notifications", {})
    assert "channels" not in s.get("notifications", {})


# ---- Response shape --------------------------------------------------------


def test_global_settings_put_returns_html_fragment_by_default(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    assert "Saved" in r.text


def test_global_settings_put_returns_json_when_requested(settings_client):
    r = settings_client.put(
        "/api/settings",
        headers={"accept": "application/json"},
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # privacy_mode is no longer part of the global form / response.
    assert "privacy_mode" not in body
    assert body["default_max_turns"] == 10


# ---- Slack inbound-config fields (app_token + allow-lists) ----------------


def test_global_settings_renders_slack_inbound_config_fields(settings_client):
    """The Slack channel block must expose the three inbound-Socket-Mode
    config fields so users don't have to hand-edit ``settings.toml`` to
    enable inbound commands or restrict who can issue them."""
    body = settings_client.get("/settings").text
    assert 'name="notifications_slack_app_token_env"' in body
    assert 'name="notifications_slack_allowed_channels"' in body
    assert 'name="notifications_slack_allowed_users"' in body


def test_global_settings_slack_inbound_fields_reflect_saved_values(
    settings_client, tmp_path
):
    """When the inbound-config fields are saved in ``settings.toml``,
    the form pre-populates them. ``allowed_channels`` /
    ``allowed_users`` are stored as TOML lists; the form renders them
    as comma-separated strings."""
    (tmp_path / "home" / "settings.toml").write_text(
        "[notifications.slack]\n"
        'channel = "#urika"\n'
        'token_env = "SLACK_BOT_TOKEN"\n'
        'app_token_env = "SLACK_APP_TOKEN"\n'
        'allowed_channels = ["#urika", "#lab-runs"]\n'
        'allowed_users = ["U01ABC", "U02DEF"]\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    assert "SLACK_APP_TOKEN" in body
    # Lists render as comma-joined strings.
    assert "#urika, #lab-runs" in body or "#urika,#lab-runs" in body
    assert "U01ABC, U02DEF" in body or "U01ABC,U02DEF" in body


def test_global_settings_put_writes_slack_inbound_config(
    settings_client, tmp_path
):
    """Saving the form persists the three new fields under
    ``[notifications.slack]``. Comma-separated allow-lists are split
    into TOML lists (whitespace stripped, empty entries dropped)."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_slack_channel": "#urika",
            "notifications_slack_token_env": "SLACK_BOT_TOKEN",
            "notifications_slack_app_token_env": "SLACK_APP_TOKEN",
            "notifications_slack_allowed_channels": "#urika, #lab-runs",
            "notifications_slack_allowed_users": "U01ABC, U02DEF",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    slack = s["notifications"]["slack"]
    assert slack["app_token_env"] == "SLACK_APP_TOKEN"
    assert slack["allowed_channels"] == ["#urika", "#lab-runs"]
    assert slack["allowed_users"] == ["U01ABC", "U02DEF"]


def test_global_settings_put_drops_empty_slack_inbound_fields(
    settings_client, tmp_path
):
    """Empty inbound-config fields are not persisted — keeps TOML tidy.
    An empty ``app_token_env`` and empty allow-lists must not write
    keys that aren't there."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_slack_channel": "#urika",
            "notifications_slack_token_env": "SLACK_BOT_TOKEN",
            "notifications_slack_app_token_env": "",
            "notifications_slack_allowed_channels": "",
            "notifications_slack_allowed_users": "",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    slack = s["notifications"]["slack"]
    # Channel + token_env still present (those carry data); the empty
    # inbound-config fields must not have written keys.
    assert slack["channel"] == "#urika"
    assert slack["token_env"] == "SLACK_BOT_TOKEN"
    assert "app_token_env" not in slack
    assert "allowed_channels" not in slack
    assert "allowed_users" not in slack
