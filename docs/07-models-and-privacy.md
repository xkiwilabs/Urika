# Models and Privacy

Urika lets you configure which AI models and endpoints each agent uses, on a per-project basis. This gives you control over cost, performance, and data privacy.


## Models and Endpoints

Urika currently uses the **Claude Agent SDK** as its runtime backend. This supports:

- **Claude models** via the Anthropic API (Haiku, Sonnet, Opus)
- **Local models** via Ollama (Llama, Mistral, etc.)
- **Institutional endpoints** -- any Anthropic-compatible API server

Future releases will add adapters for OpenAI Agents SDK, Google ADK, and Pi coding agent.

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

Endpoints are named API targets defined in `[privacy.endpoints]`. Three patterns are common:

### Cloud (default)

The standard Anthropic API. No configuration needed -- this is the default when no endpoint is specified.

### Local (Ollama)

A local model server running on your machine. Full data privacy -- nothing leaves your network.

```toml
[privacy.endpoints.local]
base_url = "http://localhost:11434"
```

### Trusted (institutional server)

An Anthropic-compatible endpoint running on a university or organization server, with its own API key.

```toml
[privacy.endpoints.trusted]
base_url = "https://secure-ai.university.edu/v1"
api_key_env = "UNI_API_KEY"
```

The `api_key_env` field names an environment variable that contains the API key. Urika reads the key from that variable at runtime -- the key itself is never stored in `urika.toml`.


## Privacy Modes

The `[privacy]` section in `urika.toml` controls how agents are routed to endpoints. There are three modes.

### Cloud mode (default)

All agents use the cloud Anthropic API. No special configuration needed.

```toml
[privacy]
mode = "cloud"
```

This is the default behavior when no `[privacy]` section exists.

### Local mode

All agents use a local endpoint. Full data privacy, but model capability depends on what you can run locally.

```toml
[privacy]
mode = "local"

[privacy.endpoints.local]
base_url = "http://localhost:11434"
```

### Hybrid mode

The recommended mode for privacy-sensitive research. A local **Data Agent** reads raw data and outputs sanitized summaries. All other agents run on cloud models for maximum analytical power, but never see raw data.

```toml
[privacy]
mode = "hybrid"

[privacy.endpoints.local]
base_url = "http://localhost:11434"
```


## Hybrid Architecture

Hybrid mode is designed for research with sensitive data. The key insight: only one agent needs to read the raw data. Everything else can work from summaries.

### How it works

1. The **Data Agent** runs on the local (or trusted) endpoint. It reads raw data files, computes features, and outputs sanitized summaries -- aggregated statistics, feature names, distributions, and processed DataFrames. It never includes raw identifiable records in its text output.

2. The **orchestrator** passes the Data Agent's sanitized output to the cloud-based agents. The raw data never reaches the cloud.

3. All other agents (Planning, Task, Evaluator, Advisor, Tool Builder, Literature) run on cloud models. They receive only the sanitized summaries and work from those.

### Orchestrator flow

```
Data Agent (LOCAL) --> sanitized summary --> Task Agent (CLOUD) --> code + results
```

In the orchestrator loop, the Data Agent runs between the Planning Agent and the Task Agent. Its sanitized output is prepended to the task input:

```
Planning Agent (CLOUD)
       |
       v
Data Agent (LOCAL) -- reads raw data, outputs sanitized features/stats
       |
       v
Task Agent (CLOUD) -- receives sanitized summary + plan, writes code
       |
       v
Evaluator (CLOUD) -- scores results against criteria
       |
       v
Advisor Agent (CLOUD) -- proposes next steps
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

In hybrid mode, the following agents default to the local endpoint:

- **data_agent** -- reads and sanitizes raw data
- **tool_builder** -- creates project-specific tools (may need data access)

All other agents default to the cloud endpoint. These defaults can be overridden with per-agent endpoint assignments.


## Per-Agent Endpoint Assignment

Any agent can be assigned to any named endpoint, regardless of the privacy mode:

```toml
[runtime.models.data_agent]
endpoint = "trusted"
model = "claude-sonnet-4-6"

[runtime.models.task_agent]
endpoint = "cloud"
model = "claude-opus-4-6"

[runtime.models.evaluator]
endpoint = "cloud"
model = "claude-haiku-4-5"
```

This overrides the defaults set by the privacy mode. You can mix and match endpoints freely.


## Use Cases

### Clinical research

Patient data stays on a university server. The Data Agent runs on the trusted institutional endpoint, reads participant records, and outputs anonymized feature matrices. Cloud-based agents design and evaluate analytical methods without ever seeing identifiable data.

```toml
[privacy]
mode = "hybrid"

[privacy.endpoints.trusted]
base_url = "https://secure-ai.university.edu/v1"
api_key_env = "UNI_API_KEY"

[runtime.models.data_agent]
endpoint = "trusted"
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

### Fully local

Run everything on your own hardware with no cloud dependency:

```toml
[privacy]
mode = "local"

[privacy.endpoints.local]
base_url = "http://localhost:11434"

[runtime]
model = "llama3:70b"
```


## Setting Up Ollama for Local Models

1. **Install Ollama** from [ollama.com](https://ollama.com)

2. **Pull a model:**
   ```bash
   ollama pull llama3:70b
   ```

3. **Configure the endpoint** in your project's `urika.toml`:
   ```toml
   [privacy]
   mode = "local"

   [privacy.endpoints.local]
   base_url = "http://localhost:11434"

   [runtime]
   model = "llama3:70b"
   ```

4. **Run as normal:**
   ```bash
   urika run my-project
   ```

Larger models (70B+ parameters) are recommended for the Task Agent and Tool Builder, as these agents write code and need strong reasoning capability. Smaller models may work for the Evaluator or Planning Agent.


## Important Notes

- **Installation does not change.** Model and privacy configuration is entirely per-project, set in `urika.toml`.
- **Different projects can have different settings.** One project can run fully local while another uses cloud models.
- **Default behavior is unchanged.** If you do not add `[privacy]` or `[runtime]` sections to `urika.toml`, everything runs on the cloud Anthropic API as before.
- **Currently only Claude Agent SDK is supported.** OpenAI Agents SDK, Google ADK, and Pi coding agent adapters are planned for upcoming releases.
