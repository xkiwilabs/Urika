# Urika Option C: Custom Python+TypeScript Agent Runtime — PRD & Implementation Plan

## 1. Overview

### What This Is

Urika built on its own agent runtime: a Python platform where we write the agent loop, the LLM provider abstraction, the core tools (read, write, edit, bash), and the session management ourselves. No Claude Agent SDK. No Pi. No LangGraph. We own the entire stack from prompt construction to tool dispatch to context window management.

### Honest Framing: What You Are Building

The previous version of this document overstated the difference between "coding agents" and "analysis agents." That framing was wrong. Here is the corrected picture:

**Urika's agents ARE primarily writing and running code.** A task agent exploring a dataset writes a Python script that imports pandas, loads the CSV, computes descriptive statistics, generates a matplotlib plot, and writes a JSON summary. It runs that script via bash. It reads the output. It decides what to try next. This is exactly what a coding agent does.

The idea of "analysis-native tools" that return typed `MethodResult` objects and bypass code generation was overengineered. The LLM calling `statistical_test(test="welch_t", group_col="condition", value_col="rt")` instead of writing a Python script sounds elegant, but:

- It forces you to anticipate every analysis operation in advance and build a typed tool for it
- It removes the agent's ability to do anything you didn't pre-build a tool for
- It adds a rigid abstraction layer between the agent and the actual computation
- Real scientific analysis involves constant improvisation — custom transformations, ad-hoc data cleaning, exploratory plots the tool system never anticipated

The correct model: agents write Python scripts that `import urika` (a pip-installable library providing data loading, evaluation, metrics, leaderboard, built-in methods) and run them via bash. The runtime needs to let agents write and run Python code effectively — which means it needs the same core tools a coding agent needs: file read, file write, file edit, bash execution, and search.

### What a Custom Runtime Must Implement

These are capabilities you would get for free from Option A (Claude Agent SDK) or Option B (Pi), or any existing agent framework:

| Component | What It Does | Estimated Effort |
|-----------|-------------|-----------------|
| **Agent loop** | prompt -> LLM response -> tool call parsing -> tool dispatch -> append results -> repeat | ~500-800 lines |
| **LLM abstraction** | Provider registry supporting Claude, GPT-4, Gemini, open-source models. Message format translation per provider. | ~400-600 lines + ~150 per provider |
| **Core tools** | `read_file`, `write_file`, `edit_file`, `bash` (command execution), `glob`, `grep` — the same tools a coding agent needs | ~300-500 lines |
| **Session management** | Conversation history persistence, resume/continue, context window tracking | ~300-400 lines |
| **Context window management** | Token counting, history compaction/summarization when approaching the limit | ~200-400 lines |
| **Streaming** | Handle streaming LLM responses for interactive display | ~200-300 lines |
| **Retry logic** | API error handling, rate limit backoff, transient failure recovery | ~100-200 lines |
| **Message formatting** | Each LLM provider has different message formats, tool-use protocols, system prompt handling | Baked into provider implementations |

**Total runtime estimate: ~2,500-4,000 lines of Python** before you write a single line of Urika-specific logic.

### What Urika Adds ON TOP of the Runtime

This work is identical regardless of whether you build your own runtime (Option C), use the Claude Agent SDK (Option A), or use Pi (Option B):

| Component | What It Does |
|-----------|-------------|
| **Multi-agent orchestration** | Sequencing: orchestrator -> task agent -> evaluator -> suggestion agent -> tool builder |
| **Security boundaries** | Evaluator cannot write to `methods/`, task agents cannot modify evaluation criteria |
| **Investigation framework** | Python evaluation, metrics, leaderboard, criteria validation system |
| **Knowledge pipeline** | PDF extraction, literature search, knowledge indexing |
| **Experiment tracking** | Runs, metrics, hypotheses, method comparisons, sessions |
| **Python analysis library** | `pip install urika` — data loading, built-in methods, evaluation runner, metrics, leaderboard |

### Why Build Your Own Runtime (the honest case)

1. **Model flexibility.** Option A is Python/Claude-native. Option B (Pi) is TypeScript and speaks Claude natively. Supporting GPT-4, Gemini, or local models through either means working within their provider systems. A custom runtime with a provider registry treats all models as interchangeable from day one.

2. **Full control over the agent loop.** When an agent loop hangs, produces garbage, or burns tokens, you need to inspect every layer — prompt construction, LLM call, response parsing, tool dispatch, result formatting. With your own runtime, every layer is your Python code you can breakpoint.

3. **Python-native stack.** Option B (Pi) is TypeScript. Option A (Claude Agent SDK) is Python but tightly coupled to Claude. A custom Python runtime means one language for the whole stack — runtime, tools, analysis library, agent-written scripts — with no vendor lock-in.

4. **No upstream dependency.** Both the Claude Agent SDK and Pi are third-party projects. If either changes direction, deprecates an API, or stops being maintained, you are exposed. A custom runtime has no upstream.

### What You Give Up

1. **Months of work.** The agent loop, LLM providers, core tools, session management, streaming, retries — this is real engineering that both the Claude Agent SDK and Pi have already done and tested.
2. **Battle-tested tool implementations.** Pi's `read`, `write`, `edit`, `bash`, `grep` tools have been used by thousands of developers. The Claude Agent SDK benefits from Anthropic's tool-use expertise. Your v1 implementations will have bugs these projects have already fixed.
3. **Ongoing maintenance.** When Claude adds a new API feature, or OpenAI changes their tool-use format, you maintain the provider adapters.
4. **Slower time-to-Urika.** Instead of starting with "agents that can read files and run code" on day one (Option A or B), you start with "build a system that lets agents read files and run code" and then build Urika on top of that.

---

## 2. Architecture

### 2.1 System Architecture

```
                           +------------------------------+
                           |        Urika CLI             |
                           |   (Python: click)            |
                           +-------------+----------------+
                                         |
                           +-------------v----------------+
                           |       Orchestrator           |
                           |  (deterministic Python loop) |
                           +-------------+----------------+
                                         | spawns
                   +------------+--------+-------+-------------+
                   v            v                v              v
             +-----------+ +-----------+ +-----------+ +-----------+
             |Task Agent | |Evaluator  | |Suggestion | |Tool       |
             |           | |(read-only)| |Agent      | |Builder    |
             +-----------+ +-----------+ +-----------+ +-----------+
                   |            |              |              |
             +-----v------------v--------------v--------------v----+
             |                    Agent Loop                        |
             |       (prompt -> LLM -> parse -> dispatch)          |
             +-----+------------------------------------------+---+
                   |                                           |
             +-----v--------------+                 +----------v--------+
             | LLM Providers      |                 | Tool Registry     |
             |                    |                 | (per-agent)       |
             | - Anthropic        |                 |                   |
             | - OpenAI           |                 | - read_file       |
             | - LiteLLM (*)     |                 | - write_file      |
             |                    |                 | - edit_file       |
             |                    |                 | - bash            |
             |                    |                 | - glob / grep     |
             +--------------------+                 | - (custom...)     |
                                                    +-------------------+
                        |                                    |
             +----------v------------------------------------v---------+
             |                  Filesystem Layer                        |
             |   sessions/ results/ methods/ knowledge/ tools/         |
             |               (JSON communication)                      |
             +--------------------------------------------------------+
```

### 2.2 The Agent Loop

The agent loop is the core of the custom runtime. It is a straightforward cycle: assemble messages, call the LLM, parse the response, dispatch any tool calls, append results, repeat.

```python
# urika/runtime/loop.py

class AgentLoop:
    """The core prompt -> LLM -> tool-dispatch cycle."""

    def __init__(
        self,
        agent_config: AgentConfig,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        session: Session,
    ):
        self.config = agent_config
        self.llm = llm
        self.tools = tool_registry
        self.session = session
        self.messages: list[Message] = []
        self.turn_count = 0

    async def run(self, initial_prompt: str) -> AgentResult:
        """Run the agent loop until completion or turn limit."""
        self.messages = [
            Message(role="system", content=self.config.system_prompt),
            Message(role="user", content=initial_prompt),
        ]

        while self.turn_count < self.config.max_turns:
            self.turn_count += 1

            # Context window management: compact if approaching limit
            self._maybe_compact_history()

            # 1. Call the LLM
            response = await self.llm.complete(
                messages=self.messages,
                tools=self.tools.schemas(),
                temperature=self.config.temperature,
            )

            # 2. Parse the response
            parsed = self.llm.parse_response(response)

            # 3. If no tool calls, the agent is done
            if not parsed.tool_calls:
                self.messages.append(
                    Message(role="assistant", content=parsed.text)
                )
                return AgentResult(
                    status="completed",
                    final_message=parsed.text,
                    turns=self.turn_count,
                    session=self.session,
                )

            # 4. Dispatch tool calls
            self.messages.append(Message(
                role="assistant",
                content=parsed.text,
                tool_calls=parsed.tool_calls,
            ))

            tool_results = []
            for call in parsed.tool_calls:
                result = await self._dispatch_tool(call)
                tool_results.append(result)

            self.messages.append(
                Message(role="tool", tool_results=tool_results)
            )

            # 5. Persist conversation state
            self.session.save_messages(self.messages)

            # 6. Check early termination
            if self._should_stop(tool_results):
                return AgentResult(
                    status="stopped",
                    reason=self._stop_reason(tool_results),
                    turns=self.turn_count,
                    session=self.session,
                )

        return AgentResult(
            status="turn_limit",
            turns=self.turn_count,
            session=self.session,
        )

    async def _dispatch_tool(self, call: ToolCall) -> ToolResult:
        """Execute a single tool call with security checks."""
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call_id=call.id, error=f"Unknown tool: {call.name}")

        try:
            validated = tool.validate_input(call.arguments)
            output = await asyncio.wait_for(
                tool.execute(validated, context=self._tool_context()),
                timeout=self.config.tool_timeout,
            )
            self.session.log_tool_call(call, output)
            return ToolResult(call_id=call.id, output=output)

        except asyncio.TimeoutError:
            return ToolResult(
                call_id=call.id,
                error=f"Tool timed out after {self.config.tool_timeout}s",
            )
        except Exception as e:
            return ToolResult(
                call_id=call.id,
                error=f"Tool error: {type(e).__name__}: {e}",
            )

    def _maybe_compact_history(self):
        """If message history is approaching context window, summarize old turns."""
        token_count = self.llm.token_count(self.messages)
        threshold = int(self.llm.context_window * 0.8)
        if token_count > threshold:
            # Keep system prompt and last N turns, summarize the rest
            system = self.messages[0]
            recent = self.messages[-self.config.compact_keep_recent:]
            old = self.messages[1:-self.config.compact_keep_recent]
            summary = self._summarize_messages(old)
            self.messages = [system, summary] + recent
```

**Key design decisions:**

- **Flat message list.** No implicit state. If we need to summarize or truncate, it is an explicit operation on this list.
- **No streaming in the loop.** The loop calls `complete()` and gets a full response. Streaming is layered on top for display purposes. This simplifies testing, retries, and tool dispatch.
- **Serial tool dispatch.** Parallel dispatch is an optimization for later. Serial dispatch is easier to debug.
- **Retries live in the LLM provider layer.** The loop sees a response or a raised exception. It does not implement retry logic.
- **Context window compaction is explicit.** When approaching the limit, old turns are summarized and replaced. The agent sees a summary of prior work rather than losing context silently.

### 2.3 LLM Provider Abstraction

```python
# urika/runtime/llm/base.py

class LLMProvider(ABC):
    """Interface each LLM provider implements."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> RawResponse: ...

    @abstractmethod
    def parse_response(self, response: RawResponse) -> ParsedResponse: ...

    @abstractmethod
    def format_tools(self, tools: list[ToolSchema]) -> Any: ...

    @abstractmethod
    def token_count(self, messages: list[Message]) -> int: ...

    @property
    @abstractmethod
    def context_window(self) -> int: ...

    @property
    @abstractmethod
    def supports_tool_use(self) -> bool: ...
```

**Provider registry:**

```python
# urika/runtime/llm/registry.py

class ProviderRegistry:
    _providers: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[LLMProvider]):
        cls._providers[name] = provider_class

    @classmethod
    def get(cls, provider: str, model: str, **kwargs) -> LLMProvider:
        if provider not in cls._providers:
            raise ProviderNotFoundError(f"Unknown provider: {provider}")
        return cls._providers[provider](model=model, **kwargs)

    @classmethod
    def from_config(cls, config: LLMConfig) -> LLMProvider:
        return cls.get(
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            **config.extra,
        )
```

**Three provider implementations:**

1. **AnthropicProvider** — Direct Claude API calls via `anthropic.AsyncAnthropic`. Handles Claude's system message format (separate `system` param), content block parsing (`text` + `tool_use`), tool result formatting.

2. **OpenAICompatProvider** — Covers OpenAI, Azure OpenAI, and any OpenAI-compatible API (vLLM, Ollama, Together, Groq). Uses `openai.AsyncOpenAI` with configurable `base_url`. Handles OpenAI's function-calling format.

3. **LiteLLMProvider** — Fallback for everything else (Gemini, Mistral, Cohere, Bedrock, etc.). Optional dependency. Uses litellm's unified interface. Covers any model litellm adds support for without us writing a provider.

**Provider registration:**

```python
# urika/runtime/llm/__init__.py

ProviderRegistry.register("anthropic", AnthropicProvider)
ProviderRegistry.register("openai", OpenAICompatProvider)
ProviderRegistry.register("azure", OpenAICompatProvider)

try:
    from .providers.litellm_provider import LiteLLMProvider
    ProviderRegistry.register("litellm", LiteLLMProvider)
except ImportError:
    pass
```

**Tool-use shim for models without native tool support:**

```python
class ToolUseShimProvider(LLMProvider):
    """Wraps any provider to add tool-use via prompt engineering.

    Injects tool schemas into the system prompt as structured text,
    parses tool calls from the model's text output.
    Used for open-source models that don't support native tool use.
    """

    def __init__(self, inner: LLMProvider):
        self.inner = inner
```

**Configuration in `urika.toml`:**

```toml
[llm]
default_provider = "anthropic"
default_model = "claude-sonnet-4-20250514"

[llm.agents.task_agent]
model = "claude-sonnet-4-20250514"

[llm.agents.suggestion_agent]
model = "claude-opus-4-20250514"   # deep strategic reasoning
```

### 2.4 Core Tool System

This is where the corrected framing matters. The core tools are the SAME tools a coding agent needs. Agents write Python scripts and run them via bash. The tools are:

| Tool | What It Does | Why Agents Need It |
|------|-------------|-------------------|
| `read_file` | Read file contents by path | Read data files, read previous results, read agent-written scripts |
| `write_file` | Write content to a file path | Write Python scripts, write JSON results, write method implementations |
| `edit_file` | Apply targeted edits to existing files | Modify scripts, update configs, fix code |
| `bash` | Execute a shell command | Run Python scripts, run pip install, execute analysis code |
| `glob` | Find files matching a pattern | Discover data files, find results, locate methods |
| `grep` | Search file contents | Search for patterns in code, find specific results |

```python
# urika/runtime/tools/base.py

@dataclass
class ToolSchema:
    """Tool definition exposed to the LLM."""
    name: str
    description: str
    parameters: dict       # JSON Schema
    safety: str            # "read_only" or "write"

class Tool(ABC):
    @abstractmethod
    def schema(self) -> ToolSchema: ...

    @abstractmethod
    async def execute(self, params: dict, context: ToolContext) -> str: ...

    def validate_input(self, params: dict) -> dict:
        jsonschema.validate(params, self.schema().parameters)
        return params
```

**Note on tool output:** Tools return strings, not typed objects. The agent reads the string output and decides what to do. This is the same model as every coding agent — `bash` returns stdout/stderr as a string, `read_file` returns file contents as a string. The LLM is perfectly capable of parsing structured output from strings.

**Security model — per-agent tool registries:**

Each agent gets a `ToolRegistry` containing only the tools it is allowed to use. The evaluator agent's registry does not contain `write_file` or `edit_file`. The tool simply does not exist from the evaluator's perspective — there is no hook intercepting a write attempt after the LLM already decided to write. The LLM never sees the tool in its tool definitions, so it never tries to call it.

```python
# Security via registry construction, not runtime interception

def build_task_agent_tools(investigation_root: Path, session_id: str) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool(
        allowed_dirs=[
            investigation_root / "methods",
            investigation_root / "results" / "sessions" / session_id,
        ]
    ))
    registry.register(EditFileTool(
        allowed_dirs=[
            investigation_root / "methods",
            investigation_root / "results" / "sessions" / session_id,
        ]
    ))
    registry.register(BashTool(
        allowed_commands=["python", "pip", "ls", "cat", "head"],
        blocked_patterns=["rm -rf", "sudo", "curl | bash"],
    ))
    registry.register(GlobTool())
    registry.register(GrepTool())
    return registry

def build_evaluator_tools(investigation_root: Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())     # read-only: no write, no edit
    registry.register(BashTool(
        allowed_commands=["python"],       # can run evaluation scripts only
        blocked_patterns=["rm", "mv", "cp", "write", ">>"],
    ))
    registry.register(GlobTool())
    registry.register(GrepTool())
    return registry
```

Additional write-path validation within `WriteFileTool` and `EditFileTool` enforces directory boundaries — even if a tool is in the registry, it checks that the target path is within `allowed_dirs`.

### 2.5 Session Management

```python
# urika/runtime/session.py

class Session:
    """Manages conversation state for a single agent run."""

    def __init__(self, session_dir: Path, agent_name: str):
        self.session_dir = session_dir
        self.agent_name = agent_name
        self.messages_file = session_dir / f"{agent_name}_messages.jsonl"
        self.tool_log_file = session_dir / f"{agent_name}_tool_log.jsonl"

    def save_messages(self, messages: list[Message]):
        """Persist current message history for resume."""
        # Write as JSONL — append-friendly, human-readable
        ...

    def load_messages(self) -> list[Message] | None:
        """Load previous messages for session resume."""
        ...

    def log_tool_call(self, call: ToolCall, output: str):
        """Append tool invocation to the audit log."""
        ...
```

**Context window management strategy:**

1. Track token count after each turn via `llm.token_count(messages)`
2. When count exceeds 80% of `llm.context_window`, trigger compaction
3. Compaction: keep system prompt + last N turns, summarize everything in between into a single message
4. Summary generation uses the same LLM (or a cheaper model) with a "summarize the work so far" prompt
5. Original messages are preserved in the JSONL log for debugging; only the in-memory list is compacted

### 2.6 Streaming

Streaming is layered on top of the agent loop, not baked into it. The loop calls `complete()` and gets a full response. For interactive use (CLI/TUI), a streaming wrapper yields tokens as they arrive:

```python
# urika/runtime/streaming.py

class StreamingAgentLoop(AgentLoop):
    """Extends AgentLoop with streaming display for interactive use."""

    async def run(self, initial_prompt: str) -> AgentResult:
        # Same loop, but uses llm.stream() instead of llm.complete()
        # Yields tokens to a display callback as they arrive
        # Collects the full response before tool dispatch
        ...
```

This separation means the core loop is testable without streaming, and streaming is a display concern only.

---

## 3. What You Build vs What Option A or Option B Would Give You

This is the honest accounting of the extra work in Option C vs Options A and B.

### Work You Must Do in Option C That the Claude Agent SDK or Pi Give You for Free

| Component | Lines (est.) | Complexity | Existing Solutions |
|-----------|-------------|-----------|-------------|
| Agent loop (prompt -> LLM -> tools -> repeat) | 500-800 | Medium — straightforward cycle but edge cases accumulate (malformed responses, partial tool calls, context overflow) | Battle-tested in both Claude Agent SDK and Pi, used by thousands of developers daily |
| LLM provider abstraction + registry | 400-600 | Medium — each provider has different message formats, tool protocols, error types | Claude Agent SDK: Claude-native. Pi: 15+ providers, maintained upstream |
| Anthropic provider adapter | 150-200 | Low-medium — Claude API is well-documented | Native in both Option A and Option B |
| OpenAI provider adapter | 150-200 | Low-medium — OpenAI API is well-documented | Native in Pi; available via community extensions for Claude Agent SDK |
| LiteLLM integration | 100-150 | Low — litellm does the heavy lifting | Covered by Pi's provider system; not needed in Claude Agent SDK (Claude-only) |
| Tool-use shim for non-native models | 200-300 | High — prompt engineering + parsing is fragile | Not needed in Pi (handles this); not applicable to Claude Agent SDK |
| Core tools: read_file, write_file, edit_file | 300-500 | Medium — edit_file in particular has tricky semantics (fuzzy matching, conflict resolution) | Mature implementations in both frameworks |
| Core tools: bash execution | 100-200 | Medium — process management, timeout, output capture, security | Mature implementations in both frameworks |
| Core tools: glob, grep | 100-150 | Low | Mature implementations in both frameworks |
| Session persistence (JSONL) | 200-300 | Low | Built-in in both frameworks |
| Context window management / compaction | 200-400 | High — summarization quality determines agent effectiveness in long sessions | Built-in in both frameworks |
| Token counting per provider | 100-200 | Low-medium — different tokenizers per provider | Built-in in both frameworks |
| Streaming response handling | 200-300 | Medium — must handle partial JSON in tool calls | Built-in in both frameworks |
| Retry logic / rate limit backoff | 100-200 | Low | Built-in in both frameworks |
| Message format translation | Baked into providers | Medium — ongoing maintenance as APIs change | Handled upstream in both frameworks |
| **Total** | **~2,800-4,500** | | |

### Work That Is Identical in All Three Options

| Component | Lines (est.) | Notes |
|-----------|-------------|-------|
| Multi-agent orchestrator | 400-600 | Deterministic Python loop that sequences agents |
| Agent prompt engineering | ~2,000 (prose) | System prompts for each agent role |
| Security boundary configuration | 200-300 | Per-agent tool registries and write boundaries |
| Python analysis library (`urika` package) | 3,000-5,000 | Data loading, methods, evaluation, metrics, leaderboard, knowledge |
| Built-in analysis methods | 1,500-3,000 | Linear regression, random forest, t-tests, mixed models, etc. |
| Evaluation framework | 500-800 | Metric registry, criteria validation, leaderboard |
| Knowledge pipeline | 500-800 | PDF extraction, literature search, indexing |
| Session/experiment tracking | 400-600 | Runs, metrics, hypotheses, progress tracking |
| CLI (`urika init`, `urika run`, etc.) | 300-500 | Click subcommands |
| Investigation config system | 300-400 | TOML config, success criteria, agent config |
| Tests | 2,000-3,000 | Unit + integration tests |
| **Total** | **~11,100-17,000** | |

### The Ratio

The runtime (Option C extra work) is roughly **2,800-4,500 lines**.
The Urika-specific platform (identical in all three options) is roughly **11,000-17,000 lines**.

**The runtime is ~20% of the total work. The analysis platform is ~80%.**

The choice between Option A, Option B, and Option C is about whether you also build that 20% yourself. It is NOT a fundamentally different architecture for Urika.

---

## 4. The Python Analysis Framework

This section describes the `urika` Python package that agents import when writing analysis scripts. **This is identical in Option A, Option B, and Option C.** It is the actual product — the thing that makes Urika useful for scientific analysis rather than being a generic coding agent pointed at data.

### 4.1 Package Overview

```
pip install urika
```

Agents write Python scripts like:

```python
#!/usr/bin/env python3
"""Explore the dataset and run initial statistical tests."""

from urika.data import load_dataset, profile
from urika.methods import LinearRegression, MixedANOVA
from urika.evaluation import evaluate, check_criteria
from urika.metrics import rmse, r_squared, cohens_d
from urika.leaderboard import update_leaderboard
from urika.sessions import current_session, log_run

# Load and profile
ds = load_dataset("data/experiment.csv")
summary = profile(ds)
print(summary)

# Run a method
model = LinearRegression()
result = model.fit(ds, target="accuracy", predictors=["age", "condition", "practice_hours"])
print(result.summary())
result.save_artifacts("results/sessions/session_001/runs/run_001/")

# Evaluate
metrics = evaluate(result, ds, metrics=[rmse, r_squared])
passed, failures = check_criteria(metrics, "config/success_criteria.json")

# Update tracking
log_run(
    session_id="session_001",
    run_id="run_001",
    method="linear_regression",
    params=model.get_params(),
    metrics=metrics,
    hypothesis="Baseline linear model to establish floor",
    observation=f"R2={metrics['r_squared']:.3f}, significant nonlinearity in residuals",
    next_step="Try tree-based methods for nonlinear relationships",
)
update_leaderboard(method="linear_regression", metrics=metrics, run_id="run_001")
```

The agent writes this script, runs it via `bash python3 analyze.py`, reads the output, and decides what to try next.

### 4.2 Data Loading and Profiling

```python
# urika/data/loader.py

def load_dataset(
    path: str | Path,
    format: str | None = None,    # auto-detected if None
    schema: dict | None = None,   # optional column type overrides
) -> Dataset:
    """Load a dataset from any supported format.

    Supports: CSV, TSV, Excel, Parquet, SPSS (.sav), Stata (.dta),
    JSON, JSON Lines. Optional readers for HDF5, EDF, C3D, etc.
    """
    ...

def profile(ds: Dataset) -> DataProfile:
    """Generate a comprehensive data profile.

    Returns: row/column counts, dtypes, missing values per column,
    descriptive stats (mean, sd, median, IQR), distribution shapes,
    correlation matrix, potential issues (high missingness, low variance,
    multicollinearity).
    """
    ...
```

**Dataset class:**

```python
@dataclass
class Dataset:
    df: pd.DataFrame              # the actual data
    path: Path                    # source file path
    metadata: dict                # format info, load options used
    schema: DataSchema            # column types, roles, measurement levels

@dataclass
class DataSchema:
    columns: dict[str, ColumnInfo]

@dataclass
class ColumnInfo:
    dtype: str                    # "numeric", "categorical", "ordinal", "datetime", "text"
    role: str | None              # "target", "predictor", "id", "group", "time", None
    measurement_level: str | None # "nominal", "ordinal", "interval", "ratio"
    missing_count: int
    unique_count: int
```

**Format readers** — pluggable via protocol:

| Reader | Formats | Install |
|--------|---------|---------|
| `tabular.py` | CSV, TSV, Excel, Parquet, SPSS, Stata | Core |
| `json_reader.py` | JSON, JSON Lines | Core |
| `hdf5_reader.py` | HDF5, MAT v7.3 | `pip install urika[hdf5]` |
| `edf_reader.py` | EDF, EDF+, BDF | `pip install urika[eeg]` |
| `c3d_reader.py` | C3D | `pip install urika[motion]` |
| `imu_reader.py` | Axivity CWA, ActiGraph GT3X | `pip install urika[wearables]` |
| `audio_reader.py` | WAV, MP3 | `pip install urika[audio]` |

### 4.3 Methods

Methods are Python classes that follow a consistent interface. Agents can use built-in methods or write new ones.

```python
# urika/methods/base.py

class AnalysisMethod(ABC):
    """Base class for all analysis methods."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def category(self) -> str: ...   # "regression", "classification", "hypothesis_test", etc.

    @abstractmethod
    def fit(self, ds: Dataset, **kwargs) -> MethodResult: ...

    def get_params(self) -> dict: ...
    def set_params(self, **kwargs): ...
    def default_params(self) -> dict: ...

@dataclass
class MethodResult:
    method_name: str
    outputs: dict[str, Any]       # predictions, coefficients, p-values, etc.
    metrics: dict[str, float]     # computed quality metrics
    diagnostics: dict             # residual plots paths, assumption checks, etc.
    artifacts: list[str]          # paths to generated files
    summary_text: str             # human-readable summary

    def summary(self) -> str:
        return self.summary_text

    def save_artifacts(self, directory: str | Path):
        """Save all artifacts to the given directory."""
        ...
```

**Built-in methods (ship with the package):**

| Category | Methods |
|----------|---------|
| Regression | `LinearRegression`, `RidgeRegression`, `LassoRegression`, `ElasticNet` |
| Classification | `LogisticRegression`, `RandomForest`, `GradientBoosting`, `SVM` |
| Hypothesis tests | `TTest`, `PairedTTest`, `WelchTTest`, `MannWhitneyU`, `ANOVA`, `MixedANOVA`, `ChiSquared`, `KruskalWallis` |
| Effect sizes | `CohensD`, `HedgesG`, `EtaSquared`, `OddsRatio` |
| Mixed models | `LinearMixedEffects`, `GeneralizedLinearMixed` |
| Dimensionality reduction | `PCA`, `FactorAnalysis` |
| Time series | `ARIMAModel`, `ExponentialSmoothing`, `SpectralAnalysis` |
| Clustering | `KMeansClustering`, `HierarchicalClustering`, `DBSCAN` |

Agents can also write entirely new methods as Python classes in the `methods/` directory. The method registry auto-discovers them:

```python
# urika/methods/registry.py

def discover_methods(search_dirs: list[Path]) -> dict[str, type[AnalysisMethod]]:
    """Auto-discover AnalysisMethod subclasses from Python files in search_dirs."""
    ...
```

### 4.4 Evaluation Framework

```python
# urika/evaluation/evaluate.py

def evaluate(
    result: MethodResult,
    ds: Dataset,
    metrics: list[Metric] | None = None,
) -> dict[str, float]:
    """Compute evaluation metrics for a method result."""
    ...

def check_criteria(
    metrics: dict[str, float],
    criteria_path: str | Path,
) -> tuple[bool, list[str]]:
    """Check metrics against success criteria.

    Returns (all_passed, list_of_failure_messages).
    """
    ...
```

**Metric registry:**

```python
# urika/evaluation/metrics.py

class Metric(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def compute(self, y_true, y_pred, **kwargs) -> float: ...

    @abstractmethod
    def direction(self) -> str: ...   # "higher_is_better" | "lower_is_better"
```

Built-in metrics: RMSE, MAE, R-squared, adjusted R-squared, accuracy, precision, recall, F1, AUC-ROC, AIC, BIC, Cohen's d, Hedge's g, eta-squared, ICC, Cronbach's alpha, CFI, RMSEA.

**Leaderboard:**

```python
# urika/evaluation/leaderboard.py

def update_leaderboard(
    method: str,
    metrics: dict[str, float],
    run_id: str,
    params: dict | None = None,
    leaderboard_path: str | Path = "results/leaderboard.json",
    primary_metric: str | None = None,
    direction: str | None = None,
):
    """Update the investigation leaderboard with a new result."""
    ...

def get_leaderboard(
    leaderboard_path: str | Path = "results/leaderboard.json",
) -> pd.DataFrame:
    """Load the leaderboard as a DataFrame, sorted by primary metric."""
    ...
```

**Success criteria format:**

```json
{
  "primary_metric": "rmse",
  "direction": "lower_is_better",
  "criteria": [
    {"metric": "rmse", "max": 0.05, "description": "Prediction error below 5%"},
    {"metric": "r_squared", "min": 0.85, "description": "At least 85% variance explained"},
    {"metric": "residual_normality_p", "min": 0.05, "type": "diagnostic", "description": "Residuals approximately normal"}
  ]
}
```

**Trust model:**

1. `evaluation/` directory and `config/success_criteria.json` are read-only for task agents (enforced by tool registry)
2. The evaluator agent runs evaluation independently after task agents claim results
3. If an agent claims `criteria_met: true` but the evaluator's independent check disagrees, the evaluator corrects the flag
4. All evaluation runs are logged with full provenance

### 4.5 Investigation Modes

Three modes to handle the range of scientific analysis:

**Exploratory mode** (default) — Try approaches, rank them, iterate:
- Task agents explore freely
- Leaderboard tracks all attempts
- Suggestion agent proposes next directions
- Terminates when criteria are met or turn limit is reached

**Confirmatory mode** — Pre-registered analysis with p-hacking guardrails:
- Analysis plan is locked before data is examined
- No leaderboard (no method shopping)
- Multiple comparison corrections enforced
- Full transparency log: every test run, every metric computed
- Cannot retroactively change success criteria
- Warnings if the agent attempts to run tests not in the pre-registered plan

**Pipeline mode** — Ordered processing stages:
- For domains requiring preprocessing before analysis (EEG, motor control, wearables)
- Stages: ingest -> preprocess -> feature extraction -> analysis -> evaluation
- Each stage has its own success criteria
- Agents can iterate within a stage but cannot skip stages

### 4.6 Knowledge Pipeline

```python
# urika/knowledge/pdf_extractor.py
def extract_pdf(path: Path) -> ExtractedDocument:
    """Extract text, tables, and figures from a PDF using pymupdf."""
    ...

# urika/knowledge/literature.py
def search_literature(query: str, max_results: int = 10) -> list[PaperSummary]:
    """Search academic databases for relevant papers."""
    ...

def fetch_paper(url: str) -> ExtractedDocument:
    """Download and extract a paper from a URL."""
    ...

# urika/knowledge/index.py
class KnowledgeIndex:
    """Manages the knowledge base for an investigation."""

    def add_document(self, doc: ExtractedDocument): ...
    def search(self, query: str, top_k: int = 5) -> list[KnowledgeEntry]: ...
    def list_methods_mentioned(self) -> list[str]: ...
    def list_papers(self) -> list[PaperSummary]: ...
```

Knowledge storage:

```
knowledge/
    index.json                    # master index of all knowledge
    papers/
        paper_001.json            # extracted text, tables, key findings
        paper_002.json
    profiles/
        dataset_profile.json      # auto-generated data profile
    notes/
        user_notes.md             # researcher's own notes
```

### 4.7 Session and Experiment Tracking

```
results/
    sessions/
        session_001/
            session.json              # metadata: start time, status, config snapshot
            progress.json             # run-by-run tracking
            evaluation/
                metrics.json          # evaluator output
                criteria_check.json   # pass/fail per criterion
            runs/
                run_001/
                    run.json          # method, params, metrics, hypothesis, observation
                    artifacts/        # plots, tables, exports
                run_002/
                    ...
    leaderboard.json                  # global method rankings
    suggestions/
        suggestion_001.json           # structured suggestion from suggestion agent
```

**`progress.json` format:**

```json
{
    "session_id": "session_001",
    "status": "in_progress",
    "criteria_met": false,
    "best_run": {"run_id": "run_003", "method": "xgboost_v2", "metrics": {"rmse": 0.042}},
    "runs": [
        {
            "run_id": "run_001",
            "method": "linear_regression",
            "params": {"alpha": 0.1},
            "metrics": {"rmse": 0.15, "r_squared": 0.72},
            "hypothesis": "Baseline linear model to establish floor",
            "observation": "R2=0.72, significant nonlinearity in residuals",
            "next_step": "Try tree-based methods for nonlinear relationships"
        }
    ]
}
```

---

## 5. Project Structure

```
urika/
    pyproject.toml                    # PEP 621, hatch build, dependency groups
    LICENSE                           # MIT
    CLAUDE.md

    src/urika/
        __init__.py
        __main__.py                   # python -m urika
        cli.py                        # click CLI: init, run, status, results, compare, report

        # =============================================
        # RUNTIME (Option C only — this is what the Claude Agent SDK or Pi gives you for free)
        # =============================================
        runtime/
            __init__.py
            loop.py                   # AgentLoop: prompt -> LLM -> parse -> dispatch -> repeat
            streaming.py              # StreamingAgentLoop for interactive display
            messages.py               # Message, ParsedResponse, ToolCall, ToolResult dataclasses
            agent_config.py           # AgentConfig dataclass
            agent_result.py           # AgentResult dataclass
            compaction.py             # Context window summarization / history compaction

            llm/
                __init__.py           # Provider registration
                base.py               # LLMProvider ABC
                registry.py           # ProviderRegistry
                retry.py              # Retry logic, rate limit backoff, exponential backoff
                token_counter.py      # Per-provider token counting
                providers/
                    __init__.py
                    anthropic.py      # Claude via anthropic SDK
                    openai_compat.py  # OpenAI, Azure, vLLM, Ollama, Groq, Together
                    litellm_provider.py   # Fallback for everything else
                    tool_use_shim.py  # Prompt-based tool use for non-native models

            tools/
                __init__.py
                base.py               # Tool ABC, ToolSchema, ToolContext
                registry.py           # ToolRegistry (per-agent tool sets)
                core/
                    __init__.py
                    read_file.py      # Read file contents
                    write_file.py     # Write file with directory boundary checks
                    edit_file.py      # Targeted string replacement edits
                    bash.py           # Shell command execution with security
                    glob_tool.py      # File pattern matching
                    grep_tool.py      # Content search

            session/
                __init__.py
                session.py            # Session persistence (JSONL messages + tool log)
                manager.py            # Create, resume, list sessions

        # =============================================
        # URIKA PLATFORM (identical in Option A, Option B, and Option C)
        # =============================================

        # --- Core configuration and protocols ---
        core/
            __init__.py
            config.py                 # InvestigationConfig, ProjectConfig, TOML loading
            investigation.py          # Investigation lifecycle (init, run, resume)
            protocols.py              # Shared interfaces/protocols
            exceptions.py

        # --- Multi-agent orchestration ---
        agents/
            __init__.py
            orchestrator.py           # Deterministic loop: task -> evaluate -> suggest -> repeat
            security.py               # Per-agent tool registry builders (write boundaries)
            agent_registry.py         # Auto-discover agents from agents/*/

            system_builder/
                __init__.py
                agent.py              # System builder agent config + launch
                prompts/
                    system_prompt.md

            task_agent/
                __init__.py
                agent.py
                prompts/
                    system_prompt.md

            evaluator/
                __init__.py
                agent.py
                prompts/
                    system_prompt.md

            suggestion_agent/
                __init__.py
                agent.py
                prompts/
                    system_prompt.md

            tool_builder/
                __init__.py
                agent.py
                prompts/
                    system_prompt.md

            literature_agent/
                __init__.py
                agent.py
                prompts/
                    system_prompt.md

        # --- Data loading and profiling ---
        data/
            __init__.py
            dataset.py                # Dataset, DataSchema, ColumnInfo dataclasses
            loader.py                 # load_dataset() with format auto-detection
            profile.py                # profile() — comprehensive EDA
            schema.py                 # Schema inference and column role detection
            readers/
                __init__.py
                base.py               # IDataReader protocol
                tabular.py            # CSV, Excel, Parquet, SPSS, Stata
                json_reader.py        # JSON, JSON Lines
                # Optional readers (installed via extras):
                hdf5_reader.py
                edf_reader.py
                c3d_reader.py
                imu_reader.py
                audio_reader.py

        # --- Analysis methods ---
        methods/
            __init__.py
            base.py                   # AnalysisMethod ABC, MethodResult dataclass
            registry.py               # discover_methods() auto-discovery
            statistical/
                __init__.py
                linear_regression.py
                logistic_regression.py
                ridge_lasso.py
                t_tests.py            # TTest, PairedTTest, WelchTTest
                anova.py              # ANOVA, MixedANOVA
                nonparametric.py      # MannWhitneyU, KruskalWallis, ChiSquared
                mixed_models.py       # LinearMixedEffects
                effect_sizes.py       # CohensD, HedgesG, EtaSquared
            ml/
                __init__.py
                random_forest.py
                gradient_boosting.py
                svm.py
                clustering.py         # KMeans, Hierarchical, DBSCAN
                dimensionality.py     # PCA, FactorAnalysis
            timeseries/
                __init__.py
                arima.py
                spectral.py
                smoothing.py

        # --- Evaluation framework ---
        evaluation/
            __init__.py
            evaluate.py               # evaluate() — run metrics on a MethodResult
            criteria.py               # check_criteria() — validate against success criteria
            leaderboard.py            # update_leaderboard(), get_leaderboard()
            metrics/
                __init__.py
                base.py               # Metric ABC
                registry.py           # MetricRegistry with auto-discovery
                regression.py         # RMSE, MAE, R2, adjusted R2
                classification.py     # Accuracy, Precision, Recall, F1, AUC
                information.py        # AIC, BIC
                effect_size.py        # Cohen's d, Hedge's g, eta-squared
                reliability.py        # ICC, Cronbach's alpha
                fit_indices.py        # CFI, RMSEA (for SEM/CFA)

        # --- Knowledge pipeline ---
        knowledge/
            __init__.py
            pdf_extractor.py          # PDF text + table extraction (pymupdf)
            literature.py             # Web search, paper fetching
            index.py                  # KnowledgeIndex management

        # --- Session and experiment tracking ---
        sessions/
            __init__.py
            tracking.py              # log_run(), current_session()
            comparison.py            # Cross-session comparison
            persistence.py           # SQLite metadata store for fast queries

    # Per-investigation workspace (created by `urika init`):
    # my-investigation/
    #     urika.toml                 # Investigation config
    #     data/                      # Dataset files
    #     knowledge/                 # Ingested papers, profiles, notes
    #     methods/                   # Agent-written methods (writable by task agents)
    #     tools/                     # Agent-built tools (writable by tool builder)
    #     results/
    #         sessions/
    #         suggestions/
    #         leaderboard.json
    #     config/
    #         success_criteria.json
    #         agents.json
    #     evaluation/                # Read-only evaluation code (not writable by task agents)

    tests/
        conftest.py
        test_runtime/
            test_loop.py
            test_llm_providers.py
            test_tools_core.py
            test_session.py
            test_compaction.py
        test_agents/
            test_orchestrator.py
            test_security.py
        test_data/
            test_loader.py
            test_profile.py
            test_readers.py
        test_methods/
            test_statistical.py
            test_ml.py
            test_registry.py
        test_evaluation/
            test_evaluate.py
            test_criteria.py
            test_leaderboard.py
            test_metrics.py
        test_knowledge/
            test_pdf_extractor.py
            test_literature.py
        test_integration/
            test_end_to_end.py       # Full: init -> run -> evaluate -> results
```

---

## 6. Implementation Plan

### Phase 1: Agent Runtime (Option C only — ~4-6 weeks)

This entire phase is work that the Claude Agent SDK (Option A) or Pi (Option B) gives you for free. It must be completed before any Urika-specific work can begin, because agents need an agent loop to run in.

**1.1 Core data types and message model (~2 days)**
- `runtime/messages.py` — `Message`, `ToolCall`, `ToolResult`, `ParsedResponse` dataclasses
- `runtime/agent_config.py` — `AgentConfig` dataclass
- `runtime/agent_result.py` — `AgentResult` dataclass
- All with JSON serialization for persistence

**1.2 LLM provider interface and Anthropic provider (~3 days)**
- `runtime/llm/base.py` — `LLMProvider` ABC
- `runtime/llm/registry.py` — `ProviderRegistry`
- `runtime/llm/providers/anthropic.py` — Claude provider via `anthropic` SDK
- Message formatting: system prompt extraction, content block parsing, tool-use response handling
- `runtime/llm/retry.py` — exponential backoff, rate limit detection, transient error recovery
- Tests with mocked API responses

**1.3 OpenAI-compatible provider (~2 days)**
- `runtime/llm/providers/openai_compat.py` — OpenAI, Azure, vLLM, Ollama
- Handle differences: function-calling format, tool_choice, finish_reason parsing
- Tests with mocked API responses

**1.4 LiteLLM fallback provider (~1 day)**
- `runtime/llm/providers/litellm_provider.py` — wraps litellm for Gemini, Mistral, etc.
- Optional dependency — graceful import failure

**1.5 Tool system foundation (~2 days)**
- `runtime/tools/base.py` — `Tool` ABC, `ToolSchema`, `ToolContext`
- `runtime/tools/registry.py` — `ToolRegistry` with per-agent tool sets
- JSON Schema validation via `jsonschema`

**1.6 Core tools (~5 days)**
- `runtime/tools/core/read_file.py` — read file contents, line range support
- `runtime/tools/core/write_file.py` — write with directory boundary enforcement
- `runtime/tools/core/edit_file.py` — targeted string replacement with uniqueness checks
- `runtime/tools/core/bash.py` — subprocess execution, timeout, stdout/stderr capture, command allowlisting
- `runtime/tools/core/glob_tool.py` — file pattern matching
- `runtime/tools/core/grep_tool.py` — content search with regex
- Each tool includes input validation, error handling, and tests
- `edit_file` is the hardest — needs to handle uniqueness failures and provide good error messages

**1.7 Agent loop (~3 days)**
- `runtime/loop.py` — `AgentLoop` class: message assembly, LLM call, response parsing, tool dispatch, result appending
- Turn limit enforcement
- Early termination detection
- Error handling at each stage (malformed response, tool failure, timeout)
- Tests with mock LLM and mock tools

**1.8 Session persistence (~2 days)**
- `runtime/session/session.py` — JSONL message persistence, tool call audit log
- `runtime/session/manager.py` — create session, resume session, list sessions
- Resume: load messages from JSONL, continue the loop

**1.9 Context window management (~3 days)**
- `runtime/llm/token_counter.py` — per-provider token counting (tiktoken for OpenAI, anthropic's counter for Claude, estimation for others)
- `runtime/compaction.py` — history summarization when approaching context limit
- Strategy: keep system prompt + last N turns, summarize middle section
- Tests verifying compaction preserves critical information

**1.10 Streaming layer (~2 days)**
- `runtime/streaming.py` — `StreamingAgentLoop` that yields tokens during LLM response
- Display callback interface for CLI output
- Collect full response before tool dispatch (streaming is display-only)

**1.11 Tool-use shim (~2 days)**
- `runtime/llm/providers/tool_use_shim.py` — wraps any provider to add tool use via prompt injection
- Inject tool schemas as structured text in system prompt
- Parse tool calls from model text output (XML or JSON format)
- This is inherently fragile — mark as experimental

**Phase 1 total: ~27 days of focused development**

**Milestone: A working agent loop that can take a prompt, call an LLM, use tools to read/write files and run bash commands, and produce a result. Tested with at least Anthropic and OpenAI providers.**

### Phase 2: Core Platform Infrastructure (~2-3 weeks)

**2.1 Configuration system (~2 days)**
- `core/config.py` — `InvestigationConfig`, `ProjectConfig` dataclasses
- TOML loading/saving for `urika.toml`
- Success criteria JSON format and loading
- Agent configuration (which agent gets which model, tools, write permissions)

**2.2 Data loading and profiling (~4 days)**
- `data/dataset.py` — `Dataset`, `DataSchema`, `ColumnInfo` dataclasses
- `data/loader.py` — `load_dataset()` with format auto-detection
- `data/readers/tabular.py` — CSV, Excel, Parquet reader (pandas-based)
- `data/readers/json_reader.py` — JSON / JSON Lines reader
- `data/profile.py` — `profile()` function: dtypes, missing values, descriptive stats, distributions, correlations, potential issues
- `data/schema.py` — schema inference, column role detection (id, target, predictor, group, time)

**2.3 Method base classes and registry (~2 days)**
- `methods/base.py` — `AnalysisMethod` ABC, `MethodResult` dataclass
- `methods/registry.py` — `discover_methods()` auto-discovery from Python files
- Template for writing new methods

**2.4 Evaluation framework (~3 days)**
- `evaluation/metrics/base.py` — `Metric` ABC
- `evaluation/metrics/registry.py` — `MetricRegistry` with auto-discovery
- Built-in metrics: RMSE, MAE, R2, accuracy, F1, AUC, Cohen's d
- `evaluation/evaluate.py` — `evaluate()` function
- `evaluation/criteria.py` — `check_criteria()` against success criteria JSON
- `evaluation/leaderboard.py` — `update_leaderboard()`, `get_leaderboard()`

**2.5 Session tracking (~2 days)**
- `sessions/tracking.py` — `log_run()`, `current_session()`
- `sessions/persistence.py` — SQLite metadata for fast queries across sessions
- `sessions/comparison.py` — cross-session comparison utilities
- `progress.json` reading/writing

**Phase 2 total: ~13-17 days**

**Milestone: The `urika` Python library is pip-installable. You can write a Python script that loads a CSV, runs a linear regression, evaluates it, checks criteria, and updates a leaderboard — all using `from urika import ...`.**

### Phase 3: Built-in Methods (~2 weeks)

**3.1 Statistical methods (~4 days)**
- `methods/statistical/linear_regression.py` — OLS via statsmodels, with diagnostics
- `methods/statistical/logistic_regression.py` — via statsmodels
- `methods/statistical/t_tests.py` — `TTest`, `PairedTTest`, `WelchTTest` via scipy/pingouin
- `methods/statistical/anova.py` — `ANOVA`, `MixedANOVA` via pingouin
- `methods/statistical/nonparametric.py` — Mann-Whitney U, Kruskal-Wallis, Chi-squared
- `methods/statistical/effect_sizes.py` — Cohen's d, Hedge's g, eta-squared
- `methods/statistical/mixed_models.py` — linear mixed effects via statsmodels

**3.2 ML methods (~3 days)**
- `methods/ml/random_forest.py` — via scikit-learn
- `methods/ml/gradient_boosting.py` — XGBoost/scikit-learn
- `methods/ml/svm.py` — via scikit-learn
- `methods/ml/clustering.py` — KMeans, Hierarchical, DBSCAN
- `methods/ml/dimensionality.py` — PCA, Factor Analysis

**3.3 Time series methods (~2 days)**
- `methods/timeseries/arima.py` — via statsmodels
- `methods/timeseries/spectral.py` — via scipy
- `methods/timeseries/smoothing.py` — exponential smoothing via statsmodels

**3.4 Additional evaluation metrics (~1 day)**
- `evaluation/metrics/information.py` — AIC, BIC
- `evaluation/metrics/reliability.py` — ICC, Cronbach's alpha
- `evaluation/metrics/fit_indices.py` — CFI, RMSEA

**Phase 3 total: ~10-12 days**

**Milestone: A substantial library of analysis methods and metrics that agents can import and use. Enough to handle the most common analysis patterns across behavioral and health sciences.**

### Phase 4: Multi-Agent Orchestration (~2-3 weeks)

**4.1 Agent security boundaries (~2 days)**
- `agents/security.py` — per-agent tool registry builders
- `build_task_agent_tools()` — read + write (restricted dirs) + bash
- `build_evaluator_tools()` — read-only + bash (python only)
- `build_suggestion_agent_tools()` — read + write (suggestions/ only)
- `build_tool_builder_tools()` — read + write (tools/ only) + bash
- Integration tests verifying agents cannot escape their boundaries

**4.2 Orchestrator (~3 days)**
- `agents/orchestrator.py` — deterministic Python loop
- Sequence: task agent -> evaluator -> suggestion agent -> (optional) tool builder -> repeat
- Session creation, agent spawning via `AgentLoop`, result collection
- Turn budget allocation across agents
- Termination: criteria met, turn limit, agent requests stop
- Support for `--continue` (resume from last session state)

**4.3 Agent prompts (~5 days)**
- `agents/system_builder/prompts/system_prompt.md` — investigation setup workflow
- `agents/task_agent/prompts/system_prompt.md` — analysis workflow, how to use `urika` library
- `agents/evaluator/prompts/system_prompt.md` — independent evaluation, criteria checking
- `agents/suggestion_agent/prompts/system_prompt.md` — strategic analysis, literature integration
- `agents/tool_builder/prompts/system_prompt.md` — tool/method creation workflow
- `agents/literature_agent/prompts/system_prompt.md` — knowledge acquisition
- Each prompt includes: role description, available tools, expected outputs, examples, constraints

**4.4 Agent launch and configuration (~2 days)**
- `agents/*/agent.py` — each agent module defines its config (model, tools, write boundaries, prompts)
- `agents/agent_registry.py` — auto-discover agents from `agents/*/`
- Integration with the runtime's `AgentLoop` — each agent gets its own loop instance with its own tool registry and LLM config

**4.5 Investigation lifecycle (~2 days)**
- `core/investigation.py` — `init_investigation()`, `run_investigation()`, `resume_investigation()`
- `urika init` workflow: create directory structure, launch system builder agent
- `urika run` workflow: launch orchestrator, which spawns task/eval/suggestion agents
- `urika run --continue` workflow: load last session, resume orchestrator

**Phase 4 total: ~14-18 days**

**Milestone: A working multi-agent system. `urika init` launches the system builder to set up an investigation. `urika run` launches the orchestrator, which sequences task, evaluator, and suggestion agents. Agents communicate via JSON files on disk.**

### Phase 5: Knowledge Pipeline (~1-2 weeks)

**5.1 PDF extraction (~2 days)**
- `knowledge/pdf_extractor.py` — text and table extraction via pymupdf
- Handle: multi-column layouts, tables, figures (as image paths), references sections

**5.2 Literature search (~3 days)**
- `knowledge/literature.py` — web search integration for academic papers
- ArXiv API integration
- Google Scholar scraping (with rate limiting)
- Paper download and extraction

**5.3 Knowledge index (~2 days)**
- `knowledge/index.py` — `KnowledgeIndex` class
- Add documents, search by query, list methods mentioned, list papers
- JSON-based storage with optional SQLite backing for search

**5.4 Literature agent (~2 days)**
- `agents/literature_agent/agent.py` — config and launch
- Prompts for knowledge acquisition workflow
- Integration with orchestrator (called when suggestion agent requests literature)

**Phase 5 total: ~9-11 days**

### Phase 6: CLI and Investigation Modes (~1-2 weeks)

**6.1 CLI implementation (~3 days)**
- `cli.py` — click subcommands:
  ```
  urika init <name>                 # Create investigation workspace
  urika run                         # Start investigation
  urika run --continue              # Resume last session
  urika run --max-turns <n>         # Limit total turns
  urika status                      # Show investigation status
  urika results                     # Show all results and leaderboard
  urika compare <s1> <s2>           # Compare two sessions
  urika report                      # Generate summary report
  urika knowledge ingest <path>     # Ingest a document
  urika knowledge search <query>    # Search knowledge base
  urika agents --list               # List available agents
  urika tools --list                # List available tools/methods
  ```

**6.2 Investigation modes (~3 days)**
- Confirmatory mode: locked analysis plan, no leaderboard, multiple comparison corrections, transparency log
- Pipeline mode: ordered stages with per-stage criteria
- Mode selection in `urika.toml` and `urika init`

**6.3 Reporting (~2 days)**
- `urika report` — generate a markdown summary of the investigation
- Include: research question, methods tried, results, best method, leaderboard, plots, recommendations

**Phase 6 total: ~8-10 days**

### Phase 7: Testing and Hardening (~1-2 weeks)

**7.1 Unit tests (~3 days)**
- Runtime: agent loop with mock LLM, tool dispatch, session persistence, compaction
- Data: loading each format, profiling, schema inference
- Methods: each built-in method produces correct output on known data
- Evaluation: each metric computes correctly, criteria checking, leaderboard

**7.2 Integration tests (~3 days)**
- End-to-end: CSV dataset -> `urika init` -> `urika run --max-turns 10` -> results
- Agent security: verify evaluator cannot write, task agent cannot modify evaluation
- Session resume: run, stop, resume, verify state continuity
- Multi-provider: same investigation with Anthropic and OpenAI providers

**7.3 Hardening (~2 days)**
- Error messages for common failures (missing API key, data format errors, method failures)
- Graceful degradation when optional dependencies are missing
- Signal handling (Ctrl+C saves session state)

**Phase 7 total: ~8-10 days**

### Phase 8: Domain Packs (post-core, ongoing)

Domain packs are separate optional installs. Each provides domain-specific readers, methods, metrics, and prompt templates.

Priority order:
1. **Survey/Psychometrics** — factor analysis, SEM, Cronbach's alpha, Likert scale methods
2. **Cognitive Experiments** — RT analysis, signal detection theory, drift diffusion models
3. **Wearable Sensors** — IMU readers, activity classification, signal processing pipelines
4. **Motor Control** — C3D readers, kinematics, coordination analysis
5. **Eye Tracking** — fixation analysis, scanpath comparison, pupillometry
6. **Cognitive Neuroscience** — EDF readers, ERP analysis, time-frequency, MVPA (requires MNE)
7. **Computer Vision / LiDAR** — point cloud readers, detection evaluation
8. **Linguistics** — NLP pipelines, acoustic analysis, speech processing
9. **Epidemiology** — survival analysis, spatial statistics, case-control methods

### Total Timeline Estimate

| Phase | Duration | Cumulative |
|-------|---------|-----------|
| Phase 1: Agent Runtime | 4-6 weeks | 4-6 weeks |
| Phase 2: Core Platform | 2-3 weeks | 6-9 weeks |
| Phase 3: Built-in Methods | 2 weeks | 8-11 weeks |
| Phase 4: Multi-Agent Orchestration | 2-3 weeks | 10-14 weeks |
| Phase 5: Knowledge Pipeline | 1-2 weeks | 11-16 weeks |
| Phase 6: CLI and Modes | 1-2 weeks | 12-18 weeks |
| Phase 7: Testing and Hardening | 1-2 weeks | 13-20 weeks |
| **Total to working system** | **13-20 weeks** | |
| Phase 8: Domain Packs | Ongoing | |

**Compare with Option A and Option B:** Both Option A (Claude Agent SDK) and Option B (Pi) skip Phase 1 entirely and start at Phase 2. That saves 4-6 weeks of development and eliminates the ongoing maintenance burden of the runtime.

---

## 7. Risks and Mitigations

### Risk 1: The Runtime Becomes the Project

**Risk:** You spend months building and debugging the agent loop, LLM providers, and core tools — and never get to the actual analysis platform. The runtime is not the product. The analysis platform is the product.

**Likelihood:** High. Agent loops have subtle edge cases: malformed LLM responses, partial tool calls, context window overflows, provider-specific quirks, streaming interruptions. Each one takes time to diagnose and fix.

**Mitigation:** Strict time-box Phase 1 to 6 weeks. If the runtime is not working reliably by week 6, seriously consider switching to Option A or Option B. The analysis framework code you have written in Phase 2+ transfers directly.

### Risk 2: Core Tool Quality

**Risk:** Your v1 `edit_file`, `bash`, and `read_file` tools have bugs that established tools (Pi's, Claude Code's) have already fixed. Agents fail in ways that are hard to diagnose because the bug is in the tool, not the agent's logic.

**Likelihood:** High for `edit_file` (fuzzy matching, handling of duplicate strings, encoding issues). Medium for `bash` (timeout handling, output truncation, environment variables). Low for `read_file`.

**Mitigation:** Invest disproportionately in tool testing. Write comprehensive test suites for each core tool before building on top of them. Consider porting test cases from Pi's tool tests.

### Risk 3: Provider Maintenance Burden

**Risk:** LLM APIs change. Claude adds extended thinking, OpenAI changes their function-calling format, Google changes Gemini's tool protocol. Each change requires updating a provider adapter.

**Likelihood:** Certain. LLM APIs are evolving rapidly. Expect 2-4 breaking changes per year across providers.

**Mitigation:** Use litellm as the primary fallback provider — it absorbs most API changes upstream. Only maintain direct providers (Anthropic, OpenAI) for the two most critical integrations. Accept that non-Anthropic provider support may lag.

### Risk 4: Context Window Management Is Harder Than It Looks

**Risk:** Long scientific investigations (50+ turns) overflow context windows. Your compaction/summarization strategy loses critical information — the agent forgets what it already tried, re-runs failed approaches, or loses track of the investigation state.

**Likelihood:** High. This is a known hard problem. Both the Claude Agent SDK and Pi have invested significant engineering into context management.

**Mitigation:** Keep the summarization strategy simple (keep system prompt + last N turns + summarize middle). Store full history on disk so nothing is permanently lost. Use structured `progress.json` as the ground truth for investigation state, not conversation history — the agent reads `progress.json` at the start of each turn to know where it is.

### Risk 5: Solo Maintenance

**Risk:** The runtime, providers, tools, analysis framework, agents, tests — maintained by one person. When something breaks in the runtime while you are working on the analysis framework, context switching costs are high.

**Likelihood:** High for a solo developer.

**Mitigation:** Keep the runtime as minimal as possible. Resist feature creep (no TUI in v1, no parallel tool dispatch in v1, no fancy streaming in v1). The simpler the runtime, the less maintenance it needs.

### Risk 6: Model Flexibility May Not Matter in Practice

**Risk:** You build a multi-provider runtime for model flexibility, then use Claude for 95% of work because it is the best at tool use and code generation. The provider abstraction was unnecessary complexity.

**Likelihood:** Medium. Claude is currently the best at agentic coding tasks. But the landscape changes fast, and research institutions often have specific model requirements (budget, data sovereignty, institutional agreements).

**Mitigation:** This risk is acceptable if the provider abstraction is clean and cheap to maintain. The LiteLLM fallback handles most providers with minimal custom code. The real cost is only the Anthropic + OpenAI direct providers (~300-400 lines each).

---

## 8. Three-Way Comparison: Claude Agent SDK vs Pi vs Custom Runtime

### Option A: Claude Agent SDK

| Aspect | Details |
|--------|---------|
| **Language** | Python |
| **LLM support** | Claude only (Anthropic-native) |
| **What you get** | Agent loop, tool dispatch, Claude-optimized tool use, session management |
| **What you build** | Multi-agent orchestration, security boundaries, analysis framework, knowledge pipeline |
| **Strengths** | Python-native, fast to start, Anthropic-maintained, excellent Claude integration |
| **Weaknesses** | Locked to Claude, Anthropic controls the roadmap, limited model flexibility |
| **Time to first agent** | Days |
| **Runtime maintenance** | None (Anthropic maintains it) |

### Option B: Pi

| Aspect | Details |
|--------|---------|
| **Language** | TypeScript (runtime) + Python (analysis) |
| **LLM support** | 15+ providers out of the box |
| **What you get** | Agent loop, tool dispatch, core tools, 15+ LLM providers, session management, TUI, streaming, extension system |
| **What you build** | Multi-agent orchestration (as TypeScript extension), security boundaries, analysis framework (Python), knowledge pipeline |
| **Strengths** | Battle-tested tools, broad model support, active community, extension system |
| **Weaknesses** | TypeScript/Python split, upstream dependency, TypeScript orchestration for a Python-heavy project |
| **Time to first agent** | Days |
| **Runtime maintenance** | None (Pi community maintains it) |

### Option C: Custom Runtime

| Aspect | Details |
|--------|---------|
| **Language** | Python (everything) |
| **LLM support** | Anthropic + OpenAI direct, everything else via LiteLLM |
| **What you get** | Full control, single-language stack, no upstream dependencies |
| **What you build** | Agent loop, LLM providers, core tools, session management, streaming, retries — PLUS all the Urika-specific work |
| **Strengths** | Total control, Python-only stack, no vendor lock-in, deep debuggability |
| **Weaknesses** | 4-6 weeks extra development, ongoing runtime maintenance, v1 tool bugs, solo maintenance burden |
| **Time to first agent** | 4-6 weeks |
| **Runtime maintenance** | Ongoing (~10-20% of development time) |

### The Tradeoff Summary

| Factor | Option A (Claude SDK) | Option B (Pi) | Option C (Custom) |
|--------|----------------------|---------------|-------------------|
| Time to first working agent | Fastest | Fast | Slowest (+4-6 weeks) |
| Model flexibility | Claude only | Excellent (15+) | Good (via LiteLLM) |
| Language consistency | Python | TypeScript + Python | Python |
| Upstream dependency risk | Medium (Anthropic) | Medium (community project) | None |
| Runtime maintenance burden | None | None | Significant |
| Debuggability | Good | Medium (through Pi abstractions) | Excellent (all your code) |
| Tool maturity | Good | Excellent | Low (v1) |
| Total lines of code you write | ~11,000-17,000 | ~11,000-17,000 | ~14,000-21,000 |

### When Each Option Makes Sense

**Choose Option A (Claude Agent SDK)** when:
- You want the fastest path to validating the analysis platform concept
- Claude is your primary (or only) LLM and you are comfortable with that dependency
- You want a Python-native stack without the custom runtime overhead
- Anthropic's roadmap alignment with your needs is acceptable

**Choose Option B (Pi)** when:
- Model flexibility is important from day one
- You are comfortable with TypeScript + Python coexistence
- You value battle-tested core tools and a mature extension system
- You want a proven agent runtime without building one

**Choose Option C (Custom Runtime)** when:
- You are committed to a Python-only stack with no upstream dependencies
- You need full control over every layer of the system
- You plan to invest >6 months and the runtime pays for itself through reduced friction
- You enjoy building infrastructure and find it energizing rather than draining
- You want to deeply understand every layer of the system

### The Key Insight

The Python analysis framework — data loading, methods, evaluation, metrics, leaderboard, knowledge pipeline, built-in methods, investigation modes, session tracking — is approximately **80% of the Urika-specific work** and is **identical in all three options.**

The choice between Option A, Option B, and Option C is about whether you also build an agent runtime (~20% extra work, ~30% extra timeline). It is a real choice with real tradeoffs. But it is not a choice about what Urika IS. Urika is the analysis platform. The runtime is plumbing.

Choose the plumbing that lets you get to the analysis platform fastest.

---

## 9. Migration Path

Option C is the end-state option. You would typically arrive here after starting with Option A (Claude Agent SDK) or Option B (Pi) and hitting their limits.

### Why You Might Migrate

- **From Option A:** You need models beyond Claude. An institutional mandate requires GPT-4 or local models. Or Anthropic's SDK roadmap diverges from your needs. Or you hit a wall with Claude-specific assumptions baked into the SDK that conflict with your multi-agent orchestration.

- **From Option B:** The TypeScript/Python split creates too much friction. Debugging across the language boundary is painful. Or Pi's extension system is too constrained for your orchestration patterns. Or you need deeper control over the agent loop than Pi exposes.

- **From either:** You have validated the concept, you have real users, and you are ready to invest in a runtime that is perfectly tailored to Urika's needs with no compromises.

### What Transfers Directly

The `urika` Python package — data loading, methods, evaluation, metrics, leaderboard, knowledge pipeline, session tracking — transfers with **zero changes**. This is the 80% of the codebase that is identical across all three options. Agents still write `from urika.data import load_dataset` and `from urika.methods import LinearRegression`. Nothing about the analysis library depends on which runtime executes the agent loop.

### What You Replace

You replace only the orchestration layer:

| Component | From Option A | From Option B | To Option C |
|-----------|--------------|---------------|-------------|
| Agent loop | Claude Agent SDK's loop | Pi's agent loop | `urika/runtime/loop.py` |
| LLM calls | Claude Agent SDK's client | Pi's LLM providers | `urika/runtime/llm/` providers |
| Core tools | Claude Agent SDK's tools | Pi's built-in tools | `urika/runtime/tools/core/` |
| Session persistence | Claude Agent SDK's sessions | Pi's JSONL sessions | `urika/runtime/session/` |
| Security boundaries | SDK-level configuration | Pi extension hooks | Per-agent `ToolRegistry` construction |
| Multi-agent orchestration | Python code calling SDK | TypeScript extension | Python code calling `AgentLoop` |

### Migration Strategy

1. **Continue running on Option A or B** while building the custom runtime in parallel (Phase 1).
2. **Write the runtime against the same interfaces** your orchestrator already uses. If your orchestrator calls `agent.run(prompt)` and gets back a result, make the custom runtime's `AgentLoop` expose the same interface.
3. **Swap the runtime behind the orchestrator.** The orchestrator does not care whether `agent.run(prompt)` is backed by the Claude Agent SDK, Pi, or your custom `AgentLoop`. Change the wiring, run the same integration tests.
4. **The `urika` Python package does not change at all.** Agents still write and run the same Python scripts. The scripts import `urika` the same way. Only the thing that executes the agent loop changes.

### When to Migrate

Do not start with Option C. Start with Option A or B, validate the analysis platform, get real users running real investigations. Migrate to Option C when:

- You have a clear, specific limitation in Option A or B that Option C solves
- You have the engineering bandwidth to build and maintain a runtime (Phase 1: 4-6 weeks, ongoing: ~10-20% of development time)
- The analysis platform is stable enough that you can afford to spend weeks on infrastructure
- You have enough agent usage data to know exactly what your runtime needs to optimize for
