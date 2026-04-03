# Getting Started

Urika is a multi-agent scientific analysis platform. You give it a dataset and a research question; its agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

Urika works with data from any scientific discipline — tabular data (CSV, Excel, SPSS), images, audio, time series (EEG, HDF5), spatial/3D data, and more. Agents automatically detect your data format, install the libraries they need, and build custom tools when required.

## Requirements

- **Python 3.11 or later** (3.12 also supported)
- **Claude Pro or Max account** (recommended), or an Anthropic API key
- **Claude Code CLI** — required for authentication and as the agent runtime

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

**Local/hybrid mode with Ollama:** Running local LLMs requires significant hardware. Smaller models like `qwen3:8b` need ~8 GB RAM. Larger models like `qwen3:14b` need ~16 GB RAM. See [Models and Privacy](12-models-and-privacy.md) for configuration details.

**Shared memory systems (Apple Silicon, etc.):** Macs with M-series chips share memory between CPU and GPU. A MacBook Pro with 64 GB unified memory can run models that would require a dedicated GPU on other systems. Ollama handles this automatically.

## Step 1: Install Claude Code CLI

Urika uses the Claude Agent SDK, which requires the Claude Code CLI for authentication and as the agent runtime. Install it first:

```bash
npm install -g @anthropic-ai/claude-code
```

> **Note:** You need Node.js 18+ installed. If you don't have it: `sudo apt install nodejs npm` (Linux) or `brew install node` (macOS).

### Log in to Claude

```bash
claude login
```

This opens a browser window to authenticate with your Anthropic account. You need at least a **Claude Pro** account ($20/month). **Claude Max** ($100/month or $200/month) is recommended for heavy use as it provides higher rate limits.

> **Why Pro or Max?** Urika's agents make many API calls during experiments — planning, coding, evaluating, advising. A free account's rate limits are too restrictive for multi-agent workflows. Pro gives you enough headroom for most projects. Max is better if you run multiple experiments or large projects.

### Verify login

```bash
claude --version
```

If you see a version number, you're authenticated and ready.

### Alternative: API key

If you prefer to use an API key instead of a Pro/Max account:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add this to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) to persist it across sessions. Note that API key usage is billed per token, which can be more expensive than a Pro/Max subscription for heavy use.

## Step 2: Install Urika

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
| claude-agent-sdk | Agent runtime (all 11 agent roles) |
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

## Step 3: Verify installation

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

# REPL
/build-tool install networkx and create a graph analysis tool
/build-tool install geopandas and build a spatial clustering tool
```

The tool builder installs the package, creates a reusable tool that wraps it, and registers it so all agents can use it in subsequent experiments. If you have a project venv enabled, packages install into the project's isolated environment rather than the global one.

## Two ways to use Urika

Urika has two interfaces that share the same commands and produce identical results:

- **Interactive REPL** — Run `urika` with no arguments. Gives you a prompt with tab completion, `/help`, conversation history, and a bottom status bar. Best for learning the system and exploratory work.
- **CLI commands** — Run `urika <command>` directly from your shell. Every command is fully scriptable with `--json` output for custom tooling. Best for scripting, automation, batch processing, and building custom workflows on top of Urika.

If you're new to Urika, **start with the REPL** — you can discover all commands with tab completion and `/help`, and ask the advisor agent questions in plain text without needing to know any commands at all.

See [CLI Reference](15-cli-reference.md) and [Interactive REPL](16-interactive-repl.md) for full details on each interface.

## Quickstart

### 1. Create a project

```bash
urika new my-study --data /path/to/data.csv
```

Urika prompts for a research question, investigation mode, and description. The project builder agent asks clarifying questions, proposes initial experiments, and writes the project files.

### 2. Launch the REPL (recommended for first-time users)

```bash
urika
```

This opens the interactive shell. Load your project and explore:

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
urika run my-study              # run the next experiment
urika status my-study           # check progress
urika results my-study          # view leaderboard
urika report my-study           # generate reports
urika present my-study          # generate presentation
urika dashboard my-study        # browse everything in your browser
```

Every REPL slash command has a matching CLI command and vice versa.

## Project location

By default, projects are created under `~/urika-projects/`. Override this with the `URIKA_PROJECTS_DIR` environment variable:

```bash
export URIKA_PROJECTS_DIR="/path/to/my/projects"
```

---

**Next:** [Core Concepts](02-core-concepts.md)

## Further reading

- [Core Concepts](02-core-concepts.md) -- hierarchy, agents, tools, orchestrator loop
- [Creating Projects](03-creating-projects.md) -- detailed guide to `urika new`
- [Running Experiments](05-running-experiments.md) -- orchestrator, turns, auto mode
