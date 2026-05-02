# Models and Privacy

Privacy modes, hybrid architecture, per-agent endpoint assignment, and the data-privacy disclaimer. See [Local Models](13b-local-models.md) for setting up Ollama, LM Studio, vLLM/LiteLLM, and the tested-models table.

Urika lets you configure which AI models and endpoints each agent uses, on a per-project basis. This gives you control over cost, performance, and data privacy.

> **What needs to be private stays private.** You decide which agents access your data and where they run -- local models, secure institutional servers, or any combination. Different projects can have completely different privacy settings.


## Models and Endpoints

Urika currently uses the **Claude Agent SDK** as its runtime backend. This supports:

- **Claude models** via the Anthropic API (Haiku, Sonnet, Opus)
- **Local models** via Ollama (Llama, Mistral, etc.)
- **Institutional endpoints** -- any Anthropic-compatible API server (e.g., an organisation's secure Claude instance)

Additional backends can be plugged in through the `urika.runners` Python entry-point group — see [Contributing an Adapter](contributing-an-adapter.md).

> **Important: Urika requires an Anthropic API key for cloud (open) use.**
>
> Anthropic's [Consumer Terms (§3.7)](https://www.anthropic.com/legal/consumer-terms)
> and the April 2026 Agent SDK clarification prohibit using a Claude
> Pro/Max subscription to authenticate the Claude Agent SDK that Urika
> depends on. Set `ANTHROPIC_API_KEY` (e.g. via `urika config api-key`)
> for any mode that talks to Anthropic's API. Only **private mode**
> (local models or an institutional endpoint) can run without an API
> key. See [Provider compliance](20-security.md#provider-compliance) for
> the full rationale.

**Per-mode requirements at a glance:**

| Mode | Needs `ANTHROPIC_API_KEY`? |
|---|---|
| Open (default — all agents on Claude API) | Yes |
| Hybrid (cloud agents + private data agent) | Yes (cloud-side agents call the Claude API) |
| Private (all agents local / institutional) | No (provided no agent uses the `open` endpoint) |

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

### Recommended defaults — reasoning vs execution split

When you run `urika config` and pick **Opus** as your default cloud model, the wizard auto-applies a per-agent split:

- **Reasoning agents** (`planning_agent`, `advisor_agent`, `finalizer`, `project_builder`) — kept on the Opus model you selected. These are the agents whose decision quality directly shapes what the experiment becomes.
- **Execution agents** (`task_agent`, `evaluator`, `report_agent`, `presentation_agent`, `tool_builder`, `literature_agent`, `data_agent`, `project_summarizer`) — automatically pinned to `claude-sonnet-4-5`. These execute already-decided plans, format already-decided findings, or apply rules to metrics. Sonnet performs indistinguishably from Opus on these tasks and saves roughly 5× per call.

Net effect: reasoning quality is unchanged, execution cost drops ~50–65% per experiment. To opt out and put every agent on the same model, edit `~/.urika/settings.toml` directly or override individual agents in the dashboard's Settings → Models tab. Picking **Sonnet** as the default skips the split entirely (everything's already at the cheaper tier).

#### Re-applying the split to existing projects

Projects created before v0.4.0 — or any project whose per-agent assignments have drifted — can be reset to the recommended split without going through the full wizard:

```bash
urika config <project> --reset-models     # rebuild that project's urika.toml
urika config --reset-models               # rebuild every configured mode in ~/.urika/settings.toml
```

The dashboard's Models tab also has a **Reset to recommended defaults** button at the top, both globally (`/settings`) and per-project (`/projects/<n>/settings`). The reset is idempotent — running it twice is a no-op the second time. Hybrid projects keep their data-agent + tool-builder private-endpoint pin across the rebuild.


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


### Data privacy disclaimer

Hybrid mode is designed to minimize the risk of sensitive data reaching cloud endpoints. The Data Agent sanitizes its output to include only aggregated statistics, feature names, and summaries — not raw individual records. However, **there is always some risk of unintended data leakage in hybrid mode**. For example, an unusual feature name, a rare category value in a summary statistic, or a highly specific data description could indirectly reveal information about the underlying data.

If you are working with highly sensitive data (patient records, classified information, personally identifiable data) or where data privacy or intellectual property protection is a strict requirement, **use private mode for a complete guarantee**. Private mode ensures that no data — raw or summarised — ever reaches an external endpoint.

Urika is provided "as is" without warranty. The authors do not guarantee that hybrid mode will prevent all forms of data leakage. Users are responsible for evaluating whether hybrid mode meets their organisation's data governance requirements.


## See also

- [Local Models](13b-local-models.md)
- [Configuration](14a-project-config.md)
- [Security Model](20-security.md)
- [Contributing an Adapter](contributing-an-adapter.md)
