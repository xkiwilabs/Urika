# Getting Started

Urika is a multi-agent scientific analysis platform. You give it a dataset and a research question; its agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

Urika works with data from any scientific discipline — tabular data (CSV, Excel, SPSS), images, audio, time series (EEG, HDF5), spatial/3D data, and more. Agents automatically detect your data format, install the libraries they need, and build custom tools when required.

## Requirements

- **Python 3.11 or later** (required — 3.12 also supported)
- **Anthropic API key** (`ANTHROPIC_API_KEY`) — required (see Step 3)
- **Claude Code CLI on PATH** (recommended, not required — see Step 1)

### Hardware requirements by use case

Your hardware needs depend on what kind of analysis you plan to do:

| Use Case | CPU | RAM | GPU | Storage | Example |
|----------|-----|-----|-----|---------|---------|
| **Statistical analysis** | Any modern CPU | 4 GB+ | Not needed | Minimal | T-tests, ANOVA, regression on survey data |
| **Machine learning** | Multi-core recommended | 8 GB+ | Not needed | 1-2 GB for packages | Random forest, XGBoost on tabular data |
| **Deep learning** | Multi-core | 16 GB+ | Recommended (NVIDIA, 8GB+ VRAM) | 5-10 GB for PyTorch | LSTM, Transformers for forecasting or NLP |
| **Local LLMs (private mode)** | Multi-core | 32 GB+ | Required (24GB+ VRAM) or shared memory | 50-100 GB for model weights | Running qwen3:14b or similar locally via Ollama |
| **Hybrid mode** | Multi-core | 16 GB+ | Depends on local model size | 10-50 GB | Data Agent on local model, thinking on cloud |

**Most users start with statistical analysis or machine learning** — no GPU required, works on any laptop. Deep learning and local LLMs are opt-in when you need them.

**Cloud-only mode (default):** All the heavy computation happens on your machine (Python code the agents write), but the AI reasoning happens via the Claude API. Your CPU and RAM matter for data processing; GPU only matters if agents build neural network models.

**Local/hybrid mode with Ollama:** Running local LLMs requires significant hardware. Smaller models like `qwen3:8b` need ~8 GB RAM. Larger models like `qwen3:14b` need ~16 GB RAM. See [Models and Privacy](13a-models-and-privacy.md) for configuration details.

**Shared memory systems (Apple Silicon, etc.):** Macs with M-series chips share memory between CPU and GPU. A MacBook Pro with 64 GB unified memory can run models that would require a dedicated GPU on other systems. Ollama handles this automatically.

## Step 1: Prerequisites

Urika has one hard requirement (Python) and one strong recommendation (the `claude` CLI on your PATH). Set both up before installing Urika in Step 2.

### Python 3.11+ (required)

Urika is a Python package and runs on Python 3.11 or later (3.12 also supported).

| OS | Install command |
|---|---|
| macOS | `brew install python@3.12` (or [python.org installer](https://python.org)) |
| Ubuntu 24.04 | already installed; just add the venv module: `sudo apt install python3-venv` |
| Ubuntu 22.04 | `sudo apt install python3.11 python3.11-venv` (or use `pyenv`/`conda`) |
| Fedora 38+ | already installed |
| Windows | [python.org installer](https://www.python.org/downloads/) — tick **"Add to PATH"** |

Verify:

```bash
python3 --version    # expect 3.11 or higher
```

### Claude Code CLI (recommended)

The Claude Agent SDK that Urika depends on launches a `claude` CLI binary as a subprocess for every agent run. The SDK ships its own copy of the binary inside the wheel, so this step is technically optional — Urika falls back to the bundled binary if no `claude` is on your PATH, and the bundled binary works fine for `claude-opus-4-6`, `claude-sonnet-4-5`, and `claude-haiku-4-5` (the v0.4 default model is `claude-opus-4-6`).

**Why install your own anyway:** the bundled binary lags the public `claude` release by several versions. The current bundled binary speaks an older request schema that newer models (e.g. `claude-opus-4-7`) reject with HTTP 400, surfacing as a cryptic *"Fatal error in message reader: Command failed with exit code 1"*. Installing the public CLI keeps you on the current schema and gives you per-model upgrade independence from the SDK's release cadence. Urika's runtime prefers the system `claude` over the bundled one whenever both are present.

The CLI is published as an npm package, so you'll need Node.js 18+ first:

```bash
# Install Node.js 18+
# macOS:         brew install node
# Ubuntu/Debian: sudo apt install nodejs npm
# Fedora:        sudo dnf install nodejs npm
# Windows:       installer from https://nodejs.org

# Then install the Claude Code CLI
npm install -g @anthropic-ai/claude-code
```

Verify:

```bash
claude --version    # expect 2.1.100 or higher for claude-opus-4-7 support
```

> **Don't** run `claude login` for Urika — Urika reads `ANTHROPIC_API_KEY` directly. `claude login` only matters if you also use `claude` interactively as a human, which is a separate use case from running Urika.

### Why does the agent runtime need a CLI at all?

The Claude Agent SDK is a thin wrapper that spawns `claude` as a subprocess and communicates with it over stdin/stdout. The CLI is what actually runs the agent loop (multi-turn reasoning, tool calls, conversation state), executes tools (Read, Write, Edit, Bash, Glob, Grep, …), enforces the permission system, and streams structured messages back. Authentication via `ANTHROPIC_API_KEY` is one piece of the picture; the CLI is the runtime.

## Step 2: Install Urika

**Recommended: install from source** in a Python virtual environment. Urika is under active development with frequent updates — new agents, tools, and improvements land regularly.

### Use a virtual environment

On Ubuntu 22.04+, Debian 12+, Fedora 38+, and recent macOS, system Python refuses `pip install` with `error: externally-managed-environment` (PEP 668). Create a venv before installing:

```bash
python3 -m venv ~/.venvs/urika
source ~/.venvs/urika/bin/activate    # Windows PowerShell: ~\.venvs\urika\Scripts\Activate.ps1
```

`pipx`, `conda`, and `uv` work too — pick whichever your environment manages best. Conda users can skip the venv step if they're already inside a conda environment.

### Install

```bash
git clone https://github.com/xkiwilabs/Urika.git
cd Urika
pip install -e ".[dev]"
```

To update at any time:

```bash
cd Urika
git pull
```

Because this is an editable install (`-e`), pulling new changes takes effect immediately — no reinstall needed.

**Alternative: install from PyPI** (pre-release — may lag behind source):

```bash
pip install urika
```

The PyPI package is currently a pre-release and may not include the latest features or fixes. If you start with PyPI and want to switch to source later:

```bash
pip uninstall urika
git clone https://github.com/xkiwilabs/Urika.git
cd Urika
pip install -e ".[dev]"
```

This installs everything you need for statistical analysis, machine learning, visualization, notifications, and knowledge ingestion:

| Package | What it provides |
|---------|-----------------|
| claude-agent-sdk | Agent runtime (all 12 agent roles) |
| numpy, pandas | Data manipulation |
| scipy | Scientific computing, statistical tests |
| scikit-learn | ML basics: SVM, classification, clustering, regression, cross-validation, PCA, preprocessing, pipelines |
| statsmodels | Advanced statistics: GLM, mixed effects, multilevel models, ARIMA, time series |
| pingouin | Effect sizes, Bayesian tests, ICC, partial correlations |
| matplotlib, seaborn | Charts, plots, heatmaps |
| xgboost, lightgbm | Gradient boosting |
| optuna | Hyperparameter tuning |
| shap | Model explainability |
| imbalanced-learn | Class imbalance handling |
| pypdf | PDF paper ingestion into the knowledge base |
| slack-sdk | Slack notifications and remote commands |
| python-telegram-bot | Telegram notifications and remote commands |

## Step 3: Set up your Anthropic API key

> **Important: Urika requires an Anthropic API key.**
>
> Anthropic's Consumer Terms (§3.7) and the April 2026 Agent SDK
> clarification prohibit using a Claude Pro/Max subscription with the
> Claude Agent SDK, which Urika depends on. To use Urika, you need an
> API key.
>
> 1. Sign in at [console.anthropic.com](https://console.anthropic.com).
> 2. Settings → API Keys → Create Key (label it e.g. `urika`).
> 3. Settings → Billing → Spend limits — set a monthly cap (e.g. $20).
> 4. Save the key into Urika's credential file:
>
>    ```bash
>    urika config api-key   # interactive prompt, saves to ~/.urika/secrets.env
>    ```
>
>    Or set the env var directly: `export ANTHROPIC_API_KEY=sk-ant-...`.
>
> If you also have a Claude Pro / Max subscription, you can keep using it
> for direct interactive work in Claude.ai or `claude` CLI — only the
> Urika code path requires the API key.

### Verify your API key

Once saved, run a quick check that Urika can authenticate:

```bash
urika config api-key --test
```

This sends a minimal request to `api.anthropic.com` using the configured
key. On success you'll see something like:

    ✓ API key works.  key authenticated; model=claude-haiku-4-5; reply='ok'

If the key is invalid or revoked you'll get a 401 with a hint to
regenerate. The test consumes ~13 tokens (~$0.0001).

You can also click **Test API key** on the dashboard's Settings page
once the dashboard is running.

See [Provider compliance](20-security.md#provider-compliance) for the full rationale and the citation to the Anthropic policy clarification.

## Step 4: Verify installation

```bash
urika setup
```

This checks installed packages by category, detects your hardware (CPU cores, RAM, GPU), and verifies your Claude authentication. If deep learning packages are missing, it offers to install them with automatic GPU detection.

### Optional: deep learning

The only optional install group is `[dl]` for deep learning (~2 GB download):

```bash
pip install "urika[dl]"         # + deep learning (torch, transformers, etc.)
```

| Group | Packages | What it adds |
|-------|----------|-------------|
| `[dl]` | torch, transformers, sentence-transformers, torchvision, torchaudio, timm | Neural networks, LLM fine-tuning, text embeddings, image/audio models |

You can also install deep learning packages interactively via `urika setup`, which detects whether you have an NVIDIA GPU and installs the appropriate CPU or CUDA variant.

### Agents install packages automatically

You don't need to install everything upfront. When agents need a package that isn't installed, they `pip install` it themselves during experiments. For example, if the advisor suggests trying an LSTM approach, the task agent will `pip install torch` automatically.

You can also tell agents to install specific packages:

**Via the advisor (conversational):**
```
urika:my-project> I want to use MNE for EEG analysis, can you set that up?
```
The advisor will route to the tool builder, which will `pip install mne` and create the appropriate tools.

**Via the build-tool command (direct):**
```bash
# CLI
urika build-tool my-project "install mne and create an EEG epoch extraction tool"
urika build-tool my-project "install lifelines and build a survival analysis tool"

# TUI
/build-tool install networkx and create a graph analysis tool
/build-tool install geopandas and build a spatial clustering tool
```

The tool builder installs the package, creates a reusable tool that wraps it, and registers it so all agents can use it in subsequent experiments. If you have a project venv enabled, packages install into the project's isolated environment rather than the global one.

## Troubleshooting

Common errors during install and first run:

| Error | Cause | Fix |
|---|---|---|
| `error: externally-managed-environment` on `pip install` | PEP 668 — system Python on Ubuntu 22.04+, Debian 12+, Fedora 38+, recent macOS refuses to write into the system site-packages | Create a venv (Step 2 → "Use a virtual environment"), or install via `pipx` / `conda` / `uv` |
| `Fatal error in message reader: Command failed with exit code 1` (running an agent) | The bundled `claude` CLI sends a request schema rejected by the selected model — most often `claude-opus-4-7` rejecting the deprecated `thinking.type.enabled` field | Install/upgrade the public CLI: `npm install -g @anthropic-ai/claude-code@latest` (Step 1 → "Claude Code CLI"). Or pick `claude-opus-4-6` in the dashboard's Models tab |
| `claude: command not found` after `npm install -g` | npm's global bin directory isn't on your PATH | `export PATH="$HOME/.npm-global/bin:$PATH"` in your shell rc, or run `npm config set prefix ~/.npm-global` and re-run the install |
| `npm install -g` fails with `EACCES` permission errors | npm prefix is `/usr/local` and you're not root | `npm config set prefix ~/.npm-global` then re-run the install. Avoid `sudo npm install -g` — it leaves binaries owned by root and outside your PATH |
| `⚠ ANTHROPIC_API_KEY not set` warning every command | Key was exported in your shell once but not saved to Urika's vault, and the warning fires whenever the env var is unset in a fresh shell | Run `urika config api-key` to save it permanently to `~/.urika/secrets.env`, or add `export ANTHROPIC_API_KEY=...` to your shell rc |
| `urika: command not found` after `pip install -e .` | Your venv isn't activated, or the install put the binary in a directory not on PATH | Activate the venv: `source ~/.venvs/urika/bin/activate`. Verify: `which urika` should resolve inside the venv |
| `[WinError 32] The process cannot access the file ... urika.exe` on Windows `pip install --upgrade -e .` | A previous `urika` (dashboard, TUI, or even a closed terminal that left a child python alive) is holding the entry-point exe open | Open Task Manager → Details → end any `urika.exe` and any `python.exe` whose command line mentions urika, then re-run. Alternatively log out and back in to release every file lock. Then: `pip install --upgrade --force-reinstall --no-deps -e . --no-cache-dir` |
| Garbled `?`/`???` instead of box-drawing chars in CLI banner / TUI on Windows cmd.exe | Console code page is `cp1252`. v0.4 reconfigures stdout/stderr to UTF-8 with `errors="replace"` automatically on startup, so this should self-fix | If you're still on v0.3.x, upgrade. Or set `PYTHONIOENCODING=utf-8` in your environment. Windows Terminal / PowerShell already use UTF-8 |

For provider-side compliance issues (Pro/Max OAuth refusal, etc.) see [Security Model → Provider compliance](20-security.md#provider-compliance). For per-agent model and endpoint configuration see [Models and Privacy](13a-models-and-privacy.md).

## Three ways to use Urika

Urika has three first-class interfaces that share the same commands and the same on-disk project state:

- **CLI** — Run `urika <command>` directly from your shell. Every command is fully scriptable with `--json` output for custom tooling. Best for scripting, automation, batch processing, and building custom workflows on top of Urika.
- **Interactive TUI** — Run `urika` with no arguments. A full-screen Textual terminal interface with an output panel, input bar with tab completion, animated activity bar, and status bar. Type slash commands (`/help`, `/run`, `/project`) or ask questions in plain text — the orchestrator coordinates agents for you. Best for learning the system and exploratory work.
- **Dashboard** — Run `urika dashboard [project]` to open a browser-based view of the project. Multi-page FastAPI app with experiment timelines, leaderboards, log streaming, advisor chat, sessions, and settings forms. Best for monitoring long runs, sharing results with collaborators, and editing settings through a UI.

If you're new to Urika, **start with the TUI** — you can discover all commands with tab completion and `/help`, and ask the orchestrator questions in plain text without needing to know any commands at all.

A classic prompt-toolkit REPL is also available via `urika --classic` if you prefer a simpler interface.

See [Interfaces Overview](02-interfaces-overview.md) for a task-by-task cheat sheet across all three. Detailed guides: [CLI Reference](16a-cli-projects.md), [Interactive TUI](17-interactive-tui.md), [Dashboard](18a-dashboard-pages.md).

## Quickstart

### 1. Create a project

```bash
urika new my-study --data /path/to/data.csv
```

Urika prompts for a research question, investigation mode, and description. The project builder agent asks clarifying questions, proposes initial experiments, and writes the project files.

### 2. Launch the TUI (recommended for first-time users)

```bash
urika
```

This opens the interactive TUI. Load your project and explore:

```
urika> /project my-study
urika:my-study> /status
urika:my-study> /run
```

Or type a question in plain text — it goes straight to the advisor agent:

```
urika:my-study> what approaches should I try for this dataset?
```

### 3. Or use CLI commands directly

```bash
urika run my-study --dry-run    # preview the planned pipeline (no agents invoked)
urika run my-study              # run the next experiment
urika status my-study           # check progress
urika results my-study          # view leaderboard
urika report my-study           # generate reports
urika present my-study          # generate presentation
urika dashboard my-study        # browse everything in your browser
```

Every slash command has a matching CLI command and vice versa.

> **Heads up:** Urika's task agent writes Python code into your project and executes it. `--dry-run` lets you preview the planned pipeline (which agents will run, which directories they can write to) before any code executes. See [Security Model](20-security.md) for the full agent-execution model.

## Project location

By default, projects are created under `~/urika-projects/`. Override this with the `URIKA_PROJECTS_DIR` environment variable:

```bash
export URIKA_PROJECTS_DIR="/path/to/my/projects"
```

---

**Next:** [Interfaces Overview](02-interfaces-overview.md)

## Further reading

- [Interfaces Overview](02-interfaces-overview.md) -- CLI, TUI, dashboard cheat sheet
- [Core Concepts](03-core-concepts.md) -- hierarchy, agents, tools, orchestrator loop
- [Creating Projects](04-creating-projects.md) -- detailed guide to `urika new`
- [Running Experiments](06-running-experiments.md) -- orchestrator, turns, auto mode
