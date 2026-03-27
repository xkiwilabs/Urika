# Models and Privacy

Urika lets you configure which AI models and endpoints each agent uses, on a per-project basis. This gives you control over cost, performance, and data privacy.

> **What needs to be private stays private.** You decide which agents access your data and where they run -- local models, secure institutional servers, or any combination. Different projects can have completely different privacy settings.


## Models and Endpoints

Urika currently uses the **Claude Agent SDK** as its runtime backend. This supports:

- **Claude models** via the Anthropic API (Haiku, Sonnet, Opus)
- **Local models** via Ollama (Llama, Mistral, etc.)
- **Institutional endpoints** -- any Anthropic-compatible API server (e.g., an organisation's secure Claude instance)

Future releases will add adapters for OpenAI Agents SDK, Google ADK, and PI.

### Per-project model configuration

Each project's `urika.toml` can include a `[runtime]` section to set the default model and per-agent overrides:

```toml
[runtime]
model = "claude-sonnet-4-5"

[runtime.models.task_agent]
model = "claude-opus-4-6"

[runtime.models.evaluator]
model = "claude-haiku-4-5"
```

- `[runtime] model` sets the default for all agents in the project.
- `[runtime.models.<agent_name>]` overrides the model for a specific agent.

If no `[runtime]` section is present, Urika uses the default Claude model.


## Named Endpoints

Endpoints are named API targets defined in `[privacy.endpoints]`. You can define as many as you need.

### Open (default)

The standard Anthropic API. No configuration needed -- this is the default when no endpoint is specified.

### Private (local models)

A local model server running on your machine. Nothing leaves your network.

```toml
[privacy.endpoints.private]
base_url = "http://localhost:11434"
```

### Private (institutional server)

A secure Anthropic-compatible endpoint running on a secure organisation, institution, or cloud server, with its own API key. This is also a "private" endpoint -- private means anything within your data governance boundary.

```toml
[privacy.endpoints.private]
base_url = "https://secure-ai.university.edu/v1"
api_key_env = "UNI_API_KEY"
```

The `api_key_env` field names an environment variable that contains the API key. Urika reads the key from that variable at runtime -- the key itself is never stored in `urika.toml`.

You can define multiple private endpoints with different names:

```toml
[privacy.endpoints.local]
base_url = "http://localhost:11434"

[privacy.endpoints.university]
base_url = "https://secure-ai.university.edu/v1"
api_key_env = "UNI_API_KEY"
```


## Privacy Modes

The `[privacy]` section in `urika.toml` controls how agents are routed to endpoints. There are three modes.

### Open mode (default)

All agents use the Anthropic API. No special configuration needed.

```toml
[privacy]
mode = "open"
```

This is the default behavior when no `[privacy]` section exists.

### Private mode

All agents use a private endpoint. This can be local models (Ollama on your machine), a secure institutional server, or any Anthropic-compatible endpoint within your data governance boundary.

```toml
[privacy]
mode = "private"

[privacy.endpoints.private]
base_url = "http://localhost:11434"
```

Or using an institutional server:

```toml
[privacy]
mode = "private"

[privacy.endpoints.private]
base_url = "https://secure-ai.university.edu/v1"
api_key_env = "UNI_API_KEY"
```

### Hybrid mode

The recommended mode for privacy-sensitive research. A private **Data Agent** reads raw data and outputs sanitized summaries. All other agents run on open cloud models for maximum analytical power, but never see raw data.

```toml
[privacy]
mode = "hybrid"

[privacy.endpoints.private]
base_url = "http://localhost:11434"
```

The default hybrid split covers most use cases, but you can customize which agents use which endpoints -- see Per-Agent Endpoint Assignment below.


## Hybrid Architecture

Hybrid mode is designed for research with sensitive data. The key insight: only one agent needs to read the raw data. Everything else can work from summaries.

### How it works

1. The **Data Agent** runs on the private endpoint. It reads raw data files, computes features, and outputs sanitized summaries -- aggregated statistics, feature names, distributions, and processed DataFrames. It never includes raw identifiable records in its text output.

2. The **orchestrator** passes the Data Agent's sanitized output to the open cloud agents. The raw data never reaches the cloud.

3. All other agents (Planning, Task, Evaluator, Advisor, Tool Builder, Literature) run on cloud models. They receive only the sanitized summaries and work from those.

### Orchestrator flow

```
Planning Agent (OPEN/CLOUD)
       |
       v
Data Agent (PRIVATE) -- reads raw data, outputs sanitized features/stats
       |
       v
Task Agent (OPEN/CLOUD) -- receives sanitized summary + plan, writes code
       |
       v
Evaluator (OPEN/CLOUD) -- scores results against criteria
       |
       v
Advisor Agent (OPEN/CLOUD) -- proposes next steps
```

### What the Data Agent outputs

The Data Agent produces structured summaries like:

```json
{
  "n_rows": 500,
  "n_columns": 12,
  "columns": ["feature1", "feature2", "..."],
  "summary_stats": {"feature1": {"mean": 0.5, "std": 0.2}},
  "sanitized_path": "experiments/<exp>/data/features.csv",
  "notes": "Description of what was extracted and any issues found"
}
```

This includes row/column counts, feature names, summary statistics, and paths to processed data files -- but never raw individual records.

### Default hybrid assignments

In hybrid mode, the following agents default to the private endpoint:

- **data_agent** -- reads and sanitizes raw data
- **tool_builder** -- creates project-specific tools (may need data access)

All other agents default to the open cloud endpoint. These defaults can be overridden with per-agent endpoint assignments to ensure what needs to be private stays private.


## Per-Agent Endpoint Assignment

Any agent can be assigned to any named endpoint, regardless of the privacy mode:

```toml
[runtime.models.data_agent]
endpoint = "university"
model = "claude-sonnet-4-6"

[runtime.models.task_agent]
endpoint = "open"
model = "claude-opus-4-6"

[runtime.models.evaluator]
endpoint = "open"
model = "claude-haiku-4-5"
```

This overrides the defaults set by the privacy mode. You can mix and match endpoints freely -- ensuring that what needs to be private stays private, while everything else gets the full power of frontier models.


## Use Cases

### Clinical research

Patient data stays on a secure institutional server. The Data Agent runs on the trusted institutional endpoint, reads participant records, and outputs anonymized feature matrices. Cloud-based agents design and evaluate analytical methods without ever seeing identifiable data.

```toml
[privacy]
mode = "hybrid"

[privacy.endpoints.private]
base_url = "https://secure-ai.university.edu/v1"
api_key_env = "UNI_API_KEY"

[runtime.models.data_agent]
endpoint = "private"
```

### GDPR compliance

European participant data stays on an EU-hosted endpoint. Cloud agents handle method design and evaluation.

### Cost optimization

Use cheaper models for straightforward tasks and expensive models for complex reasoning:

```toml
[runtime]
model = "claude-sonnet-4-5"

[runtime.models.task_agent]
model = "claude-opus-4-6"

[runtime.models.evaluator]
model = "claude-haiku-4-5"

[runtime.models.planning_agent]
model = "claude-haiku-4-5"
```

### Fully private

Run everything on your own hardware or institutional server with no external cloud dependency:

```toml
[privacy]
mode = "private"

[privacy.endpoints.private]
base_url = "http://localhost:11434"

[runtime]
model = "gpt-oss:120b"
```


## Setting Up Local Models

Urika supports local model servers that provide an Anthropic-compatible API. Two options work out of the box:

### Option 1: Ollama (recommended)

Requires Ollama v0.14 or later, which includes native Anthropic API compatibility.

1. **Install Ollama** from [ollama.com](https://ollama.com)

2. **Pull a model** with strong reasoning and code generation:
   ```bash
   ollama pull qwen3-coder        # 30B, needs 24GB+ VRAM
   ollama pull qwen3.5            # lighter alternative
   ollama pull glm-4.7-flash      # fast, good for simpler agents
   ```

3. **Configure the endpoint** in your project's `urika.toml`:
   ```toml
   [privacy]
   mode = "private"

   [privacy.endpoints.private]
   base_url = "http://localhost:11434"

   [runtime]
   model = "qwen3-coder"
   ```

4. **Run as normal:**
   ```bash
   urika run my-project
   ```

Models with strong reasoning and code generation capabilities are recommended for the Task Agent and Tool Builder. Smaller models may work for the Evaluator or Planning Agent — use per-agent overrides to mix model sizes:

```toml
[runtime]
model = "qwen3-coder"

[runtime.models.evaluator]
model = "glm-4.7-flash"

[runtime.models.planning_agent]
model = "glm-4.7-flash"
```

### Option 2: LM Studio

LM Studio 0.4.1+ provides an Anthropic-compatible endpoint on port 1234.

1. **Install LM Studio** from [lmstudio.ai](https://lmstudio.ai)
2. **Load a model** in LM Studio and start the local server
3. **Configure:**
   ```toml
   [privacy]
   mode = "private"

   [privacy.endpoints.private]
   base_url = "http://localhost:1234"

   [runtime]
   model = "your-loaded-model-name"
   ```

### Option 3: vLLM / LiteLLM Server (network)

For teams running shared GPU workstations, a vLLM or LiteLLM server provides a single OpenAI-compatible API endpoint that multiple users and projects can share. This is ideal for labs and institutions with dedicated hardware.

1. **Set up the server** on your workstation (see your server documentation, e.g. [inference-hub](https://github.com/xkiwilabs/inference-hub))

2. **Set the API key** on your local machine:
   ```bash
   export VLLM_API_KEY="your-api-key"
   ```
   Add to your shell profile (`~/.bashrc`, `~/.zshrc`) to persist.

3. **Configure via interactive setup:**
   ```bash
   urika config my-project
   # Pick: private (or hybrid)
   # Pick: vLLM / LiteLLM server (network)
   # Enter: http://192.168.1.100:4200/v1
   # API key env var: VLLM_API_KEY
   # Model: small (or large)
   ```

4. **Or configure manually** in `urika.toml`:
   ```toml
   [privacy]
   mode = "private"

   [privacy.endpoints.private]
   base_url = "http://192.168.1.100:4200"
   api_key_env = "INFERENCE_HUB_KEY"

   [runtime]
   model = "small"
   ```

#### Multiple workstations

You can define separate endpoints for different servers and route agents to specific machines:

```toml
[privacy]
mode = "private"

[privacy.endpoints.workstation1]
base_url = "http://192.168.1.100:4200"
api_key_env = "INFERENCE_HUB_KEY"

[privacy.endpoints.workstation2]
base_url = "http://192.168.1.101:4200/v1"
api_key_env = "INFERENCE_HUB_KEY"

[runtime]
model = "small"

[runtime.models.task_agent]
model = "large"
endpoint = "workstation1"

[runtime.models.planning_agent]
model = "small"
endpoint = "workstation2"
```

This is particularly useful when you have workstations with different GPU configurations — route compute-heavy agents (task agent, finalizer) to the machine with more VRAM, and lighter agents (evaluator, planning) to smaller machines.

### Option 4: LiteLLM Proxy (advanced)

For maximum flexibility — mix local and cloud models, add load balancing, or use providers without native Anthropic compatibility:

1. **Install:** `pip install 'litellm[proxy]'`
2. **Create `litellm-config.yaml`:**
   ```yaml
   model_list:
     - model_name: "local-coder"
       litellm_params:
         model: "ollama_chat/qwen3-coder"
         api_base: "http://localhost:11434"
   ```
3. **Start proxy:** `litellm --config litellm-config.yaml --port 4000`
4. **Configure:**
   ```toml
   [privacy.endpoints.private]
   base_url = "http://localhost:4000"
   api_key_env = "LITELLM_KEY"
   ```

### Tested models

Not all local models work with Urika. The model must support **tool/function calling** via Ollama's Anthropic-compatible API. Tested results:

| Model | Size | Tools | Urika | Notes |
|-------|------|-------|-------|-------|
| `qwen3:14b` | 9 GB | Yes | **Recommended** | Best local option. Full pipeline with reports. |
| `qwen3:8b` | 5 GB | Yes | Works | Lighter, may not format structured output perfectly. |
| `qwen3-coder` | 18 GB | Yes | Good | Strong code generation. Needs 24GB+ VRAM. |
| `devstral` | 15 GB | Yes | Partial | Has tools but may not follow prompt structure. |
| `gemma3:12b` | 8 GB | No | Fails | Ollama reports "does not support tools". |
| `llama3:8b` | 5 GB | No | Fails | Ollama reports "does not support tools". |

**Recommendation:** Use `qwen3:14b` for the best balance of quality and speed. Use `qwen3:8b` if VRAM is limited. Larger Qwen3 variants (30B+) will produce better results if your hardware supports them.

### Requirements for local models

- **Claude Code CLI must be installed** (system-wide, not just the SDK). Install via: `npm install -g @anthropic-ai/claude-code`
- **Context window**: 64K tokens minimum recommended. Agents use substantial context for reading files and tracking experiments.
- **Tool/function calling**: The model must support tool use via Ollama. Check the table above — not all models work.
- **Quality varies**: Local models produce lower-quality analysis than Claude. Results will differ from cloud mode. For best local results, use the largest model your hardware supports.


## Important Notes

- **Installation does not change.** Model and privacy configuration is entirely per-project, set in `urika.toml`.
- **Different projects can have different settings.** One project can run fully private while another uses open cloud models.
- **Default behavior is unchanged.** If you do not add `[privacy]` or `[runtime]` sections to `urika.toml`, everything runs on the Anthropic API as before.
- **What needs to be private stays private.** You control exactly which agents access which endpoints. The hybrid default covers most cases, but full customization is available.
- **Claude Code CLI required for local models.** The Claude Agent SDK spawns the `claude` CLI as a subprocess. For local model support, the system-installed CLI is used (not the bundled one). Install via `npm install -g @anthropic-ai/claude-code`.
- **Currently only Claude Agent SDK is supported.** OpenAI Agents SDK, Google ADK, and PI adapters are planned for upcoming releases.

### Data privacy disclaimer

Hybrid mode is designed to minimize the risk of sensitive data reaching cloud endpoints. The Data Agent sanitizes its output to include only aggregated statistics, feature names, and summaries — not raw individual records. However, **there is always some risk of unintended data leakage in hybrid mode**. For example, an unusual feature name, a rare category value in a summary statistic, or a highly specific data description could indirectly reveal information about the underlying data.

If you are working with highly sensitive data (patient records, classified information, personally identifiable data) or where data privacy or intellectual property protection is a strict requirement, **use private mode for a complete guarantee**. Private mode ensures that no data — raw or summarised — ever reaches an external endpoint.

Urika is provided "as is" without warranty. The authors do not guarantee that hybrid mode will prevent all forms of data leakage. Users are responsible for evaluating whether hybrid mode meets their organisation's data governance requirements.

---

**Next:** [Configuration](13-configuration.md)
