# CLI Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 new CLI commands/groups (`experiment`, `results`, `methods`, `tools`) to wire existing infrastructure into the Urika CLI.

**Architecture:** All changes in `src/urika/cli.py` only — pure wiring of existing core functions into Click commands. Tests use Click's `CliRunner` with the existing `urika_env` fixture pattern from `tests/test_cli.py`.

**Tech Stack:** Click (already installed), existing core modules

---

## Reference Files

Before starting, read these to understand existing patterns:

- `src/urika/cli.py` — Current CLI with `new`, `list`, `status` commands
- `tests/test_cli.py` — Existing CLI tests (CliRunner pattern, `urika_env` fixture)
- `src/urika/core/experiment.py` — `create_experiment()`, `list_experiments()`
- `src/urika/core/progress.py` — `load_progress()`
- `src/urika/evaluation/leaderboard.py` — `load_leaderboard()`
- `src/urika/methods/registry.py` — `MethodRegistry`
- `src/urika/tools/registry.py` — `ToolRegistry`

---

### Task 1: `_resolve_project` Helper + Refactor `status`

**Files:**
- Modify: `src/urika/cli.py:78-109`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class TestResolveProject:
    def test_resolve_valid_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """status command still works after refactoring to use _resolve_project."""
        runner.invoke(
            cli,
            ["new", "test", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["status", "test"], env=urika_env)
        assert result.exit_code == 0
        assert "Does X?" in result.output

    def test_resolve_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["status", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output
```

**Step 2: Run tests to verify they pass (these test existing behavior)**

Run: `pytest tests/test_cli.py::TestResolveProject -v`
Expected: PASS (since status already works)

**Step 3: Extract `_resolve_project` helper and refactor `status`**

In `src/urika/cli.py`, add the helper after `_projects_dir()` and refactor `status` to use it:

```python
def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name. Raises ClickException on error."""
    registry = ProjectRegistry()
    project_path = registry.get(name)
    if project_path is None:
        raise click.ClickException(f"Project '{name}' not found in registry.")
    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise click.ClickException(f"Project directory missing at {project_path}")
    return project_path, config


@cli.command()
@click.argument("name")
def status(name: str) -> None:
    """Show project status."""
    project_path, config = _resolve_project(name)
    experiments = list_experiments(project_path)

    click.echo(f"Project: {config.name}")
    click.echo(f"Question: {config.question}")
    click.echo(f"Mode: {config.mode}")
    click.echo(f"Path: {project_path}")
    click.echo(f"Experiments: {len(experiments)}")

    if experiments:
        click.echo("")
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            n_runs = len(progress.get("runs", []))
            exp_status = progress.get("status", "unknown")
            click.echo(
                f"  {exp.experiment_id}: {exp.name} [{exp_status}, {n_runs} runs]"
            )
```

**Step 4: Run all CLI tests**

Run: `pytest tests/test_cli.py -v`
Expected: All PASS (existing + new)

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "refactor: extract _resolve_project helper in CLI"
```

---

### Task 2: `urika experiment create` and `urika experiment list`

**Files:**
- Modify: `src/urika/cli.py` — add `experiment` group with `create` and `list` subcommands
- Modify: `tests/test_cli.py` — add tests

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestExperimentCreateCommand:
    def test_creates_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Question?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["experiment", "create", "proj", "baseline", "--hypothesis", "Test H"],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "exp-001" in result.output

    def test_creates_second_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Q?", "-m", "exploratory"],
            env=urika_env,
        )
        runner.invoke(
            cli,
            ["experiment", "create", "proj", "first", "--hypothesis", "H1"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["experiment", "create", "proj", "second", "--hypothesis", "H2"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "exp-002" in result.output

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["experiment", "create", "nope", "test", "--hypothesis", "H"],
            env=urika_env,
        )
        assert result.exit_code != 0


class TestExperimentListCommand:
    def test_empty(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Q?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli, ["experiment", "list", "proj"], env=urika_env
        )
        assert result.exit_code == 0
        assert "No experiments" in result.output

    def test_shows_experiments(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Q?", "-m", "exploratory"],
            env=urika_env,
        )
        runner.invoke(
            cli,
            ["experiment", "create", "proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        result = runner.invoke(
            cli, ["experiment", "list", "proj"], env=urika_env
        )
        assert result.exit_code == 0
        assert "baseline" in result.output
        assert "exp-001" in result.output

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["experiment", "list", "nope"], env=urika_env
        )
        assert result.exit_code != 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::TestExperimentCreateCommand -v`
Expected: FAIL — `No such command 'experiment'`

**Step 3: Write the implementation**

Add to `src/urika/cli.py`, import `create_experiment` at the top:

```python
from urika.core.experiment import create_experiment, list_experiments
```

(Replace the existing `list_experiments`-only import.)

Then add the command group:

```python
@cli.group()
def experiment() -> None:
    """Manage experiments within a project."""


@experiment.command("create")
@click.argument("project")
@click.argument("name")
@click.option("--hypothesis", required=True, help="Experiment hypothesis.")
def experiment_create(project: str, name: str, hypothesis: str) -> None:
    """Create a new experiment in a project."""
    project_path, _config = _resolve_project(project)
    exp = create_experiment(project_path, name=name, hypothesis=hypothesis)
    click.echo(f"Created experiment '{exp.name}' ({exp.experiment_id})")


@experiment.command("list")
@click.argument("project")
def experiment_list(project: str) -> None:
    """List experiments in a project."""
    project_path, _config = _resolve_project(project)
    experiments = list_experiments(project_path)

    if not experiments:
        click.echo("No experiments yet.")
        return

    for exp in experiments:
        progress = load_progress(project_path, exp.experiment_id)
        n_runs = len(progress.get("runs", []))
        exp_status = progress.get("status", "unknown")
        click.echo(f"  {exp.experiment_id}: {exp.name} [{exp_status}, {n_runs} runs]")
```

**Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: add experiment create and list CLI commands"
```

---

### Task 3: `urika results`

**Files:**
- Modify: `src/urika/cli.py` — add `results` command
- Modify: `tests/test_cli.py` — add tests

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`. Also add this import at the top:

```python
from urika.evaluation.leaderboard import update_leaderboard
```

Then:

```python
class TestResultsCommand:
    def test_empty_leaderboard(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Q?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["results", "proj"], env=urika_env)
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_shows_leaderboard(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Q?", "-m", "exploratory"],
            env=urika_env,
        )
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "proj"
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.85, "rmse": 0.12},
            run_id="run-001",
            params={"alpha": 0.1},
            primary_metric="r2",
            direction="higher_is_better",
        )
        result = runner.invoke(cli, ["results", "proj"], env=urika_env)
        assert result.exit_code == 0
        assert "linear_regression" in result.output
        assert "0.85" in result.output

    def test_shows_experiment_runs(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "proj", "-q", "Q?", "-m", "exploratory"],
            env=urika_env,
        )
        runner.invoke(
            cli,
            ["experiment", "create", "proj", "baseline", "--hypothesis", "H"],
            env=urika_env,
        )
        # Write a run directly to progress.json
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "proj"
        from urika.core.progress import append_run
        from urika.core.models import RunRecord

        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.75},
            hypothesis="Baseline",
            observation="Decent fit",
            next_step="Try RF",
        )
        append_run(project_dir, "exp-001-baseline", run)

        result = runner.invoke(
            cli,
            ["results", "proj", "--experiment", "exp-001-baseline"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "linear_regression" in result.output

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["results", "nope"], env=urika_env)
        assert result.exit_code != 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::TestResultsCommand -v`
Expected: FAIL — `No such command 'results'`

**Step 3: Write the implementation**

Add import at top of `src/urika/cli.py`:

```python
from urika.evaluation.leaderboard import load_leaderboard
```

Then add the command:

```python
@cli.command()
@click.argument("project")
@click.option("--experiment", default=None, help="Show runs for a specific experiment.")
def results(project: str, experiment: str | None) -> None:
    """Show results: leaderboard or experiment runs."""
    project_path, _config = _resolve_project(project)

    if experiment:
        progress = load_progress(project_path, experiment)
        runs = progress.get("runs", [])
        if not runs:
            click.echo(f"No runs in {experiment}.")
            return
        for run in runs:
            method = run.get("method", "unknown")
            metrics = run.get("metrics", {})
            metrics_str = ", ".join(f"{k}={v:.4f}" for k, v in metrics.items())
            click.echo(f"  {run.get('run_id', '?')}: {method} — {metrics_str}")
    else:
        lb = load_leaderboard(project_path)
        ranking = lb.get("ranking", [])
        if not ranking:
            click.echo("No results yet.")
            return

        primary = lb.get("primary_metric", "")
        click.echo(f"Leaderboard (by {primary}):\n")
        for entry in ranking:
            rank = entry.get("rank", "?")
            method = entry.get("method", "unknown")
            metrics = entry.get("metrics", {})
            metrics_str = ", ".join(f"{k}={v:.4f}" for k, v in metrics.items())
            click.echo(f"  #{rank} {method} — {metrics_str}")
```

**Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: add results CLI command"
```

---

### Task 4: `urika methods` and `urika tools`

**Files:**
- Modify: `src/urika/cli.py` — add `methods` and `tools` commands
- Modify: `tests/test_cli.py` — add tests

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestMethodsCommand:
    def test_lists_builtin_methods(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["methods"], env=urika_env)
        assert result.exit_code == 0
        assert "linear_regression" in result.output
        assert "random_forest" in result.output
        assert "paired_t_test" in result.output

    def test_filter_by_category(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["methods", "--category", "regression"], env=urika_env
        )
        assert result.exit_code == 0
        assert "linear_regression" in result.output
        assert "random_forest" in result.output
        assert "paired_t_test" not in result.output

    def test_empty_category(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["methods", "--category", "nonexistent"], env=urika_env
        )
        assert result.exit_code == 0
        assert "No methods" in result.output


class TestToolsCommand:
    def test_lists_builtin_tools(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["tools"], env=urika_env)
        assert result.exit_code == 0
        assert "data_profiler" in result.output
        assert "correlation_analysis" in result.output

    def test_filter_by_category(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["tools", "--category", "exploration"], env=urika_env
        )
        assert result.exit_code == 0
        assert "data_profiler" in result.output

    def test_empty_category(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["tools", "--category", "nonexistent"], env=urika_env
        )
        assert result.exit_code == 0
        assert "No tools" in result.output
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::TestMethodsCommand -v`
Expected: FAIL — `No such command 'methods'`

**Step 3: Write the implementation**

Add imports at top of `src/urika/cli.py`:

```python
from urika.methods import MethodRegistry
from urika.tools import ToolRegistry
```

Then add the commands:

```python
@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific methods.")
def methods(category: str | None, project: str | None) -> None:
    """List available analysis methods."""
    registry = MethodRegistry()
    registry.discover()

    if project:
        project_path, _config = _resolve_project(project)
        registry.discover_project(project_path / "methods")

    if category:
        names = registry.list_by_category(category)
    else:
        names = registry.list_all()

    if not names:
        click.echo("No methods found." if not category else f"No methods in category '{category}'.")
        return

    for name in names:
        method = registry.get(name)
        if method:
            click.echo(f"  {name}  [{method.category()}]  {method.description()}")


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific tools.")
def tools(category: str | None, project: str | None) -> None:
    """List available analysis tools."""
    registry = ToolRegistry()
    registry.discover()

    if project:
        project_path, _config = _resolve_project(project)
        registry.discover_project(project_path / "tools")

    if category:
        names = registry.list_by_category(category)
    else:
        names = registry.list_all()

    if not names:
        click.echo("No tools found." if not category else f"No tools in category '{category}'.")
        return

    for name in names:
        tool = registry.get(name)
        if tool:
            click.echo(f"  {name}  [{tool.category()}]  {tool.description()}")
```

**Step 4: Run all tests**

Run: `pytest tests/test_cli.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `pytest -v`
Expected: All 385+ tests pass

**Step 6: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: add methods and tools CLI commands"
```
