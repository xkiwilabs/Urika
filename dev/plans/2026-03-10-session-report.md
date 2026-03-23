# Session Management & Report Generation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire existing session and labbook infrastructure into `urika run --continue` and `urika report` CLI commands.

**Architecture:** Modify `run_experiment()` to accept a `resume` parameter that calls `resume_session` instead of `start_session` and picks up from the last turn. Add `--continue` flag to the `run` CLI command. Add a `report` CLI command that calls existing labbook generators. No new modules — pure wiring.

**Tech Stack:** Python, Click, existing `session.py` + `labbook.py` + `progress.py`

---

### Task 1: Add `resume` parameter to `run_experiment()`

**Files:**
- Modify: `src/urika/orchestrator/loop.py:26-46`
- Test: `tests/test_orchestrator/test_loop.py`

**Step 1: Write the failing tests**

Add these tests to `tests/test_orchestrator/test_loop.py`:

```python
class TestOrchestratorResume:
    @pytest.mark.asyncio
    async def test_resume_calls_resume_session(self, tmp_path: Path) -> None:
        """When resume=True, run_experiment calls resume_session, not start_session."""
        project_dir, exp_id = _setup_project(tmp_path)

        # Start and pause a session first
        from urika.core.session import start_session, pause_session
        start_session(project_dir, exp_id, max_turns=50)
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "suggestion_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=5, resume=True
        )

        assert result["status"] == "completed"

        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_resume_starts_from_current_turn(self, tmp_path: Path) -> None:
        """When resuming, the loop starts from the session's current_turn."""
        project_dir, exp_id = _setup_project(tmp_path)

        from urika.core.session import start_session, pause_session, update_turn
        start_session(project_dir, exp_id, max_turns=10)
        update_turn(project_dir, exp_id)  # turn 1
        update_turn(project_dir, exp_id)  # turn 2
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "suggestion_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=10, resume=True
        )

        assert result["status"] == "completed"
        # Should report the turn it completed on (3, since 2 were already done)
        assert result["turns"] == 3

    @pytest.mark.asyncio
    async def test_resume_uses_last_suggestion_as_prompt(self, tmp_path: Path) -> None:
        """When resuming, last suggestion from progress is used as initial prompt."""
        project_dir, exp_id = _setup_project(tmp_path)

        from urika.core.session import start_session, pause_session
        from urika.core.models import RunRecord
        from urika.core.progress import append_run
        start_session(project_dir, exp_id, max_turns=10)
        run = RunRecord(
            run_id="run-001",
            method="lr",
            params={},
            metrics={"r2": 0.5},
            next_step="Try random forest",
        )
        append_run(project_dir, exp_id, run)
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "suggestion_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=10, resume=True
        )

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_resume_false_is_default(self, tmp_path: Path) -> None:
        """Default behavior (resume=False) still calls start_session."""
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
        session = load_session(project_dir, exp_id)
        assert session is not None

    @pytest.mark.asyncio
    async def test_resume_on_non_paused_session_fails(self, tmp_path: Path) -> None:
        """Resuming a session that isn't paused/failed should fail gracefully."""
        project_dir, exp_id = _setup_project(tmp_path)
        # No session exists at all
        runner = FakeRunner(
            {
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "suggestion_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=5, resume=True
        )

        assert result["status"] == "failed"
        assert "error" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator/test_loop.py::TestOrchestratorResume -v`
Expected: FAIL with `TypeError: run_experiment() got an unexpected keyword argument 'resume'`

**Step 3: Implement `resume` parameter in `run_experiment()`**

Modify `src/urika/orchestrator/loop.py`. Add `resume_session` to the imports from `urika.core.session`, and add the `resume` parameter:

```python
from urika.core.session import (
    complete_session,
    fail_session,
    load_session,
    resume_session,
    start_session,
    update_turn,
)


async def run_experiment(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    *,
    max_turns: int = 50,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the orchestration loop for an experiment.

    Cycles through task_agent -> evaluator -> suggestion_agent until
    criteria are met or max_turns is reached.
    """
    registry = AgentRegistry()
    registry.discover()

    start_turn = 1

    if resume:
        try:
            state = resume_session(project_dir, experiment_id)
            start_turn = state.current_turn + 1
        except (FileNotFoundError, RuntimeError) as exc:
            return {"status": "failed", "error": str(exc), "turns": 0}
    else:
        try:
            start_session(project_dir, experiment_id, max_turns=max_turns)
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "turns": 0}

    # Build initial task prompt
    if resume:
        progress = load_progress(project_dir, experiment_id)
        runs = progress.get("runs", [])
        if runs and runs[-1].get("next_step"):
            task_prompt = runs[-1]["next_step"]
        else:
            task_prompt = "Continue the experiment with a different approach."
    else:
        task_prompt = "Begin the experiment. Try an initial approach."

    # --- Pre-loop: knowledge scan ---
    # ... (existing knowledge scan code, unchanged)
```

The loop range changes from `range(1, max_turns + 1)` to `range(start_turn, max_turns + 1)`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator/test_loop.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
git commit -m "feat: add resume parameter to run_experiment"
```

---

### Task 2: Add `--continue` flag to `urika run` CLI

**Files:**
- Modify: `src/urika/cli.py:247-285`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestRunContinueFlag:
    def test_continue_passes_resume_true(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """--continue flag passes resume=True to run_experiment."""
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )

        # Pre-create a paused session so resume works
        from urika.core.session import start_session, pause_session
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        exp_dirs = sorted((project_dir / "experiments").iterdir())
        exp_id = exp_dirs[0].name
        start_session(project_dir, exp_id, max_turns=50)
        pause_session(project_dir, exp_id)

        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 3, "error": None}
            result = runner.invoke(
                cli,
                ["run", "test-proj", "--continue"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        # Verify resume=True was passed
        _, kwargs = mock_run.call_args
        assert kwargs.get("resume") is True

    def test_run_without_continue_passes_resume_false(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """Without --continue, resume defaults to False."""
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 1, "error": None}
            result = runner.invoke(cli, ["run", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        _, kwargs = mock_run.call_args
        assert kwargs.get("resume") is False

    def test_continue_with_experiment_flag(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """--continue works together with --experiment."""
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 2, "error": None}
            result = runner.invoke(
                cli,
                ["run", "test-proj", "--experiment", "exp-001-baseline", "--continue"],
                env=urika_env,
            )
        assert result.exit_code == 0
        _, kwargs = mock_run.call_args
        assert kwargs.get("resume") is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::TestRunContinueFlag -v`
Expected: FAIL with `no such option: --continue`

**Step 3: Implement `--continue` flag**

Modify the `run` command in `src/urika/cli.py`:

```python
@cli.command()
@click.argument("project")
@click.option(
    "--experiment", "experiment_id", default=None, help="Experiment ID to run."
)
@click.option("--max-turns", default=50, help="Maximum orchestrator turns.")
@click.option(
    "--continue", "resume", is_flag=True, default=False,
    help="Resume a paused or failed experiment.",
)
def run(project: str, experiment_id: str | None, max_turns: int, resume: bool) -> None:
    """Run an experiment using the orchestrator."""
    from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
    from urika.orchestrator import run_experiment

    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException(
                "No experiments in this project. Create one first."
            )
        experiment_id = experiments[-1].experiment_id
        click.echo(f"Using latest experiment: {experiment_id}")

    if resume:
        click.echo(f"Resuming experiment {experiment_id}...")
    else:
        click.echo(f"Running experiment {experiment_id} (max {max_turns} turns)...")

    runner_instance = ClaudeSDKRunner()
    result = asyncio.run(
        run_experiment(
            project_path,
            experiment_id,
            runner_instance,
            max_turns=max_turns,
            resume=resume,
        )
    )

    status_val = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    if status_val == "completed":
        click.echo(f"Experiment completed after {turns} turns.")
    elif status_val == "failed":
        click.echo(f"Experiment failed after {turns} turns: {error}")
    else:
        click.echo(f"Experiment finished with status: {status_val} ({turns} turns)")
```

Note: The variable name for the runner instance is changed to `runner_instance` to avoid shadowing the `runner` fixture name if needed. Also the variable `status` is renamed to `status_val` to avoid shadowing the `status` command.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: add --continue flag to urika run CLI"
```

---

### Task 3: Add `urika report` CLI command

**Files:**
- Modify: `src/urika/cli.py` (add after the `knowledge` group, before EOF)
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestReportCommand:
    def test_report_project_level(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """urika report <project> generates project-level summaries."""
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["report", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "results-summary.md" in result.output
        assert "key-findings.md" in result.output

    def test_report_experiment_level(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """urika report <project> --experiment <id> generates experiment summary."""
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        exp_dirs = sorted((project_dir / "experiments").iterdir())
        exp_id = exp_dirs[0].name

        result = runner.invoke(
            cli,
            ["report", "test-proj", "--experiment", exp_id],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "summary.md" in result.output
        assert "notes.md" in result.output

    def test_report_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["report", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_report_nonexistent_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            ["report", "test-proj", "--experiment", "exp-999-nope"],
            env=urika_env,
        )
        assert result.exit_code != 0

    def test_report_creates_files(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """Report command actually writes labbook files."""
        _create_project(runner, urika_env)
        runner.invoke(cli, ["report", "test-proj"], env=urika_env)
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        assert (project_dir / "labbook" / "results-summary.md").exists()
        assert (project_dir / "labbook" / "key-findings.md").exists()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::TestReportCommand -v`
Expected: FAIL with `No such command 'report'`

**Step 3: Implement `report` command**

Add to `src/urika/cli.py` after the `knowledge` group:

```python
@cli.command()
@click.argument("project")
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Generate report for a specific experiment.",
)
def report(project: str, experiment_id: str | None) -> None:
    """Generate labbook reports."""
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )

    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        try:
            update_experiment_notes(project_path, experiment_id)
            generate_experiment_summary(project_path, experiment_id)
        except FileNotFoundError:
            raise click.ClickException(
                f"Experiment '{experiment_id}' not found."
            )
        notes = project_path / "experiments" / experiment_id / "labbook" / "notes.md"
        summary = project_path / "experiments" / experiment_id / "labbook" / "summary.md"
        click.echo(f"Updated: {notes}")
        click.echo(f"Generated: {summary}")
        return

    # Project-level reports
    generate_results_summary(project_path)
    generate_key_findings(project_path)

    # Also refresh notes for all experiments
    for exp in list_experiments(project_path):
        update_experiment_notes(project_path, exp.experiment_id)

    results_path = project_path / "labbook" / "results-summary.md"
    findings_path = project_path / "labbook" / "key-findings.md"
    click.echo(f"Generated: {results_path}")
    click.echo(f"Generated: {findings_path}")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: add urika report CLI command"
```

---

### Task 4: Full integration verification

**Files:**
- No new files
- Run: full test suite

**Step 1: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS (should be ~540+ tests)

**Step 2: Run linting**

Run: `ruff check src/ tests/`
Expected: No errors

Run: `ruff format --check src/ tests/`
Expected: No formatting issues

**Step 3: Commit if any fixes needed**

If linting required fixes:
```bash
ruff format src/ tests/
git add -u
git commit -m "style: format session and report code"
```
