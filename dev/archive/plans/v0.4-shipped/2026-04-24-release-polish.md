# Urika Release Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring Urika from working-well-for-me to ready-for-wider-release by (1) improving presentation verbosity (slides and speaker notes), (2) hardening the TUI around copy/paste and long-running commands, (3) polishing the dashboard, (4) adding multi-provider support via a LiteLLM adapter so Urika isn't locked to Anthropic, (5) splitting oversized CLI and orchestrator files into focused modules, (6) adding the security documentation and `--dry-run` mode that agent-written-code execution needs, and (7) removing 187MB of archived TypeScript code.

**Architecture:** Work is grouped into 9 phases designed to land safe/high-value changes first (cleanup, version pins, security) before the disruptive refactors. Each phase can be committed and released independently. Phases 3 (presentations) and 4 (TUI) are the user-visible "polish" the release needs; phase 7 (LiteLLM adapter) unlocks multi-provider without rewriting; phase 8 (refactoring) is the foundation for external contributors. Every refactor target exceeds 1,100 lines, so splits follow a consistent pattern: one `_helpers.py` per domain, one module per logical concern, keep the existing public entry-point intact to avoid breaking callers.

**Tech Stack:** Python 3.11+, Click 8, Textual 0.90+, Rich 13, Claude Agent SDK, LiteLLM, pytest, ruff, reveal.js (bundled).

**Estimated total:** ~40 tasks across 9 phases. Phases 1–4 are ~1 day each; Phase 7 (LiteLLM adapter) is ~3–4 days; Phase 8 (refactoring) is ~2–3 days.

---

## Phase 0 — Pre-flight (5 minutes, no code)

### Task 0.1: Confirm baseline tests pass on `dev`

Run: `pytest -q 2>&1 | tail -20`
Expected: All tests pass. If any fail, triage before starting — this plan assumes a green baseline.

---

## Phase 1 — Quick wins (cleanup, version pins)

Low-risk, immediate. Do these first so nothing downstream breaks from a surprise Textual upgrade mid-refactor.

### Task 1.1: Remove the archived TypeScript TUI

**Files:**
- Delete: `dev/archive/typescript-tui/` (187MB, 7,649 files)
- Keep: `dev/archive/option-a-claude-agent-sdk.md`, `option-b-build-on-pi.md`, `option-c-custom-runtime.md` (decision records)

**Context:** This is the abandoned TypeScript TUI + pi-runtime attempt. It's tracked in git (committed in `e07e747c`) and still in the working tree. The `project_tui_v2_status` memory from 2026-04-12 explicitly listed these as "What to Remove." It inflates fresh clones by ~190MB and clutters code search.

**Step 1: Confirm current size**

Run: `du -sh dev/archive/typescript-tui && find dev/archive/typescript-tui -type f | wc -l`
Expected: `~187M` and `7649`.

**Step 2: Verify no code references it**

Run: `grep -rn "dev/archive/typescript-tui\|archive/typescript-tui" --include="*.py" --include="*.md" --include="*.toml" src/ tests/ docs/ pyproject.toml CLAUDE.md`
Expected: No matches (or only matches in dev/archive itself).

**Step 3: Remove**

Run: `git rm -r dev/archive/typescript-tui`

**Step 4: Commit**

```bash
git commit -m "chore: remove archived typescript-tui (187MB, 7649 files)

The TypeScript TUI + pi-runtime attempt was superseded by the Python
Textual TUI in 2026-04. The archived copy is preserved in git history
at commit e07e747c if ever needed. Decision-record markdown files in
dev/archive/ are kept."
```

**Step 5: Verify**

Run: `du -sh dev/archive`
Expected: Only a few KB (just the three option-*.md files).

---

### Task 1.2: Pin `textual` and `claude-agent-sdk` to safe ranges

**Files:**
- Modify: `pyproject.toml` (the `dependencies` block, around the claude-agent-sdk and textual lines)

**Context:** `tui/capture.py:129-134` depends on Textual private attributes (`_thread_id`, `_loop`). A Textual minor bump could silently break the TUI's thread-safe output routing. And Claude Agent SDK is pre-1.0 — an eventual 1.0 is likely to break things. Tight upper bounds let us test upgrades deliberately.

**Step 1: Edit the deps**

Change:
```toml
"claude-agent-sdk>=0.1",
```
to:
```toml
"claude-agent-sdk>=0.1,<1.0",
```

Change:
```toml
"textual>=0.90",
```
to:
```toml
"textual>=0.90,<0.95",
```

**Step 2: Reinstall and run the TUI smoke test**

Run:
```bash
pip install -e ".[dev]" 2>&1 | tail -5
pytest tests/test_tui -q
```
Expected: Install succeeds without resolver errors. TUI tests pass.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pin textual <0.95 and claude-agent-sdk <1.0

textual: capture.py uses private _thread_id/_loop attributes; pin
until we verify 0.95+ still exposes them or rewrite to public API.
claude-agent-sdk: pre-1.0, breaking 1.0 is expected; opt-in later."
```

---

### Task 1.3: Decide the fate of `echo.py`

**Files:**
- Investigate: `src/urika/agents/roles/echo.py`
- Potentially move to: `tests/fixtures/echo_agent.py`, or delete

**Step 1: Find references**

Run: `grep -rn "echo" src/urika/agents/ | grep -v __pycache__ | grep -v "echo_" | grep -v '"echo' | head -20`
Also: `grep -rn "from urika.agents.roles.echo\|from urika.agents.roles import echo\|roles.echo" src/ tests/ | head`
Expected: Determine whether it's imported by production code, tests, or neither.

**Step 2: Decide based on findings**

- If imported only by tests → move to `tests/fixtures/` and update imports.
- If imported by production code → leave it, but add a one-line docstring explaining its purpose.
- If unreferenced → `git rm src/urika/agents/roles/echo.py`.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: clean up echo agent role"
```

---

## Phase 2 — Safety and release-critical docs

These are release-blockers for a wider audience.

### Task 2.1: Add `--dry-run` to `urika run`

**Files:**
- Modify: `src/urika/cli/run.py` (add the flag and wire it through)
- Modify: `src/urika/orchestrator/loop.py` (accept dry_run parameter; short-circuit agent execution to print-only)
- Modify: `src/urika/rpc/methods.py` (pass dry_run through RPC boundary if applicable)
- Test: `tests/test_cli/test_run.py`

**Context:** Task agents write and execute Python. For a mass-release user seeing this for the first time, `--dry-run` is the difference between "trust but verify" and "I have to read every generated file before I hit enter." The flag should print the planned pipeline (which agents will run, which tools are available, which dirs are writable) without invoking any agent.

**Step 1: Write the failing test**

```python
# tests/test_cli/test_run.py (new test, add to existing file)
def test_run_dry_run_prints_plan_without_executing(tmp_path, monkeypatch):
    """--dry-run outputs the planned pipeline and returns 0 without calling any runner."""
    from click.testing import CliRunner
    from urika.cli import cli

    # Set up a minimal project fixture
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "urika.toml").write_text('name = "test"\nquestion = "Q"\n')

    called = {"ran": False}

    def fake_run_experiment(*args, **kwargs):
        called["ran"] = True
        raise AssertionError("runner should not be called in dry-run")

    monkeypatch.setattr("urika.orchestrator.loop.run_experiment", fake_run_experiment)

    result = CliRunner().invoke(cli, ["run", "--project", str(project_dir), "--dry-run"])
    assert result.exit_code == 0
    assert not called["ran"]
    assert "dry run" in result.output.lower() or "would run" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli/test_run.py::test_run_dry_run_prints_plan_without_executing -v`
Expected: FAIL — `--dry-run` is not a known option.

**Step 3: Add the `--dry-run` flag to the run command**

In `src/urika/cli/run.py`, find the `@click.option` decorators on the `run` command and add:

```python
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned pipeline (agents, tools, writable dirs) without executing.",
)
```

Update the function signature and early in the body:

```python
def run(..., dry_run: bool, ...):
    ...
    if dry_run:
        _print_dry_run_plan(project_dir, experiment_id, ...)
        return
    ...
```

Add a helper:

```python
def _print_dry_run_plan(project_dir, experiment_id, ...):
    from urika.cli_display import print_section, print_kv
    print_section("Dry run — no agents will be invoked")
    print_kv("Project", str(project_dir))
    print_kv("Experiment", experiment_id or "(auto)")
    print_kv("Pipeline", "planning → task → evaluator → advisor")
    print_kv("Writable dirs", f"{project_dir}/experiments/, {project_dir}/methods/")
    print_kv("Each task agent will write Python code under:",
             f"{project_dir}/experiments/<id>/code/")
    click.echo("")
    click.echo("Remove --dry-run to execute.")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli/test_run.py::test_run_dry_run_prints_plan_without_executing -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/urika/cli/run.py tests/test_cli/test_run.py
git commit -m "feat(cli): add --dry-run to urika run

Prints the planned pipeline without invoking any agent. Lets users
preview what will happen before agent-written code executes."
```

---

### Task 2.2: Write the security documentation

**Files:**
- Create: `docs/18-security.md`
- Modify: `docs/README.md` (add to table of contents)

**Context:** Agent-generated Python runs as the user. There's no runtime sandbox — permission enforcement lives in the Claude SDK's tool policy, not in Urika. This has been fine for your personal use but will surprise new users. Document it.

**Step 1: Create `docs/18-security.md`**

```markdown
# Security Model

## Agent-generated code runs as you

Urika's task agent, finalizer, and tool builder write Python code into
your project directory and execute it via `subprocess.run([sys.executable, ...])`.
There is no sandbox. Generated code has the same filesystem access as the
process that launched `urika run`.

### What this means in practice

- **Inspect before rerunning.** Each experiment's code lives under
  `<project>/experiments/<id>/code/`. Read it before re-running.
- **Use `--dry-run` to preview.** `urika run --dry-run` prints the planned
  pipeline without invoking any agent.
- **Don't run untrusted projects.** If someone sends you a Urika project,
  treat it like running a random Python script from them.
- **Avoid shared hardware.** Don't run on a machine where the user you're
  logged in as can write to files other users depend on.

## Permission boundaries

Each agent role declares its own `SecurityPolicy`:

- `readable_dirs` — directories the agent may read
- `writable_dirs` — directories the agent may write to
- `allowed_tools` / `disallowed_tools` — which Claude Code tools the agent may use
- `allowed_bash_prefixes` / `blocked_bash_patterns` — shell command restrictions

These are passed to the Claude Agent SDK and enforced by Claude Code. Urika
does not verify the SDK's enforcement; we trust Claude Code's tool
permission system. If you need a stronger boundary, run Urika inside a
container or VM.

## Secrets

Secrets live in `~/.urika/secrets.env` with mode 0600. API keys are loaded
into `os.environ` at CLI startup. Consider using the OS keyring via the
`keyring` package if you share a machine.

## Dashboard

`urika dashboard` binds to `127.0.0.1:8420` (localhost only). Path
traversal is prevented by `is_relative_to(project_dir)` checks. There is
no authentication — anyone with shell access to the machine can browse
the dashboard. For networked use, put it behind an auth proxy.

## Notifications

Slack and Telegram bots currently accept interactions from any user in
the channel. If you deploy notifications for a team, restrict to
authorized channels in `.urika/notifications.toml` and audit the
configuration.
```

**Step 2: Add to `docs/README.md`**

Append to the table of contents:
```markdown
18. [Security Model](18-security.md) — what agent-generated code can do, permission boundaries, secrets
```

**Step 3: Commit**

```bash
git add docs/18-security.md docs/README.md
git commit -m "docs: add security model documentation

Explains agent-generated code execution, permission boundaries,
secrets handling, dashboard and notifications security posture."
```

---

### Task 2.3: Slack bot authorization allowlist

**Files:**
- Modify: `src/urika/notifications/slack_channel.py` (around the TODO at line 158)
- Test: `tests/test_notifications/test_slack_channel.py` (may need to create or extend)

**Context:** The TODO at line 158 says "Restrict interactions to authorized users/channels." For mass release, this matters — otherwise anyone in a shared Slack workspace who sees the bot could click buttons that trigger actions on someone else's Urika.

**Step 1: Write the failing test**

```python
# tests/test_notifications/test_slack_channel.py
def test_slack_bot_ignores_interactions_from_unauthorized_channels(monkeypatch):
    """Button clicks from a channel not in allowed_channels are dropped."""
    from urika.notifications.slack_channel import SlackChannel
    channel = SlackChannel(
        webhook_url="http://fake",
        bot_token="xoxb-fake",
        app_token="xapp-fake",
        allowed_channels=["CALLOWED"],
    )
    payload = {"channel": {"id": "COTHER"}, "actions": [{"action_id": "run"}]}
    handled = channel._handle_authorized_interaction(payload)
    assert handled is False, "should drop payloads from non-allowlisted channels"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_notifications/test_slack_channel.py::test_slack_bot_ignores_interactions_from_unauthorized_channels -v`
Expected: FAIL.

**Step 3: Implement**

In `src/urika/notifications/slack_channel.py`:

1. Add `allowed_channels: list[str] | None = None` and `allowed_users: list[str] | None = None` to `SlackChannel.__init__` (default None = allow all, for back-compat, but warn).
2. Add a method `_handle_authorized_interaction(self, payload: dict) -> bool` that returns False if the channel or user is not on the allowlist.
3. In `_handle_interaction` (the inner function at line ~150), call `_handle_authorized_interaction` first and return early if it returns False.
4. On init, if both allowlists are None, log a WARNING: `"Slack channel configured without allowed_channels or allowed_users — any user in the workspace can trigger actions."`
5. Remove the TODO comment.

**Step 4: Run test**

Run: `pytest tests/test_notifications/test_slack_channel.py -v`
Expected: PASS.

**Step 5: Document in `docs/17-notifications.md`**

Add a section on `allowed_channels` and `allowed_users`.

**Step 6: Commit**

```bash
git add src/urika/notifications/slack_channel.py tests/test_notifications/test_slack_channel.py docs/17-notifications.md
git commit -m "feat(slack): support allowed_channels/allowed_users allowlist

Slack button clicks from unauthorized channels or users are now dropped.
Empty allowlist is permitted for backwards-compatibility but logs a
warning so operators know actions are unrestricted."
```

---

## Phase 3 — Presentation verbosity rework

User's explicit request. Current hard caps of "max 4 bullets × max 8 words" mathematically can't explain methodology to a non-expert. Fix: require speaker notes, render them into reveal.js's `<aside class="notes">`, add an `explainer` slide type, and make "standard" audience verbose by default.

### Task 3.1: Expand `audience.py` — add "standard" mode with verbose default

**Files:**
- Modify: `src/urika/agents/audience.py`
- Test: `tests/test_agents/test_audience.py` (create if missing)

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_audience.py
from urika.agents.audience import AUDIENCE_INSTRUCTIONS, get_audience_instruction

def test_standard_audience_exists_and_is_default():
    assert "standard" in AUDIENCE_INSTRUCTIONS
    assert get_audience_instruction(None) == AUDIENCE_INSTRUCTIONS["standard"]
    assert get_audience_instruction("") == AUDIENCE_INSTRUCTIONS["standard"]

def test_standard_audience_requires_verbose_notes():
    text = AUDIENCE_INSTRUCTIONS["standard"].lower()
    assert "speaker notes" in text
    assert "sentences" in text or "paragraph" in text

def test_novice_audience_more_verbose_than_standard():
    assert len(AUDIENCE_INSTRUCTIONS["novice"]) > len(AUDIENCE_INSTRUCTIONS["standard"])
    assert len(AUDIENCE_INSTRUCTIONS["standard"]) > len(AUDIENCE_INSTRUCTIONS["expert"])
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_audience.py -v`
Expected: All FAIL.

**Step 3: Update `src/urika/agents/audience.py`**

```python
"""Audience-level instruction blocks for agent prompts."""

AUDIENCE_INSTRUCTIONS: dict[str, str] = {
    "expert": (
        "Assume domain expertise. Use technical terminology freely. "
        "Focus on results and methodology. Keep explanations concise. "
        "Speaker notes: 1-2 sentences per slide, only where non-obvious."
    ),
    "standard": (
        "Write for a researcher familiar with general statistics and ML "
        "but not necessarily this specific sub-domain. Define domain-"
        "specific jargon on first use (e.g., 'LOSO (Leave-One-Session-Out)'). "
        "Slides remain concise, but speaker notes should be verbose: write "
        "2-4 sentences per slide explaining what was done, why, and what "
        "the result means in plain language. Notes are where the real "
        "explanation lives — the slide is the headline. For methodology "
        "slides, the notes should describe the approach end-to-end so a "
        "presenter could talk to the slide without extra prep."
    ),
    "novice": (
        "Explain every method in plain language as if the reader has no "
        "statistics or ML background. For each method or model, add a "
        "'What this means' explainer slide. Define all technical terms on "
        "first use. Explain why each approach was chosen and what the "
        "results mean practically. Walk through results step by step. "
        "Include 1-2 extra slides per method explaining the approach "
        "conceptually before showing results. Speaker notes are long: "
        "4-6 sentences per slide, written as if narrating to someone new "
        "to the field. Use analogies. Define any term you introduce."
    ),
}

_DEFAULT = "standard"


def get_audience_instruction(audience: str | None) -> str:
    """Return the instruction block for an audience, defaulting to 'standard'."""
    if not audience:
        return AUDIENCE_INSTRUCTIONS[_DEFAULT]
    return AUDIENCE_INSTRUCTIONS.get(audience, AUDIENCE_INSTRUCTIONS[_DEFAULT])
```

**Step 4: Run tests**

Run: `pytest tests/test_agents/test_audience.py -v`
Expected: PASS.

**Step 5: Update callers**

Run: `grep -rn "AUDIENCE_INSTRUCTIONS" src/ tests/`
For each call site, use `get_audience_instruction(audience)` so the default falls through cleanly.

**Step 6: Commit**

```bash
git add src/urika/agents/audience.py tests/test_agents/test_audience.py
git commit -m "feat(audience): add 'standard' audience mode as default

The 'standard' mode sits between expert and novice. Slides stay
concise, but speaker notes are now verbose (2-4 sentences per slide)
and carry the real explanation. get_audience_instruction() falls
back to 'standard' when audience is None/empty."
```

---

### Task 3.2: Rework the presentation agent prompt

**Files:**
- Modify: `src/urika/agents/roles/prompts/presentation_agent_system.md`

**Context:** Current prompt says max 4 bullets, max 8 words per bullet, `notes` is "optional." That's what's producing shallow decks. Fix: require `notes` with explicit length guidance, soften word caps to guidelines, add `explainer` slide type, reorganize the narrative arc.

**Step 1: Edit the prompt**

Replace the contents of `src/urika/agents/roles/prompts/presentation_agent_system.md`. Key changes:

1. Change "Slide Design Principles" bullet "Max 4 bullet points per slide, each 3-8 words" to:
   - "Aim for ≤5 bullets per slide and ≤12 words per bullet where the content fits naturally. Prefer clarity over brevity."
2. In "Output Format" JSON, change `"notes": "Optional speaker notes"` to `"notes": "Required. 2-6 sentences explaining the slide content in plain language."` and mark `notes` as required in every slide type's example.
3. Add an "explainer" slide type between `bullets` and `figure`:
   - `{ "type": "explainer", "title": "...", "lead": "One-sentence lead", "body": "2-4 sentence paragraph", "notes": "required speaker notes" }`
4. Under "Slide Types," add:
   - **explainer** — a concept slide with a lead sentence and short paragraph body. Use for method explanation and audience context.
5. Under "Slide Layout Rules," replace the hard caps with:
   - **Guidelines per slide** (soft limits):
     - Bullets: ≤5 items, ≤12 words each
     - Figures: 1 per slide
     - Explainer body: ≤60 words
   - **Always required:** speaker notes per slide, length per the audience block below.
6. Expand the narrative arc guidance to include explainer slides (2-3 for standard audience, 3-5 for novice).
7. Add a "Speaker Notes" section before "Rules":
   ```markdown
   ## Speaker Notes
   
   Every slide MUST have a `notes` field. This is what a presenter would say
   out loud; it is rendered into reveal.js's speaker-notes pane and is NOT
   shown on the projected slide. Length depends on audience:
   
   - expert: 1-2 sentences, only where non-obvious
   - standard: 2-4 sentences per slide, describing what, why, and meaning
   - novice: 4-6 sentences per slide, narrated as if teaching the topic
   
   The slide is the headline; the notes are the explanation.
   ```
8. Update the Output Format JSON example so every slide includes a populated `notes` field.

**Step 2: Sanity check**

Run: `grep -c "notes" src/urika/agents/roles/prompts/presentation_agent_system.md`
Expected: ≥ 6 references to "notes".

**Step 3: Commit**

```bash
git add src/urika/agents/roles/prompts/presentation_agent_system.md
git commit -m "feat(presentation): require speaker notes, soften word caps

Speaker notes are now required on every slide and are where the real
explanation lives. Bullet caps become guidelines. Adds 'explainer'
slide type for method descriptions. Audience-driven notes length."
```

---

### Task 3.3: Render speaker notes in reveal.js

**Files:**
- Modify: `src/urika/core/presentation.py` — add notes rendering to every slide renderer
- Test: `tests/test_core/test_presentation.py`

**Context:** reveal.js supports `<aside class="notes">...</aside>` inside a `<section>`; pressing `S` in the deck opens the speaker window. This is the correct place for the verbose content the new prompt will produce.

**Step 1: Write the failing tests**

```python
# tests/test_core/test_presentation.py
from pathlib import Path
from urika.core.presentation import render_presentation

def test_notes_render_as_reveal_aside(tmp_path):
    data = {
        "title": "T", "subtitle": "S",
        "slides": [
            {"type": "bullets", "title": "Slide", "bullets": ["a"], "notes": "Hello notes."},
            {"type": "stat", "title": "K", "stat": "99%", "stat_label": "label",
             "notes": "Stat notes."},
        ],
    }
    out = render_presentation(data, tmp_path)
    html = (out / "index.html").read_text()
    assert '<aside class="notes">Hello notes.</aside>' in html
    assert '<aside class="notes">Stat notes.</aside>' in html

def test_notes_are_html_escaped(tmp_path):
    data = {"title": "T", "subtitle": "", "slides": [
        {"type": "bullets", "title": "x", "bullets": [], "notes": "<script>x</script>"},
    ]}
    out = render_presentation(data, tmp_path)
    html = (out / "index.html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

def test_explainer_slide_type(tmp_path):
    data = {"title": "T", "subtitle": "", "slides": [
        {"type": "explainer", "title": "What is LOSO?",
         "lead": "Leave-one-session-out cross-validation.",
         "body": "Each session is held out in turn, training on the others.",
         "notes": "Explainer notes."},
    ]}
    out = render_presentation(data, tmp_path)
    html = (out / "index.html").read_text()
    assert "Leave-one-session-out" in html
    assert "training on the others" in html
    assert '<aside class="notes">Explainer notes.</aside>' in html
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_presentation.py -v`
Expected: All three FAIL.

**Step 3: Implement**

In `src/urika/core/presentation.py`:

1. Add a helper:
   ```python
   def _render_notes(slide: dict[str, Any]) -> str:
       notes = slide.get("notes", "")
       if not notes:
           return ""
       return f'<aside class="notes">{_escape(notes)}</aside>'
   ```
2. In each `_render_*_slide` function, insert `{_render_notes(slide)}` just before the closing `</section>`.
3. Add a new renderer:
   ```python
   def _render_explainer_slide(slide: dict[str, Any]) -> str:
       title = slide.get("title", "")
       lead = slide.get("lead", "")
       body = slide.get("body", "")
       return f"""
               <section class="slide-explainer">
                   <h2>{_escape(title)}</h2>
                   <p class="lead">{_escape(lead)}</p>
                   <p class="body">{_escape(body)}</p>
                   {_render_notes(slide)}
               </section>
   """
   ```
4. In the dispatch block in `render_presentation`, add:
   ```python
   elif slide_type == "explainer":
       slides_html += _render_explainer_slide(slide)
   ```
5. Title slide: add optional notes support too so the intro can have notes.

**Step 4: Update reveal.js CSS to style explainer**

In `src/urika/templates/presentation/reveal.css` (or `theme-light.css` / `theme-dark.css`), add:
```css
.slide-explainer .lead { font-size: 1.4em; font-weight: 600; margin-bottom: 0.8em; }
.slide-explainer .body { font-size: 1.0em; line-height: 1.5; max-width: 40em; }
```

**Step 5: Run tests**

Run: `pytest tests/test_core/test_presentation.py -v`
Expected: PASS.

**Step 6: Run full presentation tests**

Run: `pytest tests/test_core/test_presentation.py tests/test_agents -v`
Expected: PASS, no regressions.

**Step 7: Commit**

```bash
git add src/urika/core/presentation.py src/urika/templates/presentation/ tests/test_core/test_presentation.py
git commit -m "feat(presentation): render speaker notes + explainer slide type

Every slide now emits <aside class=\"notes\"> so reveal.js's speaker
view shows the verbose explanation that lives in the JSON 'notes'
field. Adds 'explainer' slide type with a lead + short paragraph,
intended for method-introduction slides. Notes HTML-escaped."
```

---

### Task 3.4: Figure-exists validation with visible placeholder

**Files:**
- Modify: `src/urika/core/presentation.py` (`_render_figure_slide` and `_render_two_col_slide`)
- Test: `tests/test_core/test_presentation.py`

**Context:** Currently if the agent references a figure that doesn't exist, `shutil.copy2` is silently skipped and the deck has broken `<img>` tags. Replace with a visible "Figure missing: <path>" placeholder so the issue is obvious.

**Step 1: Write the failing test**

```python
def test_missing_figure_shows_placeholder(tmp_path):
    data = {"title": "T", "subtitle": "", "slides": [
        {"type": "figure", "title": "Results", "figure": "artifacts/does_not_exist.png",
         "figure_caption": "cap", "notes": "n"},
    ]}
    out = render_presentation(data, tmp_path, experiment_dir=tmp_path / "nowhere")
    html = (out / "index.html").read_text()
    assert "Figure missing" in html or "figure-missing" in html
    assert "does_not_exist.png" in html  # the path is visible so agent/user can fix
```

**Step 2: Implement**

In `_render_figure_slide` and `_render_two_col_slide`, after the `shutil.copy2` block, check whether the destination file exists. If not, render a placeholder instead of the `<img>`:

```python
fig_dst = figures_dir / fig_name
if fig_dst.exists():
    fig_html = f'<img src="figures/{_escape(fig_name)}" alt="{_escape(caption)}">'
else:
    fig_html = (
        f'<div class="figure-missing">'
        f'Figure missing: {_escape(figure_path)}'
        f'</div>'
    )
```

**Step 3: Add the placeholder CSS**

In `reveal.css` (or the theme CSS):
```css
.figure-missing { padding: 2em; border: 2px dashed #c33; color: #c33; text-align: center; }
```

**Step 4: Run tests**

Run: `pytest tests/test_core/test_presentation.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/urika/core/presentation.py src/urika/templates/presentation/ tests/test_core/test_presentation.py
git commit -m "fix(presentation): visible placeholder for missing figures

Was silently emitting a broken <img> tag when the agent referenced a
figure that didn't exist. Now shows a dashed-border placeholder with
the intended path so the problem is obvious."
```

---

### Task 3.5: End-to-end presentation smoke test

**Files:**
- Test: `tests/test_core/test_presentation_e2e.py` (new)

**Step 1: Write the test**

```python
# tests/test_core/test_presentation_e2e.py
def test_full_deck_with_all_slide_types_and_notes(tmp_path):
    from urika.core.presentation import render_presentation
    data = {
        "title": "Full Deck", "subtitle": "All slide types",
        "slides": [
            {"type": "bullets", "title": "b", "bullets": ["x","y"], "notes": "N1."},
            {"type": "explainer", "title": "e", "lead": "L", "body": "B", "notes": "N2."},
            {"type": "stat", "title": "s", "stat": "42", "stat_label": "lab", "notes": "N3."},
        ],
    }
    out = render_presentation(data, tmp_path)
    html = (out / "index.html").read_text()
    for n in ("N1.", "N2.", "N3."):
        assert f'<aside class="notes">{n}</aside>' in html
    assert "42" in html and "Leave-" not in html  # sanity
```

**Step 2: Run and commit**

Run: `pytest tests/test_core/test_presentation_e2e.py -v`
Expected: PASS.

```bash
git add tests/test_core/test_presentation_e2e.py
git commit -m "test(presentation): end-to-end smoke test across slide types"
```

---

## Phase 4 — TUI polish (copy/paste, worker timeout)

### Task 4.1: Reproduce copy/paste to determine if there's a real bug

**No code change yet — this is diagnosis.**

**Step 1: Launch the TUI in a mouse-friendly terminal**

Run (in iTerm2 / WezTerm / Alacritty / GNOME Terminal / Kitty):
```bash
urika
```

**Step 2: Generate some output in the panel**

Type `/help` and hit enter. The panel now has text.

**Step 3: Try copy**

- Attempt A: normal click+drag — expected to fail (Textual forwards mouse clicks).
- Attempt B: **Shift+drag** — select text, then Shift+Ctrl+C (or terminal's copy shortcut). This SHOULD work per Textual's default behavior.

**Step 4: Document the result**

- If Shift+drag works → this is a docs issue only. Skip to Task 4.2.
- If Shift+drag doesn't work → we need a `/copy` fallback. Proceed to Task 4.2 anyway; it's cheap insurance.

**Step 5: Update the welcome banner**

In `src/urika/tui/app.py`, find the welcome banner (around line 239 per the project memory) and confirm it says "Shift+drag to copy." If not, add it.

```bash
git add src/urika/tui/app.py
git commit -m "docs(tui): welcome banner mentions Shift+drag for copy"
```

---

### Task 4.2: Add a `/copy` slash command as a fallback

**Files:**
- Modify: `src/urika/repl/commands.py` (add the handler)
- Modify: `pyproject.toml` (add `pyperclip` to optional or core deps)
- Test: `tests/test_repl/test_commands_copy.py`

**Context:** A terminal-agnostic fallback for users whose terminal doesn't forward Shift+drag (Terminal.app, some SSH sessions). `/copy <n>` copies the last N lines of the output panel to the system clipboard.

**Step 1: Add `pyperclip` dependency**

In `pyproject.toml`, add `"pyperclip>=1.8",` to `dependencies`.

Run: `pip install -e ".[dev]"`

**Step 2: Write the failing test**

```python
# tests/test_repl/test_commands_copy.py
def test_copy_command_copies_last_n_lines(monkeypatch, tmp_path):
    from urika.repl.commands import handle_copy
    from urika.repl.session import ReplSession

    captured = {"text": None}
    monkeypatch.setattr("pyperclip.copy", lambda s: captured.__setitem__("text", s))

    session = ReplSession()
    session.recent_output_lines = ["line 1", "line 2", "line 3", "line 4"]
    handle_copy(session, "2")  # last 2 lines

    assert captured["text"] == "line 3\nline 4"
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_repl/test_commands_copy.py -v`
Expected: FAIL (no `handle_copy` defined; `recent_output_lines` may not exist).

**Step 4: Implement**

1. In `src/urika/repl/session.py`, add `recent_output_lines: list[str]` to `ReplSession` (default empty). Cap at 1000 entries.
2. In `src/urika/repl/commands.py`, add:
   ```python
   def handle_copy(session, args: str):
       """Copy recent output lines to the clipboard. Usage: /copy [N]"""
       import pyperclip
       try:
           n = int(args.strip()) if args.strip() else 40
       except ValueError:
           print_error("Usage: /copy [N]  — copies the last N lines (default 40).")
           return
       lines = session.recent_output_lines[-n:]
       if not lines:
           print_warning("No output to copy.")
           return
       text = "\n".join(lines)
       try:
           pyperclip.copy(text)
           print_info(f"Copied last {len(lines)} lines ({len(text)} chars) to clipboard.")
       except Exception as e:
           print_error(f"Clipboard copy failed: {e}")
   ```
3. Register in the `GLOBAL_COMMANDS` dict.
4. In `src/urika/tui/capture.py`, in `_write_to_panel`, also append the clean text to `session.recent_output_lines` (cap at 1000).
5. In `src/urika/repl/main.py`, do the same for the classic REPL's output path.

**Step 5: Run tests**

Run: `pytest tests/test_repl/test_commands_copy.py tests/test_tui -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat(repl/tui): /copy slash command — clipboard fallback

Adds /copy [N] which puts the last N output-panel lines on the
clipboard via pyperclip. Fallback for terminals that don't forward
Shift+drag (Terminal.app, some SSH)."
```

---

### Task 4.3: Worker-command timeout support

**Files:**
- Modify: `src/urika/tui/agent_worker.py`
- Test: `tests/test_tui/test_agent_worker.py`

**Context:** From the deep TUI review: if a handler blocks forever on something that isn't stdin (e.g., a socket without timeout), `/stop` and Ctrl+C don't help. Add an opt-in per-command timeout.

**Step 1: Write the failing test**

```python
# tests/test_tui/test_agent_worker.py
def test_worker_respects_timeout(monkeypatch):
    import threading, time
    from urika.tui.agent_worker import _run_with_timeout

    def slow_handler(sess, args):
        time.sleep(3)

    result = _run_with_timeout(slow_handler, session=None, args="",
                               timeout_s=0.5)
    assert result["timed_out"] is True
    assert result["error"] is None or "timeout" in result["error"].lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_agent_worker.py::test_worker_respects_timeout -v`
Expected: FAIL.

**Step 3: Implement**

Add a helper in `src/urika/tui/agent_worker.py`:

```python
def _run_with_timeout(handler, session, args, timeout_s: float | None):
    """Run handler, optionally enforcing a timeout.

    Uses a daemon thread so a forever-blocking handler doesn't
    prevent process exit. Returns a dict: timed_out, error.
    """
    import threading
    result = {"timed_out": False, "error": None}
    done = threading.Event()

    def _work():
        try:
            handler(session, args)
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            done.set()

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    finished = done.wait(timeout=timeout_s) if timeout_s else (t.join() or True)
    if not finished:
        result["timed_out"] = True
    return result
```

In `run_command_in_worker`, optionally look up a per-command timeout from a module-level dict (default None = no timeout):

```python
_COMMAND_TIMEOUTS = {
    # "run": 3600,           # experiments: 1 hour soft cap
    # "finalize": 1800,      # 30 min
    # Leave empty by default; opt-in only.
}
```

Wrap the handler call to honor the timeout. If the timeout fires, print an error to the panel and cancel the stdin reader.

**Step 4: Run tests**

Run: `pytest tests/test_tui -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/urika/tui/agent_worker.py tests/test_tui/test_agent_worker.py
git commit -m "feat(tui): opt-in worker-command timeout

_COMMAND_TIMEOUTS dict lets specific commands enforce a soft time
cap. Default is no timeout (unchanged). A timed-out worker leaves
the daemon thread to die with the process, avoiding forever-hangs
that /stop couldn't clear."
```

---

## Phase 5 — Dashboard polish

### Task 5.1: Dashboard live-reload on progress changes

**Files:**
- Modify: `src/urika/dashboard/server.py` (add SSE endpoint)
- Modify: `src/urika/dashboard/templates/` (add small client script)
- Test: `tests/test_dashboard/test_server_sse.py`

**Context:** Today the dashboard is static — you reload to see new runs. For a demo or during an experiment, a live-refresh on `progress.json` changes is a small change with big UX payoff.

**Step 1: Write the failing test**

```python
# tests/test_dashboard/test_server_sse.py
def test_sse_endpoint_emits_on_progress_change(tmp_path):
    import json, threading, time, urllib.request
    from urika.dashboard.server import make_app, run_server_in_thread

    project = tmp_path / "proj"
    project.mkdir()
    progress = project / "experiments" / "exp1" / "progress.json"
    progress.parent.mkdir(parents=True)
    progress.write_text(json.dumps([]))

    server, port = run_server_in_thread(project, port=0)
    try:
        # Spawn the SSE listener, then trigger a change
        received = []

        def listen():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/events") as r:
                for _ in range(2):
                    chunk = r.readline().decode()
                    if chunk.startswith("data:"):
                        received.append(chunk)

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        time.sleep(0.3)
        progress.write_text(json.dumps([{"id": "r1"}]))
        t.join(timeout=3)
        assert received, "expected at least one SSE message"
    finally:
        server.shutdown()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard/test_server_sse.py -v`
Expected: FAIL — no /events endpoint.

**Step 3: Implement**

Add an `/events` route to the dashboard server. It polls `progress.json` mtime every 1s and streams `data: {"type": "progress"}\n\n` whenever it changes. Add a tiny JS snippet to the dashboard HTML that opens an EventSource and reloads relevant panels.

**Step 4: Commit**

```bash
git add -A
git commit -m "feat(dashboard): SSE live-reload on progress.json changes"
```

---

### Task 5.2: Dashboard polish — search, navigation, responsive layout

**Files:**
- Modify: `src/urika/dashboard/templates/*.html`, `src/urika/dashboard/*.css` (if present)
- Test: visual, and `tests/test_dashboard/test_server.py` for any new routes

**Context:** Your dashboard already looks great, per your own feedback. These are small polish items.

**Scope:**
- Ctrl+K / `/` to focus a tree-search input that filters the left nav by filename
- Breadcrumb above the rendered file
- On mobile/narrow windows, collapse the tree into a left-edge drawer
- Consistent light/dark mode toggle persistence (localStorage)
- Keyboard shortcuts: `j`/`k` to navigate the tree, `t` to toggle theme

**Steps:** split into 4 sub-commits (one per bullet above), each with a narrow test or visual check. Keep each small.

```bash
git commit -m "feat(dashboard): search box, breadcrumb, responsive drawer, keyboard nav"
```

---

### Task 5.3: Dashboard optional auth

**Files:**
- Modify: `src/urika/dashboard/server.py`
- Modify: `src/urika/cli/` (the dashboard command, wherever it lives)
- Test: `tests/test_dashboard/test_server_auth.py`

**Context:** Localhost is still the default; this is an opt-in bearer-token auth for users who want to tunnel to the dashboard remotely.

**Step 1: Write the failing test**

```python
# tests/test_dashboard/test_server_auth.py
def test_dashboard_rejects_missing_token_when_auth_enabled(tmp_path):
    from urika.dashboard.server import make_app
    from http import HTTPStatus
    app = make_app(tmp_path, auth_token="secret")
    # Use whatever test client pattern the dashboard uses
    ...  # expect 401 without Authorization header
    ...  # expect 200 with Authorization: Bearer secret
```

**Step 2: Implement**

- Add `--auth-token` to the `urika dashboard` CLI command.
- If provided, every request checks `Authorization: Bearer <token>` (constant-time compare with `secrets.compare_digest`).
- `/events` checks the token once on connect.
- On startup: warn if `--host` is not 127.0.0.1 and `--auth-token` is not set.

**Step 3: Commit**

```bash
git add -A
git commit -m "feat(dashboard): optional --auth-token for non-localhost hosts"
```

---

## Phase 6 — Error taxonomy

Prerequisite for Phase 8 refactoring: a consistent error type lets the split modules share error-handling idioms. Also useful to Phase 7 (LiteLLM adapter) so provider-specific errors surface uniformly.

### Task 6.1: Create `core/errors.py`

**Files:**
- Create: `src/urika/core/errors.py`
- Test: `tests/test_core/test_errors.py`

**Step 1: Write the failing tests**

```python
# tests/test_core/test_errors.py
from urika.core.errors import UrikaError, ConfigError, AgentError, ValidationError

def test_urika_error_is_base():
    assert issubclass(ConfigError, UrikaError)
    assert issubclass(AgentError, UrikaError)
    assert issubclass(ValidationError, UrikaError)

def test_errors_carry_user_message_and_hint():
    e = ConfigError("project file missing", hint="Run `urika new` first.")
    assert "project file missing" in str(e)
    assert e.hint == "Run `urika new` first."
```

**Step 2: Implement**

```python
# src/urika/core/errors.py
"""Typed errors used across the Urika codebase.

All user-facing errors derive from UrikaError so the CLI can render
them uniformly without leaking tracebacks.
"""

class UrikaError(Exception):
    """Base class for Urika's user-facing errors."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class ConfigError(UrikaError):
    """Project or runtime configuration is missing or invalid."""


class AgentError(UrikaError):
    """An agent failed for a reason worth surfacing (rate limit, auth, etc)."""


class ValidationError(UrikaError):
    """Input validation failed — user or LLM output."""
```

**Step 3: Commit**

```bash
git add src/urika/core/errors.py tests/test_core/test_errors.py
git commit -m "feat(errors): typed errors for consistent user-facing messages"
```

---

### Task 6.2: Migrate key call sites to the typed errors

**Files:**
- Modify: `src/urika/cli/__init__.py` (add a top-level `UrikaError` handler)
- Modify: `src/urika/agents/adapters/claude_sdk.py` (raise `AgentError` on SDK failure)
- Modify: `src/urika/core/workspace.py` (raise `ConfigError` where applicable)

**Context:** Don't try to migrate every raise site — pick the hot paths so the CLI can render errors consistently.

**Step 1: Add a top-level handler in `src/urika/cli/__init__.py`**

Wrap the `cli()` invocation so that `UrikaError` subclasses print `error: <message>` and `hint: <hint>` styled, then `sys.exit(2)` — without a traceback.

**Step 2: Migrate ~5-10 high-value call sites**

Prioritize: workspace load, project validation, agent runner errors.

**Step 3: Run the test suite**

Run: `pytest -q`
Expected: still green; the types are additive.

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: route hot-path errors through typed UrikaError subclasses"
```

---

## Phase 7 — LiteLLM multi-provider adapter

Add a second `AgentRunner` implementation that delegates to LiteLLM (OpenAI-compatible API surface spanning 140+ providers: OpenAI, Google, xAI, Groq, Cerebras, OpenRouter, Ollama, Bedrock, Vertex, and more). The existing `ClaudeSDKRunner` stays unchanged and remains the default — users on Claude subscriptions keep their economics. Users with API keys for other providers get a path that doesn't require Anthropic.

**Scope boundary (important):** initial adapter supports **reasoning-only roles** (planning_agent, advisor_agent, evaluator when used in read-only mode, presentation_agent, report_agent, project_summarizer, literature_agent in API-search mode). These roles don't invoke Claude Code's filesystem/bash tools.

Roles that require Claude Code's tool suite (task_agent, finalizer, tool_builder, and data_agent when it writes code) **stay on `ClaudeSDKRunner` for now**. Full tool-shim support for those roles — reimplementing Read/Write/Glob/Grep/Bash as Python function-call tools enforced against each role's `SecurityPolicy` — is its own plan and lives in Future Work.

This scope makes the release unblockable on Anthropic for the "thinking" parts of Urika while keeping the "executing" parts correct and safe.

### Task 7.1: Add LiteLLM as an optional dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add the extra**

In `pyproject.toml`, under `[project.optional-dependencies]`, add:
```toml
litellm = [
    "litellm>=1.50",
]
```
And include it in the `all` extra:
```toml
all = [
    "urika[dl]",
    "urika[litellm]",
]
```

**Step 2: Install + smoke check**

Run: `pip install -e ".[dev,litellm]"` then `python -c "import litellm; print(litellm.__version__)"`
Expected: prints a version ≥ 1.50.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add litellm as optional dep (for multi-provider adapter)"
```

---

### Task 7.2: Define the `AgentRunner` contract explicitly (if not already)

**Files:**
- Modify: `src/urika/agents/runner.py` (confirm `AgentRunner` ABC exposes every method LiteLLMRunner will need)
- Test: `tests/test_agents/test_runner_contract.py`

**Context:** Before writing the new adapter, pin down the contract. Read `ClaudeSDKRunner` and list every method + return type the adapter must honor. Missing or implicit methods should be hoisted onto the ABC with abstract declarations.

**Step 1: Audit**

Run: `grep -n "def " src/urika/agents/adapters/claude_sdk.py | head -30`
Compare against `grep -n "def \|@abstractmethod" src/urika/agents/runner.py`.

**Step 2: Add missing abstract methods**

Any method `ClaudeSDKRunner` exposes that's called from orchestrator/CLI must be abstract on `AgentRunner`. Concretely expect: `async run(config, prompt, on_message=None) -> AgentResult`. Make sure streaming callback signature is pinned.

**Step 3: Write a contract test**

```python
# tests/test_agents/test_runner_contract.py
def test_runner_abc_has_run_method():
    from urika.agents.runner import AgentRunner
    import inspect
    assert inspect.iscoroutinefunction(AgentRunner.run)
```

**Step 4: Commit**

```bash
git add src/urika/agents/runner.py tests/test_agents/test_runner_contract.py
git commit -m "refactor(agents): pin AgentRunner ABC contract ahead of LiteLLM adapter"
```

---

### Task 7.3: Implement `LiteLLMRunner` (reasoning-only, no tools)

**Files:**
- Create: `src/urika/agents/adapters/litellm_runner.py`
- Test: `tests/test_agents/test_litellm_runner.py`

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_litellm_runner.py
import pytest
from unittest.mock import AsyncMock, patch

from urika.agents.config import AgentConfig, SecurityPolicy
from urika.agents.runner import AgentResult

pytestmark = pytest.mark.asyncio

async def test_litellm_runner_returns_agent_result_on_success():
    from urika.agents.adapters.litellm_runner import LiteLLMRunner

    fake_response = {
        "choices": [{"message": {"content": "Hello from LLM."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "model": "gpt-4o-mini",
    }

    runner = LiteLLMRunner()
    with patch("litellm.acompletion", new=AsyncMock(return_value=fake_response)):
        config = AgentConfig(
            name="advisor",
            system_prompt="You are an advisor.",
            allowed_tools=[],
            disallowed_tools=[],
            security=SecurityPolicy(),
            max_turns=1,
            model="gpt-4o-mini",
        )
        result = await runner.run(config, "What's up?")
    assert isinstance(result, AgentResult)
    assert result.success is True
    assert "Hello from LLM." in result.text_output
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.model == "gpt-4o-mini"


async def test_litellm_runner_rejects_configs_requiring_tools():
    """Phase 7 adapter is reasoning-only. Configs with allowed_tools must fail loudly."""
    from urika.agents.adapters.litellm_runner import LiteLLMRunner
    from urika.core.errors import AgentError

    runner = LiteLLMRunner()
    config = AgentConfig(
        name="task_agent",
        system_prompt="Do the thing.",
        allowed_tools=["Read", "Write"],
        disallowed_tools=[],
        security=SecurityPolicy(),
        max_turns=1,
        model="gpt-4o-mini",
    )
    with pytest.raises(AgentError, match="tools not yet supported"):
        await runner.run(config, "prompt")


async def test_litellm_runner_classifies_rate_limit_error():
    from urika.agents.adapters.litellm_runner import LiteLLMRunner

    class FakeRateLimit(Exception):
        pass
    FakeRateLimit.__name__ = "RateLimitError"

    runner = LiteLLMRunner()
    with patch("litellm.acompletion", new=AsyncMock(side_effect=FakeRateLimit("slow down"))):
        config = AgentConfig(
            name="advisor", system_prompt="x", allowed_tools=[],
            disallowed_tools=[], security=SecurityPolicy(), max_turns=1,
            model="gpt-4o-mini",
        )
        result = await runner.run(config, "prompt")
    assert result.success is False
    assert result.error_category == "rate_limit"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_litellm_runner.py -v`
Expected: ImportError — module doesn't exist.

**Step 3: Implement the runner**

```python
# src/urika/agents/adapters/litellm_runner.py
"""LiteLLM-backed AgentRunner for reasoning-only roles.

Delegates to LiteLLM's unified OpenAI-compatible API so Urika's planning,
advisor, evaluator, presentation, report, and literature roles can run on
any provider LiteLLM supports (OpenAI, Google, xAI, Groq, Cerebras,
OpenRouter, Ollama, Bedrock, Vertex, and more).

Scope (Phase 7): reasoning-only. Configs that request tools (allowed_tools
non-empty) are rejected with AgentError. Full tool-shim support is future
work.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.errors import AgentError

log = logging.getLogger(__name__)


class LiteLLMRunner(AgentRunner):
    """Reasoning-only runner that uses LiteLLM's completion API."""

    async def run(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: Callable[[Any], None] | None = None,
    ) -> AgentResult:
        if config.allowed_tools:
            raise AgentError(
                f"Agent '{config.name}' requests tools {config.allowed_tools!r}, "
                "but the LiteLLM adapter is reasoning-only. Use the Claude SDK "
                "runner for roles that need filesystem or bash tools.",
                hint="Set runtime.provider='claude' for this agent, or remove "
                     "allowed_tools if the role is read-only reasoning.",
            )

        messages = [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            import litellm
            response = await litellm.acompletion(
                model=config.model,
                messages=messages,
                stream=False,
            )
        except Exception as exc:
            return _error_result(config, exc)

        return _success_result(config, response)


def _success_result(config: AgentConfig, response: dict[str, Any]) -> AgentResult:
    # LiteLLM returns OpenAI-style dicts.
    choices = response.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    usage = response.get("usage") or {}
    return AgentResult(
        success=True,
        text_output=text,
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        cost_usd=response.get("_response_cost", 0.0) or 0.0,
        model=response.get("model") or config.model,
        error=None,
        error_category=None,
    )


def _error_result(config: AgentConfig, exc: Exception) -> AgentResult:
    category = _classify(exc)
    message = f"LiteLLM call failed: {exc}"
    log.warning("%s (category=%s)", message, category)
    return AgentResult(
        success=False,
        text_output="",
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model=config.model or "",
        error=message,
        error_category=category,
    )


def _classify(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "ratelimit" in name or "rate" in text and "limit" in text:
        return "rate_limit"
    if "auth" in name or "api_key" in text or "unauthorized" in text:
        return "auth"
    if "billing" in name or "insufficient_quota" in text or "credit" in text:
        return "billing"
    return "unknown"
```

**Step 4: Run tests**

Run: `pytest tests/test_agents/test_litellm_runner.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/urika/agents/adapters/litellm_runner.py tests/test_agents/test_litellm_runner.py
git commit -m "feat(agents): LiteLLMRunner adapter for reasoning-only roles

Delegates to litellm.acompletion. Rejects configs that request tools
so accidental use for task_agent/finalizer/tool_builder surfaces
loudly. Tool-shim support for those roles is deferred to future work."
```

---

### Task 7.4: Register `LiteLLMRunner` in the runner factory

**Files:**
- Modify: `src/urika/agents/runner.py` (the `get_runner` factory)
- Test: `tests/test_agents/test_runner.py`

**Step 1: Write failing test**

```python
def test_get_runner_returns_litellm_runner():
    from urika.agents.runner import get_runner
    from urika.agents.adapters.litellm_runner import LiteLLMRunner
    runner = get_runner("litellm")
    assert isinstance(runner, LiteLLMRunner)

def test_get_runner_unknown_backend_raises():
    from urika.agents.runner import get_runner
    from urika.core.errors import ConfigError
    import pytest
    with pytest.raises(ConfigError, match="unknown runner backend"):
        get_runner("fake-backend")
```

**Step 2: Implement**

In `src/urika/agents/runner.py`, add a branch to `get_runner("litellm")` that imports `LiteLLMRunner` lazily (only when requested) so litellm stays truly optional.

**Step 3: Run + commit**

Run: `pytest tests/test_agents/test_runner.py -v`
Expected: PASS.

```bash
git add src/urika/agents/runner.py tests/test_agents/test_runner.py
git commit -m "feat(agents): register litellm backend in runner factory"
```

---

### Task 7.5: Per-agent provider config

**Files:**
- Modify: `src/urika/agents/config.py` (runtime config loader)
- Modify: `src/urika/core/workspace.py` (if config loading happens there)
- Test: `tests/test_agents/test_runtime_config.py`

**Context:** Runtime config already supports per-agent model overrides. Extend it to also support per-agent provider (claude | litellm). Default stays `claude` for all agents.

**Example runtime config** (for `.urika/runtime.toml`):
```toml
[agents.advisor]
provider = "litellm"
model = "gpt-4o-mini"

[agents.planning]
provider = "litellm"
model = "openrouter/anthropic/claude-3.5-sonnet"

# task_agent NOT specified → defaults to claude (tools supported)
```

**Step 1: Write failing tests**

```python
def test_runtime_config_falls_back_to_claude_when_provider_not_set(tmp_path):
    from urika.agents.config import load_runtime_config, get_agent_provider
    (tmp_path / ".urika").mkdir()
    (tmp_path / ".urika" / "runtime.toml").write_text("")
    cfg = load_runtime_config(tmp_path)
    assert get_agent_provider("task_agent", cfg) == "claude"

def test_runtime_config_honors_per_agent_provider(tmp_path):
    from urika.agents.config import load_runtime_config, get_agent_provider
    (tmp_path / ".urika").mkdir()
    (tmp_path / ".urika" / "runtime.toml").write_text(
        '[agents.advisor]\nprovider = "litellm"\nmodel = "gpt-4o-mini"\n'
    )
    cfg = load_runtime_config(tmp_path)
    assert get_agent_provider("advisor", cfg) == "litellm"
    assert get_agent_provider("task_agent", cfg) == "claude"
```

**Step 2: Implement**

Add `get_agent_provider(name, runtime_config)` alongside the existing `get_agent_model`.

**Step 3: Commit**

```bash
git add -A
git commit -m "feat(config): per-agent provider override in runtime.toml"
```

---

### Task 7.6: Wire provider selection into agent invocation

**Files:**
- Modify: every call site that currently does `get_runner()` with no argument — change to `get_runner(get_agent_provider(agent_name, runtime_config))`
  - Primary: `src/urika/orchestrator/chat.py`, `src/urika/orchestrator/loop.py`, `src/urika/agents/*` call sites
- Modify: `src/urika/agents/config.py` — if provider is `litellm` and the agent config has `allowed_tools`, raise `ConfigError` with a clear message at config load time (fail fast, don't wait for the API call)
- Test: `tests/test_orchestrator/test_provider_routing.py`

**Step 1: Write failing test**

```python
def test_orchestrator_uses_litellm_runner_when_configured(tmp_path, monkeypatch):
    # Set up runtime.toml with provider=litellm for advisor
    # Call the advisor via orchestrator
    # Assert LiteLLMRunner.run was invoked, not ClaudeSDKRunner.run
    ...
```

**Step 2: Implement**

Grep for all `get_runner(` call sites. Replace each with the provider-aware variant. Add a `ConfigError` at config-load time when a tool-requiring agent is pinned to `litellm`.

**Step 3: Run + commit**

```bash
git add -A
git commit -m "feat(orchestrator): route agents through configured provider"
```

---

### Task 7.7: `urika config` support for provider selection

**Files:**
- Modify: `src/urika/cli/config.py` (or its post-split location if Phase 8 has landed — note cross-phase dependency)
- Test: `tests/test_cli/test_config_provider.py`

**Step 1: Add CLI subcommand**

```bash
urika config provider <agent_name> <claude|litellm>
urika config model <agent_name> <model_name>
urika config provider --list   # show current per-agent config
```

**Step 2: Implement** — writes into `.urika/runtime.toml`, validates provider name, validates agent name, warns if setting `litellm` on a tool-requiring agent.

**Step 3: Commit**

```bash
git add -A
git commit -m "feat(cli): urika config provider/model subcommands"
```

---

### Task 7.8: Documentation + example `.env` setups

**Files:**
- Create: `docs/19-providers.md`
- Modify: `docs/13-configuration.md` (cross-link)
- Modify: `docs/README.md` (TOC)

**Content for `docs/19-providers.md`:**

- Overview: Claude SDK = default, LiteLLM = alternative for reasoning roles.
- Which roles can use LiteLLM today (reasoning-only list).
- Which roles still require Claude (task_agent, tool_builder, finalizer, data_agent when writing code).
- Setup:
  - OpenAI: `OPENAI_API_KEY`, model names.
  - Google Gemini: `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
  - OpenRouter (proxies anything): `OPENROUTER_API_KEY`, model names with prefixes.
  - Local Ollama: no key needed, `OLLAMA_BASE_URL=http://localhost:11434`.
- Example `runtime.toml` for a mixed setup.
- Cost considerations (LiteLLM surfaces cost in the response; Urika records it).
- Security note: provider keys live in `~/.urika/secrets.env` with mode 0600.

**Commit:**

```bash
git add docs/
git commit -m "docs: multi-provider setup guide (LiteLLM-backed roles)"
```

---

### Task 7.9: End-to-end smoke test with a mocked LiteLLM

**Files:**
- Test: `tests/test_integration/test_multi_provider.py`

Full pipeline: a minimal project, runtime.toml pins `advisor` to `litellm`, other agents remain claude, then run an advisor query and assert the LiteLLM runner was used for that one call.

```bash
git add -A
git commit -m "test: end-to-end multi-provider integration smoke"
```

---

## Phase 8 — Modular refactoring

**Philosophy:** every split preserves the public entry-point (the CLI command or the top-level function) and moves implementation detail into sub-modules. No behavioral change. Each split is its own commit.

**Pattern used:**
- `cli/<name>.py` keeps the Click command decorators + docstrings + public function signature.
- Implementation moves into `cli/_<name>/` subpackage (e.g. `cli/_run/plan.py`, `cli/_run/resume.py`, `cli/_run/execute.py`).
- Shared helpers go in `cli/_helpers.py`.
- Tests stay in the same module paths; only imports change.

### Task 8.1: Extract `cli/_helpers.py`

**Files:**
- Create: `src/urika/cli/_helpers.py`
- Test: `tests/test_cli/test_helpers.py`

**Context:** Several CLI modules duplicate patterns: load project config → validate → call agent/experiment → record usage → display. Extract these into one place.

**Steps:**
1. Identify 6-10 repeated helpers across `cli/run.py`, `cli/project.py`, `cli/agents.py` (grep for patterns: `load_project_config`, `save_usage`, `print_section`-style banner sequences, agent-result-to-display).
2. Move each into `cli/_helpers.py` with a small test.
3. Update call sites to import from `_helpers`.
4. Verify `pytest -q` remains green.

**Commit:**
```bash
git commit -m "refactor(cli): extract cli/_helpers.py for shared patterns"
```

---

### Task 8.2: Split `cli/config.py` (1,341 lines)

**Target layout:**
- `cli/config.py` — keep Click commands (`config`, `setup`, `secrets`, `endpoints`, etc.) and their docstrings. Thin dispatch.
- `cli/_config/hardware.py` — CPU/GPU detection, cuda/mps checks.
- `cli/_config/deps.py` — dependency-present detection, install hints.
- `cli/_config/venv.py` — venv creation helpers.
- `cli/_config/secrets_cmd.py` — secrets CLI flows.
- `cli/_config/endpoints.py` — endpoint management.
- `cli/_config/notifications_cmd.py` — notifications setup flow.

**Steps:**
1. For each sub-module, move the functions + their tests.
2. Re-import shims in `cli/config.py` so existing imports don't break.
3. After each sub-split, run `pytest tests/test_cli -q`.

**Commits (one per sub-module move):**
```bash
git commit -m "refactor(cli): split config.py — hardware detection"
git commit -m "refactor(cli): split config.py — dependency detection"
# ... etc
```

---

### Task 8.3: Split `cli/run.py` (1,187 lines)

**Target layout:**
- `cli/run.py` — the Click command + short main dispatch.
- `cli/_run/plan.py` — `_print_dry_run_plan`, pre-flight validation.
- `cli/_run/execute.py` — the RPC/orchestrator invocation path.
- `cli/_run/resume.py` — `--resume` logic.
- `cli/_run/progress_display.py` — progress bar + status updates.
- `cli/_run/usage.py` — usage-tracking wrapper.

Same pattern as 8.2. One commit per sub-module.

---

### Task 8.4: Split `cli/project.py` (1,198 lines)

**Target layout:**
- `cli/project.py` — `new`, `list`, `status`, `inspect` commands.
- `cli/_project/interactive.py` — the interactive project-builder walkthrough.
- `cli/_project/data_profile.py` — dataset scanning / profiling UI.
- `cli/_project/knowledge_ingest.py` — knowledge-pipeline hookup during setup.

---

### Task 8.5: Split `cli/agents.py` (1,186 lines)

**Target layout:**
- `cli/agents.py` — subcommand dispatch only.
- `cli/_agents/advisor.py`, `evaluate.py`, `plan.py`, `build_tool.py`, `present.py`, `report.py`, `finalize.py` — one per agent-flavored subcommand.

---

### Task 8.6: Split `repl/commands.py` (1,225 lines)

**Target layout:**
- `repl/commands.py` — `GLOBAL_COMMANDS`, `PROJECT_COMMANDS` registries + `get_all_commands`.
- `repl/_commands/project.py` — `/project`, `/list`, `/status`, `/new`.
- `repl/_commands/runtime.py` — `/run`, `/finalize`, `/evaluate`, `/advisor`, `/plan`.
- `repl/_commands/session.py` — `/usage`, `/config`, `/notifications`, `/copy`, `/quit`, `/stop`.
- `repl/_commands/project_assets.py` — `/results`, `/tools`, `/methods`, `/logs`, `/inspect`, `/criteria`.
- `repl/_commands/orchestrator.py` — `/resume`, orchestrator-chat entry points.

Commands stay callable under their current names (registry preserved). Every handler keeps the same signature `(session, args)`.

---

### Task 8.7: Split `orchestrator/loop.py` (1,114 lines)

**Target layout:**
- `orchestrator/loop.py` — `run_experiment` entry point.
- `orchestrator/_loop/turn.py` — single-turn execution (planning → task → evaluator → advisor).
- `orchestrator/_loop/resume.py` — resume-state reconstruction.
- `orchestrator/_loop/criteria_check.py` — criteria-evaluation gate.
- `orchestrator/_loop/notify.py` — on_progress callback + notification bus integration.

This is the highest-risk split — add a defensive integration test first:

**Step 1: Add a pre-refactor integration test**

```python
# tests/test_orchestrator/test_loop_integration.py
def test_run_experiment_pre_refactor_behavior(monkeypatch, tmp_path):
    """Pin behavior before the loop.py split so regressions surface."""
    # Arrange a minimal fixture with mocked runner
    # Assert: progress.json updated, labbook written, usage recorded, criteria evaluated
    ...
```

**Step 2: Extract sub-modules one at a time, running the test after each extraction.**

**Step 3: Commit per sub-module.**

---

## Phase 9 — Release prep

### Task 9.1: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Create the workflow**

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/
      - run: pytest -q
```

**Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: test on Python 3.11 and 3.12 + ruff check/format"
```

---

### Task 9.2: Plug test-coverage gaps

**Files:**
- Test: `tests/test_orchestrator/test_meta.py`, `tests/test_core/test_labbook.py`, `tests/test_dashboard/test_renderer.py`

**Context:** The codebase-review flagged `orchestrator/meta.py`, `core/labbook.py`, and dashboard rendering as thin on tests. Don't chase 100% — target the happy paths + one edge case each.

**Steps:**
1. `orchestrator/meta.py`: test criteria evolution, experiment-to-experiment decision branching.
2. `core/labbook.py`: test summary generation, inline figure linking, truncation.
3. `dashboard/renderer.py`: test markdown rendering, image embedding, code-block rendering.

One commit per module's test addition.

---

### Task 9.3: README + getting-started refresh

**Files:**
- Modify: `README.md`
- Modify: `docs/01-getting-started.md`

**Steps:**
- Update the "current state" section to match 0.2 (Textual TUI default, dashboard, presentations, finalizer).
- Screenshots: one of the TUI, one of the dashboard, one of a finished presentation.
- "Known limitations" subsection: agent-generated code runs as you (link to `docs/18-security.md`), TUI copy/paste needs Shift+drag in most terminals.

```bash
git add README.md docs/01-getting-started.md docs/assets/
git commit -m "docs: refresh README and getting-started for 0.2"
```

---

### Task 9.4: Version bump

**Files:**
- Modify: `pyproject.toml` (`version = "0.2.0"`)
- Modify: `CHANGELOG.md`

**Steps:**
1. Bump version to `0.2.0`.
2. Write a CHANGELOG entry summarizing: presentation verbosity rework, TUI worker-timeout + /copy, dashboard SSE + auth, error taxonomy, CLI/REPL refactoring, security docs, TypeScript TUI archive removal.

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.2.0"
```

---

### Task 9.5: Final smoke test

Run:
```bash
pytest -q && ruff check src/ tests/ && ruff format --check src/ tests/
```
Expected: all green.

Then manually verify:
- `urika` launches into TUI cleanly
- `/help`, `/copy 10`, `/project <name>` work
- `urika run --dry-run` prints a plan
- `urika dashboard` opens and live-updates on progress change
- `urika present <exp>` produces a deck where pressing `S` shows verbose speaker notes

---

## Future work (post-release, not in this plan)

- **Claude Code tool shims for non-Claude providers** (Phase 7 LiteLLM adapter initially supports reasoning-only roles; task_agent / finalizer / tool_builder keep the Claude SDK until tool shims land).
- **OS keychain for secrets** via `keyring` package.
- **Claude SDK Skills / Plugins / Hooks** adoption — progressively replace hand-rolled patterns with SDK-native abstractions now that the 2025/2026 SDK supports them.
- **Orchestrator memory persistence + `/resume`** across sessions (already in your notes as a future item).
- **Streaming progress updates to TUI during long agent runs** — currently batched.

---

## Execution notes

- **Commit frequency:** every task commits. Phase 8 splits commit per sub-module move to keep diffs reviewable.
- **Tests:** every code change is TDD (test first, red, green, commit). Refactors in phase 8 are behavior-preserving — tests should not need to change content, only imports.
- **Skills to invoke during execution:**
  - @superpowers:test-driven-development on every code task
  - @superpowers:verification-before-completion before marking any task done
  - @superpowers:systematic-debugging if a test fails unexpectedly
  - @pr-review-toolkit:code-reviewer after each phase
- **Worktree:** not required, but recommended for Phase 8 (the big refactor phase) — use @superpowers:using-git-worktrees.
- **Stop conditions:** if Phase 8 starts breaking integration tests, stop and add more pinning tests before continuing.
