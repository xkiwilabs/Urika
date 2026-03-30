# Contributing to Urika

Thanks for your interest in contributing to Urika! This document covers the basics for getting started.

## Development Setup

```bash
git clone https://github.com/xkiwilabs/Urika.git
cd Urika
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest -v              # Full test suite
pytest tests/test_core # Specific module
ruff check src/ tests/ # Lint
ruff format src/ tests/ # Format
```

## Code Style

- Python 3.11+
- Type annotations on all public functions
- `ruff` for linting and formatting (config in `pyproject.toml`)
- Tests use `pytest` with fixtures in `conftest.py`

## Project Structure

```
src/urika/
  agents/       # Agent roles, prompts, registry, SDK adapter
  orchestrator/ # Experiment loop, meta-orchestrator, finalize
  core/         # Models, workspace, progress, labbook, criteria
  tools/        # Built-in statistical and ML tools
  data/         # Data loading and profiling
  evaluation/   # Leaderboard and metric computation
  knowledge/    # Knowledge pipeline (PDF, text, URL)
  methods/      # Agent-created analytical pipelines
  notifications/ # Email, Slack, Telegram channels
  templates/    # Reveal.js presentation assets
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch from `dev`
3. Make your changes with tests
4. Run the full test suite: `pytest -v`
5. Run the linter: `ruff check src/ tests/`
6. Open a pull request against `dev`

## Reporting Issues

Open an issue at [GitHub Issues](https://github.com/xkiwilabs/Urika/issues) with:
- What you expected vs what happened
- Steps to reproduce
- Urika version (`urika --version`)
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the project's license.
