# Getting Started

Urika is a multi-agent scientific analysis platform. You give it a dataset and a research question; its agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

Urika works with data from any scientific discipline — tabular data (CSV, Excel, SPSS), images, audio, time series (EEG, HDF5), spatial/3D data, and more. Agents automatically detect your data format, install the libraries they need, and build custom tools when required.

## Requirements

- **Python 3.11 or later** (3.12 also supported)
- **Claude access** via Anthropic API key or Claude Max/Pro account

### Hardware requirements by use case

Your hardware needs depend on what kind of analysis you plan to do:

| Use Case | CPU | RAM | GPU | Storage | Example |
|----------|-----|-----|-----|---------|---------|
| **Statistical analysis** | Any modern CPU | 4 GB+ | Not needed | Minimal | T-tests, ANOVA, regression on survey data |
| **Machine learning** | Multi-core recommended | 8 GB+ | Not needed | 1-2 GB for packages | Random forest, XGBoost on tabular data |
| **Deep learning** | Multi-core | 16 GB+ | Recommended (NVIDIA, 8GB+ VRAM) | 5-10 GB for PyTorch | LSTM, Transformers for forecasting or NLP |
| **Local LLMs (private mode)** | Multi-core | 32 GB+ | Required (24GB+ VRAM) or shared memory | 50-100 GB for model weights | Running gpt-oss:120b or similar locally via Ollama |
| **Hybrid mode** | Multi-core | 16 GB+ | Depends on local model size | 10-50 GB | Data Agent on local model, thinking on cloud |

**Most users start with statistical analysis or machine learning** — no GPU required, works on any laptop. Deep learning and local LLMs are opt-in when you need them.

**Cloud-only mode (default):** All the heavy computation happens on your machine (Python code the agents write), but the AI reasoning happens via the Claude API. Your CPU and RAM matter for data processing; GPU only matters if agents build neural network models.

**Local/hybrid mode with Ollama:** Running local LLMs requires significant hardware. Smaller models like `gpt-oss:20b` need ~16 GB RAM. Larger models like `gpt-oss:120b` need a GPU with 80 GB VRAM or equivalent shared memory (e.g., Apple Silicon with unified memory). See [Models and Privacy](11-models-and-privacy.md) for configuration details.

**Shared memory systems (Apple Silicon, etc.):** Macs with M-series chips share memory between CPU and GPU. A MacBook Pro with 64 GB unified memory can run models that would require a dedicated GPU on other systems. Ollama handles this automatically.

## Installation

### Clone and install

```bash
git clone https://github.com/xkiwilabs/Urika.git
cd Urika
pip install -e .
```

This installs everything you need for statistical analysis, machine learning, visualization, and knowledge ingestion:

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

### Check your installation

After installing, run `urika setup` to verify everything is working:

```bash
urika setup
```

This checks installed packages by category, detects your hardware (CPU cores, RAM, GPU), and verifies your `ANTHROPIC_API_KEY` is set. If deep learning packages are missing, it offers to install them with automatic GPU detection.

### Optional: deep learning

The only optional install group is `[dl]` for deep learning (~2 GB download):

```bash
pip install -e ".[dl]"           # + deep learning (torch, transformers, etc.)
pip install -e ".[all]"          # same as core + dl
```

| Group | Packages | What it adds |
|-------|----------|-------------|
| `[dl]` | torch, transformers, sentence-transformers, torchvision, torchaudio, timm | Neural networks, LLM fine-tuning, text embeddings, image/audio models |
| `[all]` | Core + dl | Everything in one install |

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

## Authentication

Urika's agents need access to Claude. Two options:

### Option 1: API key

Set your Anthropic API key as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add this to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) to persist it across sessions.

### Option 2: Claude Max/Pro account

If you have a Claude Max or Pro subscription, the Claude Agent SDK can authenticate through your account login. No API key needed — just ensure you're logged in via Claude Code.

## Two ways to use Urika

Urika has two interfaces that share the same commands and produce identical results:

- **Interactive REPL** — Run `urika` with no arguments. Gives you a prompt with tab completion, `/help`, conversation history, and a bottom status bar. Best for learning the system and exploratory work.
- **CLI commands** — Run `urika <command>` directly from your shell. Best for scripting, automation, and when you know exactly what you want to run.

If you're new to Urika, **start with the REPL** — you can discover all commands with tab completion and `/help`, and ask the advisor agent questions in plain text without needing to know any commands at all.

See [CLI Reference](14-cli-reference.md) and [Interactive REPL](15-interactive-repl.md) for full details on each interface.

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
