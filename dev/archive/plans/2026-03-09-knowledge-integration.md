# Knowledge CLI & Orchestrator Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the knowledge pipeline into CLI commands and integrate knowledge context into the orchestrator loop.

**Architecture:** Add a `urika knowledge` CLI group (ingest/search/list) following existing CLI patterns. Add a `build_knowledge_summary()` helper. Modify the orchestrator loop to run the literature agent pre-loop and on-demand via `needs_literature`.

**Tech Stack:** click (CLI), existing KnowledgeStore, existing orchestrator infrastructure

---

## Reference Files

Before starting, read these to understand existing patterns:

- `src/urika/cli.py` — CLI command patterns, `_resolve_project` helper
- `src/urika/orchestrator/loop.py` — Orchestrator loop, `needs_tool` pattern
- `src/urika/knowledge/store.py` — KnowledgeStore API
- `tests/test_cli.py` — CLI test pattern with CliRunner and urika_env fixture
- `tests/test_orchestrator/test_loop.py` — FakeRunner, _setup_project, canned responses

---

### Task 1: Knowledge CLI Commands

**Files:**
- Modify: `src/urika/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestKnowledgeIngestCommand:
    def test_ingests_text_file(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        # Create a project first
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        # Create a knowledge file
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        knowledge_dir = projects_dir / "test-proj" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        note = knowledge_dir / "notes.txt"
        note.write_text("Some research notes about regression.")

        result = runner.invoke(
            cli,
            ["knowledge", "ingest", "test-proj", str(note)],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "k-001" in result.output

    def test_ingest_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["knowledge", "ingest", "nope", "/tmp/file.txt"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestKnowledgeSearchCommand:
    def test_search_with_results(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        knowledge_dir = projects_dir / "test-proj" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Regression analysis is useful.")
        runner.invoke(
            cli,
            ["knowledge", "ingest", "test-proj", str(knowledge_dir / "notes.txt")],
            env=urika_env,
        )

        result = runner.invoke(
            cli,
            ["knowledge", "search", "test-proj", "regression"],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "notes.txt" in result.output

    def test_search_no_results(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["knowledge", "search", "test-proj", "quantum"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "No results" in result.output


class TestKnowledgeListCommand:
    def test_list_empty(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["knowledge", "list", "test-proj"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "No knowledge" in result.output

    def test_list_populated(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        knowledge_dir = projects_dir / "test-proj" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Some notes.")
        runner.invoke(
            cli,
            ["knowledge", "ingest", "test-proj", str(knowledge_dir / "notes.txt")],
            env=urika_env,
        )

        result = runner.invoke(
            cli,
            ["knowledge", "list", "test-proj"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "k-001" in result.output
        assert "notes.txt" in result.output
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::TestKnowledgeIngestCommand -v`
Expected: FAIL — "no such command 'knowledge'"

**Step 3: Write the implementation**

Add to `src/urika/cli.py`, after the `run` command:

```python
@cli.group()
def knowledge() -> None:
    """Manage project knowledge base."""


@knowledge.command("ingest")
@click.argument("project")
@click.argument("source")
def knowledge_ingest(project: str, source: str) -> None:
    """Ingest a file or URL into the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    try:
        entry = store.ingest(source)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc))
    click.echo(f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})')


@knowledge.command("search")
@click.argument("project")
@click.argument("query")
def knowledge_search(project: str, query: str) -> None:
    """Search the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    results = store.search(query)

    if not results:
        click.echo("No results found.")
        return

    for entry in results:
        snippet = entry.content[:100].replace("\n", " ")
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]  {snippet}")


@knowledge.command("list")
@click.argument("project")
def knowledge_list(project: str) -> None:
    """List all knowledge entries."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    entries = store.list_all()

    if not entries:
        click.echo("No knowledge entries yet.")
        return

    for entry in entries:
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]")
```

**Step 4: Run tests**

Run: `pytest tests/test_cli.py -v -k knowledge`
Expected: All PASS

**Step 5: Lint and commit**

```bash
ruff check src/urika/cli.py tests/test_cli.py
ruff format src/urika/cli.py tests/test_cli.py
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: add knowledge CLI commands (ingest, search, list)"
```

---

### Task 2: Knowledge Summary Helper

**Files:**
- Create: `src/urika/orchestrator/knowledge.py`
- Create: `tests/test_orchestrator/test_knowledge_integration.py`

**Step 1: Write the failing tests**

```python
"""Tests for knowledge integration in the orchestrator."""

from __future__ import annotations

from pathlib import Path

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.orchestrator.knowledge import build_knowledge_summary


class TestBuildKnowledgeSummary:
    def test_returns_empty_when_no_knowledge(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            name="test", question="Q?", mode="exploratory"
        )
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        summary = build_knowledge_summary(project_dir)
        assert summary == ""

    def test_returns_summary_with_entries(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            name="test", question="Q?", mode="exploratory"
        )
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Regression is a key technique for prediction.")

        from urika.knowledge import KnowledgeStore
        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "notes.txt"))

        summary = build_knowledge_summary(project_dir)
        assert "notes.txt" in summary
        assert "Regression" in summary

    def test_truncates_long_content(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            name="test", question="Q?", mode="exploratory"
        )
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "long.txt").write_text("x" * 1000)

        from urika.knowledge import KnowledgeStore
        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "long.txt"))

        summary = build_knowledge_summary(project_dir)
        assert len(summary) < 1000

    def test_multiple_entries(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            name="test", question="Q?", mode="exploratory"
        )
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "a.txt").write_text("First note about alpha.")
        (knowledge_dir / "b.txt").write_text("Second note about beta.")

        from urika.knowledge import KnowledgeStore
        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "a.txt"))
        store.ingest(str(knowledge_dir / "b.txt"))

        summary = build_knowledge_summary(project_dir)
        assert "a.txt" in summary
        assert "b.txt" in summary
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator/test_knowledge_integration.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write the implementation**

`src/urika/orchestrator/knowledge.py`:

```python
"""Knowledge integration helpers for the orchestrator."""

from __future__ import annotations

from pathlib import Path

from urika.knowledge import KnowledgeStore

_MAX_SNIPPET = 200


def build_knowledge_summary(project_dir: Path) -> str:
    """Build a text summary of project knowledge for agent context.

    Returns an empty string if no knowledge entries exist.
    """
    store = KnowledgeStore(project_dir)
    entries = store.list_all()

    if not entries:
        return ""

    lines = ["## Available Knowledge\n"]
    for entry in entries:
        snippet = entry.content[:_MAX_SNIPPET].replace("\n", " ")
        if len(entry.content) > _MAX_SNIPPET:
            snippet += "..."
        lines.append(f"- **{entry.title}** ({entry.source_type}): {snippet}")

    return "\n".join(lines)
```

**Step 4: Run tests**

Run: `pytest tests/test_orchestrator/test_knowledge_integration.py -v`
Expected: All PASS

**Step 5: Lint and commit**

```bash
ruff check src/urika/orchestrator/knowledge.py tests/test_orchestrator/test_knowledge_integration.py
ruff format src/urika/orchestrator/knowledge.py tests/test_orchestrator/test_knowledge_integration.py
git add src/urika/orchestrator/knowledge.py tests/test_orchestrator/test_knowledge_integration.py
git commit -m "feat: add build_knowledge_summary helper"
```

---

### Task 3: Orchestrator Integration

**Files:**
- Modify: `src/urika/orchestrator/loop.py`
- Modify: `tests/test_orchestrator/test_loop.py`

**Step 1: Write the failing tests**

Add to `tests/test_orchestrator/test_loop.py`:

First add a canned literature agent response near the other canned responses:

```python
_LITERATURE_OUTPUT = """\
I scanned the knowledge directory and found existing entries.
```json
{
    "ingested": [],
    "total_entries": 1,
    "relevant_findings": [
        {"source": "notes.txt", "summary": "Notes about regression"}
    ]
}
```
"""
```

Then add the test class:

```python
class TestOrchestratorKnowledgeIntegration:
    @pytest.mark.asyncio
    async def test_runs_literature_agent_pre_loop(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        # Add knowledge so pre-loop scan has something to find
        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Some research notes.")
        from urika.knowledge import KnowledgeStore
        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "notes.txt"))

        runner = FakeRunner(
            {
                "literature_agent": [_LITERATURE_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "suggestion_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        assert runner._call_counts.get("literature_agent", 0) >= 1

    @pytest.mark.asyncio
    async def test_skips_literature_when_no_knowledge(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        runner = FakeRunner(
            {
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "suggestion_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        assert runner._call_counts.get("literature_agent", 0) == 0

    @pytest.mark.asyncio
    async def test_on_demand_literature_from_suggestion(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        suggestion_with_lit = """\
Try a different approach:
```json
{
    "suggestions": [
        {"method": "random_forest", "rationale": "Non-linear may fit better"}
    ],
    "needs_tool": false,
    "needs_literature": true
}
```
"""
        runner = FakeRunner(
            {
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_NOT_MET, _EVAL_CRITERIA_MET],
                "suggestion_agent": [suggestion_with_lit],
                "literature_agent": [_LITERATURE_OUTPUT],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        # Literature agent called on-demand (not pre-loop since no knowledge)
        assert runner._call_counts.get("literature_agent", 0) >= 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator/test_loop.py::TestOrchestratorKnowledgeIntegration -v`
Expected: FAIL — tests won't find literature_agent calls in orchestrator

**Step 3: Modify the orchestrator loop**

Edit `src/urika/orchestrator/loop.py`:

Add import at top:
```python
from urika.orchestrator.knowledge import build_knowledge_summary
```

Add pre-loop literature scan after `task_prompt = "Begin the experiment..."` and before `for turn in range(...)`:

```python
    task_prompt = "Begin the experiment. Try an initial approach."

    # --- Pre-loop: knowledge scan ---
    knowledge_summary = build_knowledge_summary(project_dir)
    if knowledge_summary:
        lit_role = registry.get("literature_agent")
        if lit_role is not None:
            lit_config = lit_role.build_config(project_dir=project_dir)
            await runner.run(lit_config, "Scan the knowledge directory and summarize available knowledge.")
        task_prompt = knowledge_summary + "\n\n" + task_prompt
```

Add on-demand literature after the existing `needs_tool` block:

```python
            # --- optional literature_agent ---
            if suggestions and suggestions.get("needs_literature"):
                lit_role = registry.get("literature_agent")
                if lit_role is not None:
                    lit_config = lit_role.build_config(project_dir=project_dir)
                    lit_result = await runner.run(lit_config, json.dumps(suggestions))
                    if lit_result.success and lit_result.text_output:
                        task_prompt = lit_result.text_output + "\n\n" + task_prompt
```

**Step 4: Run tests**

Run: `pytest tests/test_orchestrator/ -v`
Expected: All PASS (including existing tests)

**Step 5: Lint and commit**

```bash
ruff check src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
ruff format src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
git add src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
git commit -m "feat: integrate knowledge into orchestrator loop"
```

---

### Task 4: Public API Exports

**Files:**
- Modify: `src/urika/orchestrator/__init__.py`

**Step 1: Write the failing test**

Add to `tests/test_orchestrator/test_knowledge_integration.py`:

```python
class TestKnowledgePublicAPI:
    def test_build_knowledge_summary_importable(self) -> None:
        from urika.orchestrator import build_knowledge_summary
        assert callable(build_knowledge_summary)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator/test_knowledge_integration.py::TestKnowledgePublicAPI -v`
Expected: FAIL — ImportError

**Step 3: Update exports**

Add to `src/urika/orchestrator/__init__.py`:

```python
from urika.orchestrator.knowledge import build_knowledge_summary
```

And add `"build_knowledge_summary"` to `__all__`.

**Step 4: Run all tests**

Run: `pytest -v`
Expected: All pass

**Step 5: Lint and commit**

```bash
ruff check src/urika/orchestrator/__init__.py
ruff format src/urika/orchestrator/__init__.py
git add src/urika/orchestrator/__init__.py tests/test_orchestrator/test_knowledge_integration.py
git commit -m "feat: export build_knowledge_summary from orchestrator"
```
