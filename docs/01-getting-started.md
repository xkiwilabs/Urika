# Getting Started

Urika is a multi-agent scientific analysis platform. You give it a dataset and a research question; its agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

Urika works with data from any scientific discipline — tabular data (CSV, Excel, SPSS), images, audio, time series (EEG, HDF5), spatial/3D data, and more. Agents automatically detect your data format, install the libraries they need, and build custom tools when required.

## Requirements

- **Python 3.11 or later** (3.12 also supported)
- **Anthropic API key** (`ANTHROPIC_API_KEY`) — required (see callout below)
- **Claude Code CLI** — required as the agent runtime

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

**Local/hybrid mode with Ollama:** Running local LLMs requires significant hardware. Smaller models like `qwen3:8b` need ~8 GB RAM. Larger models like `qwen3:14b` need ~16 GB RAM. See [Models and Privacy](13-models-and-privacy.md) for configuration details.

**Shared memory systems (Apple Silicon, etc.):** Macs with M-series chips share memory between CPU and GPU. A MacBook Pro with 64 GB unified memory can run models that would require a dedicated GPU on other systems. Ollama handles this automatically.

## Step 1: Install Claude Code CLI

Urika uses the Claude Agent SDK, which requires the Claude Code CLI as the agent runtime. Install it first:

```bash
npm install -g @anthropic-ai/claude-code
```

> **Note:** You need Node.js 18+ installed. If you don't have it: `sudo apt install nodejs npm` (Linux) or `brew install node` (macOS).

### Verify installation

```bash
claude --version
```

If you see a version number, the CLI is installed and ready. (Login via `claude login` is only needed for direct interactive use of the CLI by a human — Urika authenticates via `ANTHROPIC_API_KEY`; see the callout below.)

## Step 2: Set up your Anthropic API key

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

See [Provider compliance](20-security.md#provider-compliance) for the full rationale and the citation to the Anthropic policy clarification.

## Step 3: Install Urika

**Recommended: install from source.** Urika is under active development with frequent updates — new agents, tools, and improvements land regularly. Installing from source ensures you always have the latest version:

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

## Three ways to use Urika

Urika has three first-class interfaces that share the same commands and the same on-disk project state:

- **CLI** — Run `urika <command>` directly from your shell. Every command is fully scriptable with `--json` output for custom tooling. Best for scripting, automation, batch processing, and building custom workflows on top of Urika.
- **Interactive TUI** — Run `urika` with no arguments. A full-screen Textual terminal interface with an output panel, input bar with tab completion, animated activity bar, and status bar. Type slash commands (`/help`, `/run`, `/project`) or ask questions in plain text — the orchestrator coordinates agents for you. Best for learning the system and exploratory work.
- **Dashboard** — Run `urika dashboard [project]` to open a browser-based view of the project. Multi-page FastAPI app with experiment timelines, leaderboards, log streaming, advisor chat, sessions, and settings forms. Best for monitoring long runs, sharing results with collaborators, and editing settings through a UI.

If you're new to Urika, **start with the TUI** — you can discover all commands with tab completion and `/help`, and ask the orchestrator questions in plain text without needing to know any commands at all.

A classic prompt-toolkit REPL is also available via `urika --classic` if you prefer a simpler interface.

See [Interfaces Overview](02-interfaces-overview.md) for a task-by-task cheat sheet across all three. Detailed guides: [CLI Reference](16-cli-reference.md), [Interactive TUI](17-interactive-tui.md), [Dashboard](18-dashboard.md).

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
