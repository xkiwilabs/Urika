# Local Models

Setting up local model servers (Ollama, LM Studio, vLLM, LiteLLM proxy), the tested-models table, and requirements. See [Models and Privacy](13a-models-and-privacy.md) for the privacy modes, hybrid architecture, and per-agent endpoint assignment that decide which agents use these endpoints.

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
- **One agent backend ships in v0.4** — the Anthropic Claude Agent SDK. Additional backends can be added via the `urika.runners` Python entry-point group; see [Contributing an Adapter](contributing-an-adapter.md).

---

**Next:** [Configuration](14a-project-config.md)


## See also

- [Models and Privacy](13a-models-and-privacy.md)
- [Configuration](14a-project-config.md)
- [Security Model](20-security.md)
- [Contributing an Adapter](contributing-an-adapter.md)
