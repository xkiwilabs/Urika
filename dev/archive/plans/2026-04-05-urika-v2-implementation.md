# Urika v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a TypeScript TUI (pi-tui fork) with an LLM-driven adaptive orchestrator (pi-ai) that replaces the deterministic Python loop, while keeping the Python CLI and core modules intact.

**Architecture:** TypeScript process (pi-tui + orchestrator + pi-ai) communicates with a Python compute server (JSON-RPC over stdio). Python owns state + execution + data. TypeScript owns LLM calls + user interaction.

**Tech Stack:** TypeScript/Bun, pi-tui, pi-ai, pi-agent-core, JSON-RPC 2.0/stdio, Python 3.11+, Click CLI

**Reference Design:** `docs/plans/2026-04-05-urika-v2-architecture-design.md`

---

## Phase 1: Python JSON-RPC Server

The foundation. Expose existing core modules as RPC methods so the TS orchestrator can call them.

---

### Task 1: JSON-RPC Protocol Handler

**Files:**
- Create: `src/urika/rpc/__init__.py`
- Create: `src/urika/rpc/protocol.py`
- Test: `tests/test_rpc_protocol.py`

**Step 1: Write the failing test**

```python
# tests/test_rpc_protocol.py
"""Tests for JSON-RPC 2.0 protocol handler."""
import json
from urika.rpc.protocol import handle_request, RPCError


def test_valid_request_dispatches():
    """A valid JSON-RPC request dispatches to the registered method."""
    registry = {"echo": lambda params: params["msg"]}
    req = {"jsonrpc": "2.0", "id": 1, "method": "echo", "params": {"msg": "hello"}}
    resp = handle_request(json.dumps(req), registry)
    parsed = json.loads(resp)
    assert parsed["result"] == "hello"
    assert parsed["id"] == 1


def test_method_not_found():
    """Unknown method returns -32601 error."""
    registry = {}
    req = {"jsonrpc": "2.0", "id": 1, "method": "nope", "params": {}}
    resp = handle_request(json.dumps(req), registry)
    parsed = json.loads(resp)
    assert parsed["error"]["code"] == -32601


def test_invalid_json():
    """Malformed JSON returns -32700 parse error."""
    resp = handle_request("not json{", {})
    parsed = json.loads(resp)
    assert parsed["error"]["code"] == -32700


def test_method_exception_returns_error():
    """If the handler raises, return -32000 internal error."""
    def bad(params):
        raise ValueError("boom")
    registry = {"bad": bad}
    req = {"jsonrpc": "2.0", "id": 1, "method": "bad", "params": {}}
    resp = handle_request(json.dumps(req), registry)
    parsed = json.loads(resp)
    assert parsed["error"]["code"] == -32000
    assert "boom" in parsed["error"]["message"]


def test_notification_no_response():
    """A request without 'id' is a notification — no response."""
    registry = {"noop": lambda params: None}
    req = {"jsonrpc": "2.0", "method": "noop", "params": {}}
    resp = handle_request(json.dumps(req), registry)
    assert resp is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_rpc_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'urika.rpc'`

**Step 3: Write minimal implementation**

```python
# src/urika/rpc/__init__.py
"""JSON-RPC server for Urika compute backend."""

# src/urika/rpc/protocol.py
"""JSON-RPC 2.0 protocol handler."""
from __future__ import annotations

import json
from typing import Any, Callable

Registry = dict[str, Callable[[dict[str, Any]], Any]]


class RPCError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def handle_request(raw: str, registry: Registry) -> str | None:
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        return _error_response(None, -32700, f"Parse error: {e}")

    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    if method not in registry:
        if req_id is None:
            return None
        return _error_response(req_id, -32601, f"Method not found: {method}")

    try:
        result = registry[method](params)
    except Exception as e:
        if req_id is None:
            return None
        return _error_response(req_id, -32000, str(e))

    if req_id is None:
        return None
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error_response(req_id: int | None, code: int, message: str) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_rpc_protocol.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add src/urika/rpc/ tests/test_rpc_protocol.py
git commit -m "feat(rpc): add JSON-RPC 2.0 protocol handler"
```

---

### Task 2: RPC Method Registry — State Operations

**Files:**
- Create: `src/urika/rpc/methods.py`
- Test: `tests/test_rpc_methods.py`

**Step 1: Write the failing test**

```python
# tests/test_rpc_methods.py
"""Tests for RPC method wrappers over core modules."""
from pathlib import Path
from urika.rpc.methods import build_registry


def test_registry_has_expected_methods():
    """Registry contains all required RPC methods."""
    registry = build_registry()
    expected = [
        "project.load_config",
        "experiment.create",
        "experiment.list",
        "experiment.load",
        "progress.append_run",
        "progress.load",
        "progress.get_best_run",
        "session.start",
        "session.pause",
        "session.resume",
        "criteria.load",
        "criteria.append",
        "methods.register",
        "methods.list",
        "usage.record",
        "tools.list",
        "tools.run",
        "data.profile",
        "knowledge.ingest",
        "knowledge.search",
        "knowledge.list",
        "labbook.update_notes",
        "labbook.generate_summary",
        "report.results_summary",
        "report.key_findings",
        "code.execute",
    ]
    for method in expected:
        assert method in registry, f"Missing RPC method: {method}"


def test_experiment_create_via_rpc(tmp_path: Path):
    """Create an experiment through the RPC layer."""
    from urika.core.workspace import create_project_workspace
    from urika.rpc.methods import build_registry

    project_dir = tmp_path / "test-project"
    create_project_workspace(
        project_dir,
        name="test-project",
        question="Does X predict Y?",
        mode="exploratory",
    )
    registry = build_registry()
    result = registry["experiment.create"]({
        "project_dir": str(project_dir),
        "name": "baseline",
        "hypothesis": "Linear is enough",
    })
    assert result["experiment_id"].startswith("exp-")
    assert result["name"] == "baseline"


def test_experiment_list_via_rpc(tmp_path: Path):
    """List experiments through the RPC layer."""
    from urika.core.workspace import create_project_workspace
    from urika.core.experiment import create_experiment
    from urika.rpc.methods import build_registry

    project_dir = tmp_path / "test-project"
    create_project_workspace(
        project_dir,
        name="test-project",
        question="Does X predict Y?",
        mode="exploratory",
    )
    create_experiment(project_dir, name="exp1", hypothesis="h1")
    registry = build_registry()
    result = registry["experiment.list"]({"project_dir": str(project_dir)})
    assert len(result) == 1
    assert result[0]["name"] == "exp1"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_rpc_methods.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write minimal implementation**

```python
# src/urika/rpc/methods.py
"""RPC method registry — thin wrappers over existing core modules."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from urika.core.experiment import create_experiment, list_experiments, load_experiment
from urika.core.progress import append_run, get_best_run, load_progress
from urika.core.session import pause_session, resume_session, start_session
from urika.core.criteria import append_criteria, load_criteria
from urika.core.workspace import load_project_config
from urika.core.method_registry import load_methods, register_method
from urika.core.usage import record_session
from urika.core.labbook import (
    generate_experiment_summary,
    generate_key_findings,
    generate_results_summary,
    update_experiment_notes,
)
from urika.core.models import RunRecord
from urika.knowledge.store import KnowledgeStore
from urika.tools.registry import ToolRegistry

Registry = dict[str, Callable[[dict[str, Any]], Any]]


def _path(params: dict, key: str = "project_dir") -> Path:
    return Path(params[key])


def build_registry() -> Registry:
    """Build the full RPC method registry."""
    return {
        # -- State: project --
        "project.load_config": _project_load_config,
        # -- State: experiments --
        "experiment.create": _experiment_create,
        "experiment.list": _experiment_list,
        "experiment.load": _experiment_load,
        # -- State: progress --
        "progress.append_run": _progress_append_run,
        "progress.load": _progress_load,
        "progress.get_best_run": _progress_get_best_run,
        # -- State: session --
        "session.start": _session_start,
        "session.pause": _session_pause,
        "session.resume": _session_resume,
        # -- State: criteria --
        "criteria.load": _criteria_load,
        "criteria.append": _criteria_append,
        # -- State: methods --
        "methods.register": _methods_register,
        "methods.list": _methods_list,
        # -- State: usage --
        "usage.record": _usage_record,
        # -- Execution: tools --
        "tools.list": _tools_list,
        "tools.run": _tools_run,
        # -- Execution: code --
        "code.execute": _code_execute,
        # -- Data --
        "data.profile": _data_profile,
        # -- Knowledge --
        "knowledge.ingest": _knowledge_ingest,
        "knowledge.search": _knowledge_search,
        "knowledge.list": _knowledge_list,
        # -- Reports --
        "labbook.update_notes": _labbook_update_notes,
        "labbook.generate_summary": _labbook_generate_summary,
        "report.results_summary": _report_results_summary,
        "report.key_findings": _report_key_findings,
    }


# -- Implementation functions --

def _project_load_config(params: dict) -> dict:
    config = load_project_config(_path(params))
    return config.to_dict()


def _experiment_create(params: dict) -> dict:
    exp = create_experiment(
        _path(params),
        name=params["name"],
        hypothesis=params.get("hypothesis", ""),
        builds_on=params.get("builds_on"),
    )
    return exp.to_dict()


def _experiment_list(params: dict) -> list[dict]:
    return [e.to_dict() for e in list_experiments(_path(params))]


def _experiment_load(params: dict) -> dict:
    return load_experiment(_path(params), params["experiment_id"]).to_dict()


def _progress_append_run(params: dict) -> str:
    run = RunRecord(**params["run"])
    append_run(_path(params), params["experiment_id"], run)
    return "ok"


def _progress_load(params: dict) -> dict:
    return load_progress(_path(params), params["experiment_id"])


def _progress_get_best_run(params: dict) -> dict | None:
    return get_best_run(
        _path(params),
        params["experiment_id"],
        metric=params["metric"],
        direction=params["direction"],
    )


def _session_start(params: dict) -> dict:
    state = start_session(
        _path(params), params["experiment_id"],
        max_turns=params.get("max_turns"),
    )
    return state.to_dict()


def _session_pause(params: dict) -> dict:
    return pause_session(_path(params), params["experiment_id"]).to_dict()


def _session_resume(params: dict) -> dict:
    return resume_session(_path(params), params["experiment_id"]).to_dict()


def _criteria_load(params: dict) -> dict | None:
    cv = load_criteria(_path(params))
    return cv.to_dict() if cv else None


def _criteria_append(params: dict) -> dict:
    cv = append_criteria(
        _path(params),
        params["criteria"],
        set_by=params["set_by"],
        turn=params["turn"],
        rationale=params["rationale"],
    )
    return cv.to_dict()


def _methods_register(params: dict) -> str:
    register_method(
        _path(params),
        name=params["name"],
        description=params["description"],
        script=params["script"],
        experiment=params["experiment"],
        turn=params["turn"],
        metrics=params["metrics"],
        status=params.get("status", "active"),
    )
    return "ok"


def _methods_list(params: dict) -> list[dict]:
    return load_methods(_path(params))


def _usage_record(params: dict) -> str:
    p = dict(params)
    project_dir = _path(p)
    del p["project_dir"]
    record_session(project_dir, **p)
    return "ok"


def _tools_list(params: dict) -> list[str]:
    reg = ToolRegistry()
    reg.discover()
    if "project_dir" in params:
        tools_dir = _path(params) / "tools"
        if tools_dir.exists():
            reg.discover_project(tools_dir)
    return reg.list_all()


def _tools_run(params: dict) -> dict:
    from urika.data.loader import load_dataset

    reg = ToolRegistry()
    reg.discover()
    if "project_dir" in params:
        tools_dir = _path(params) / "tools"
        if tools_dir.exists():
            reg.discover_project(tools_dir)
    tool = reg.get(params["tool_name"])
    if tool is None:
        raise ValueError(f"Tool not found: {params['tool_name']}")
    data = load_dataset(Path(params["data_path"]))
    result = tool.run(data, params.get("params", {}))
    return {
        "outputs": result.outputs,
        "artifacts": result.artifacts,
        "metrics": result.metrics,
        "valid": result.valid,
        "error": result.error,
    }


def _code_execute(params: dict) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", params["code"]],
        capture_output=True,
        text=True,
        cwd=params.get("cwd"),
        timeout=params.get("timeout", 300),
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _data_profile(params: dict) -> dict:
    from urika.data.loader import load_dataset
    from urika.data.profiler import profile_dataset

    ds = load_dataset(Path(params["data_path"]))
    summary = profile_dataset(ds.df)
    return summary.to_dict()


def _knowledge_ingest(params: dict) -> dict:
    store = KnowledgeStore(_path(params))
    entry = store.ingest(params["source"], source_type=params.get("source_type"))
    return entry.to_dict()


def _knowledge_search(params: dict) -> list[dict]:
    store = KnowledgeStore(_path(params))
    return [e.to_dict() for e in store.search(params["query"])]


def _knowledge_list(params: dict) -> list[dict]:
    store = KnowledgeStore(_path(params))
    return [e.to_dict() for e in store.list_all()]


def _labbook_update_notes(params: dict) -> str:
    update_experiment_notes(_path(params), params["experiment_id"])
    return "ok"


def _labbook_generate_summary(params: dict) -> str:
    generate_experiment_summary(_path(params), params["experiment_id"])
    return "ok"


def _report_results_summary(params: dict) -> str:
    generate_results_summary(_path(params))
    return "ok"


def _report_key_findings(params: dict) -> str:
    generate_key_findings(_path(params))
    return "ok"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_rpc_methods.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/urika/rpc/methods.py tests/test_rpc_methods.py
git commit -m "feat(rpc): add method registry wrapping all core modules"
```

---

### Task 3: RPC Server Main Loop (stdio)

**Files:**
- Create: `src/urika/rpc/server.py`
- Create: `src/urika/rpc/__main__.py`
- Test: `tests/test_rpc_server.py`

**Step 1: Write the failing test**

```python
# tests/test_rpc_server.py
"""Tests for the stdio JSON-RPC server."""
import json
import subprocess
import sys


def test_server_responds_to_request():
    """Server reads JSON-RPC from stdin, writes response to stdout."""
    req = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools.list", "params": {},
    })
    proc = subprocess.run(
        [sys.executable, "-m", "urika.rpc"],
        input=req + "\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    resp = json.loads(proc.stdout.strip())
    assert "result" in resp
    assert isinstance(resp["result"], list)


def test_server_handles_multiple_requests():
    """Server processes multiple newline-delimited requests."""
    reqs = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools.list", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools.list", "params": {}}),
    ]) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "urika.rpc"],
        input=reqs,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = [l for l in proc.stdout.strip().split("\n") if l]
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "result" in parsed
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_rpc_server.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# src/urika/rpc/server.py
"""Stdio JSON-RPC server for Urika compute backend."""
from __future__ import annotations

import sys

from urika.rpc.methods import build_registry
from urika.rpc.protocol import handle_request


def run_server() -> None:
    """Read JSON-RPC requests from stdin, write responses to stdout."""
    registry = build_registry()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = handle_request(line, registry)
        if response is not None:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()


# src/urika/rpc/__main__.py
"""Allow running as: python -m urika.rpc"""
from urika.rpc.server import run_server

run_server()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_rpc_server.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/urika/rpc/server.py src/urika/rpc/__main__.py tests/test_rpc_server.py
git commit -m "feat(rpc): add stdio JSON-RPC server with __main__ entry point"
```

---

### Task 4: Verify all existing tests still pass

**Step 1: Run full test suite**

Run: `pytest -v`
Expected: All 1100+ tests PASS. The RPC server is purely additive.

**Step 2: Run linter**

Run: `ruff check src/urika/rpc/ tests/test_rpc_protocol.py tests/test_rpc_methods.py tests/test_rpc_server.py`
Expected: No errors

**Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint fixes for rpc module"
```

---

## Phase 2: TypeScript Scaffolding

Set up the tui/ package, fork pi-tui, build the RPC client, prompt loader, and config loader.

---

### Task 5: Initialize TypeScript Package

**Files:**
- Create: `tui/package.json`
- Create: `tui/tsconfig.json`
- Create: `tui/.gitignore`
- Create: `tui/src/index.ts`

**Step 1: Create package.json**

```json
{
  "name": "urika-tui",
  "version": "0.1.0",
  "type": "module",
  "main": "src/index.ts",
  "scripts": {
    "dev": "bun run src/index.ts",
    "build": "bun build --compile --target=bun src/index.ts --outfile dist/urika-tui",
    "test": "bun test"
  },
  "dependencies": {
    "@mariozechner/pi-ai": "latest",
    "@mariozechner/pi-agent-core": "latest",
    "chalk": "^5.5.0",
    "marked": "^15.0.0"
  },
  "devDependencies": {
    "@types/bun": "latest",
    "typescript": "^5.7.0"
  }
}
```

**Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "outDir": "dist",
    "rootDir": "src",
    "declaration": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*"]
}
```

**Step 3: Create .gitignore**

```
node_modules/
dist/
*.tsbuildinfo
```

**Step 4: Create entry point stub**

```typescript
// tui/src/index.ts
/**
 * Urika TUI — Terminal UI + Adaptive Orchestrator
 *
 * Two modes:
 *   --interactive (default): pi-tui with conversational orchestrator
 *   --headless: stdout JSON events, no TUI
 */

const args = process.argv.slice(2);
const headless = args.includes("--headless");

if (headless) {
  console.log(JSON.stringify({ event: "started", mode: "headless" }));
} else {
  console.log("Urika TUI — not yet implemented");
}

process.exit(0);
```

**Step 5: Install dependencies and verify**

Run:
```bash
cd tui && bun install && bun run dev
```
Expected: Prints "Urika TUI -- not yet implemented" and exits

**Step 6: Commit**

```bash
git add tui/
git commit -m "feat(tui): initialize TypeScript package with pi-ai dependencies"
```

---

### Task 6: JSON-RPC Client

**Files:**
- Create: `tui/src/rpc/client.ts`
- Create: `tui/src/rpc/types.ts`
- Test: `tui/tests/rpc-client.test.ts`

**Step 1: Write the failing test**

```typescript
// tui/tests/rpc-client.test.ts
import { describe, expect, it } from "bun:test";
import { RpcClient } from "../src/rpc/client";

describe("RpcClient", () => {
  it("sends request and receives response from Python server", async () => {
    const client = new RpcClient("python", ["-m", "urika.rpc"]);
    try {
      const result = await client.call("tools.list", {});
      expect(Array.isArray(result)).toBe(true);
    } finally {
      client.close();
    }
  });

  it("handles method not found error", async () => {
    const client = new RpcClient("python", ["-m", "urika.rpc"]);
    try {
      await client.call("nonexistent.method", {});
      expect(true).toBe(false); // should not reach
    } catch (e: any) {
      expect(e.code).toBe(-32601);
    } finally {
      client.close();
    }
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd tui && bun test`
Expected: FAIL — module not found

**Step 3: Write implementation**

```typescript
// tui/src/rpc/types.ts
export interface RpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params: Record<string, unknown>;
}

export interface RpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

export class RpcError extends Error {
  code: number;
  constructor(code: number, message: string) {
    super(message);
    this.code = code;
  }
}
```

```typescript
// tui/src/rpc/client.ts
import { spawn, type ChildProcess } from "child_process";
import { createInterface, type Interface } from "readline";
import type { RpcRequest, RpcResponse } from "./types";
import { RpcError } from "./types";

export class RpcClient {
  private process: ChildProcess;
  private readline: Interface;
  private nextId = 1;
  private pending = new Map<number, {
    resolve: (value: unknown) => void;
    reject: (error: RpcError) => void;
  }>();

  constructor(command: string, args: string[]) {
    this.process = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.readline = createInterface({ input: this.process.stdout! });
    this.readline.on("line", (line: string) => {
      if (!line.trim()) return;
      const resp: RpcResponse = JSON.parse(line);
      const handler = this.pending.get(resp.id);
      if (!handler) return;
      this.pending.delete(resp.id);
      if (resp.error) {
        handler.reject(new RpcError(resp.error.code, resp.error.message));
      } else {
        handler.resolve(resp.result);
      }
    });
  }

  async call(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextId++;
    const req: RpcRequest = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin!.write(JSON.stringify(req) + "\n");
    });
  }

  close(): void {
    this.process.stdin!.end();
    this.readline.close();
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd tui && bun test`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add tui/src/rpc/ tui/tests/
git commit -m "feat(tui): add JSON-RPC client for Python compute server"
```

---

### Task 7: Config Loader

**Files:**
- Create: `tui/src/config/loader.ts`
- Create: `tui/src/config/types.ts`
- Test: `tui/tests/config-loader.test.ts`

**Step 1: Write the failing test**

```typescript
// tui/tests/config-loader.test.ts
import { describe, expect, it } from "bun:test";
import { loadUrikaConfig } from "../src/config/loader";
import { mkdtempSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

describe("loadUrikaConfig", () => {
  it("loads model config from urika.toml", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-test-"));
    writeFileSync(join(dir, "urika.toml"), `
[project]
name = "test"
question = "Does X?"
mode = "exploratory"

[runtime]
default_model = "anthropic/claude-sonnet-4-6"

[runtime.models]
evaluator = "anthropic/claude-haiku-4-5"
data_agent = "ollama/qwen3:14b"
`);
    const config = loadUrikaConfig(dir);
    expect(config.defaultModel).toBe("anthropic/claude-sonnet-4-6");
    expect(config.models.evaluator).toBe("anthropic/claude-haiku-4-5");
    expect(config.models.data_agent).toBe("ollama/qwen3:14b");
  });

  it("returns defaults when runtime section missing", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-test-"));
    writeFileSync(join(dir, "urika.toml"), `
[project]
name = "test"
question = "Does X?"
mode = "exploratory"
`);
    const config = loadUrikaConfig(dir);
    expect(config.defaultModel).toBe("anthropic/claude-sonnet-4-6");
    expect(Object.keys(config.models)).toHaveLength(0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd tui && bun test`
Expected: FAIL

**Step 3: Write implementation**

Note: Bun has built-in TOML support. Use a simple TOML parser or Bun's native parsing.

```typescript
// tui/src/config/types.ts
export interface UrikaConfig {
  projectName: string;
  question: string;
  mode: string;
  defaultModel: string;
  models: Record<string, string>;
  privacyMode: string;
  localRoles: string[];
}

// tui/src/config/loader.ts
import { readFileSync } from "fs";
import { join } from "path";
import type { UrikaConfig } from "./types";

// Minimal TOML parser for the sections we need.
// For production, use a proper TOML library. Bun can also import TOML natively.
export function loadUrikaConfig(projectDir: string): UrikaConfig {
  const raw = readFileSync(join(projectDir, "urika.toml"), "utf-8");

  // Use Bun's built-in TOML support if available, else basic parsing
  let parsed: any;
  try {
    // Bun natively supports TOML imports but not dynamic parsing yet.
    // Use a simple section parser.
    parsed = parseTOML(raw);
  } catch {
    parsed = {};
  }

  const project = parsed.project ?? {};
  const runtime = parsed.runtime ?? {};
  const models = runtime.models ?? {};
  const privacy = parsed.privacy ?? {};

  return {
    projectName: project.name ?? "",
    question: project.question ?? "",
    mode: project.mode ?? "exploratory",
    defaultModel: runtime.default_model ?? "anthropic/claude-sonnet-4-6",
    models: models as Record<string, string>,
    privacyMode: privacy.mode ?? "open",
    localRoles: privacy.local_roles ?? [],
  };
}

/** Minimal TOML parser — handles flat tables and key=value pairs. */
function parseTOML(raw: string): Record<string, any> {
  const result: Record<string, any> = {};
  let currentSection: string[] = [];

  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    // Section header: [foo] or [foo.bar]
    const sectionMatch = trimmed.match(/^\[([^\]]+)\]$/);
    if (sectionMatch) {
      currentSection = sectionMatch[1].split(".");
      // Ensure nested structure exists
      let obj = result;
      for (const key of currentSection) {
        if (!(key in obj)) obj[key] = {};
        obj = obj[key];
      }
      continue;
    }

    // Key = value
    const kvMatch = trimmed.match(/^(\w+)\s*=\s*(.+)$/);
    if (kvMatch) {
      const [, key, rawVal] = kvMatch;
      const val = parseValue(rawVal.trim());
      let obj = result;
      for (const sec of currentSection) {
        obj = obj[sec];
      }
      obj[key] = val;
    }
  }
  return result;
}

function parseValue(raw: string): any {
  if (raw.startsWith('"') && raw.endsWith('"')) return raw.slice(1, -1);
  if (raw.startsWith("'") && raw.endsWith("'")) return raw.slice(1, -1);
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (raw.startsWith("[")) {
    // Simple array parsing
    const inner = raw.slice(1, -1).trim();
    if (!inner) return [];
    return inner.split(",").map((s) => parseValue(s.trim()));
  }
  const num = Number(raw);
  if (!isNaN(num)) return num;
  return raw;
}
```

**Step 4: Run test to verify it passes**

Run: `cd tui && bun test`
Expected: PASS

**Step 5: Commit**

```bash
git add tui/src/config/ tui/tests/config-loader.test.ts
git commit -m "feat(tui): add config loader for urika.toml model routing"
```

---

### Task 8: Prompt Template Loader

**Files:**
- Create: `tui/src/orchestrator/prompt-loader.ts`
- Test: `tui/tests/prompt-loader.test.ts`

**Step 1: Write the failing test**

```typescript
// tui/tests/prompt-loader.test.ts
import { describe, expect, it } from "bun:test";
import { loadPrompt, listPromptFiles } from "../src/orchestrator/prompt-loader";
import { mkdtempSync, mkdirSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

describe("loadPrompt", () => {
  it("loads and substitutes variables in a prompt template", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompt-"));
    writeFileSync(join(dir, "test.md"), "Analyze data in {project_dir} for experiment {experiment_id}.");
    const result = loadPrompt(join(dir, "test.md"), {
      project_dir: "/tmp/my-project",
      experiment_id: "exp-001",
    });
    expect(result).toBe("Analyze data in /tmp/my-project for experiment exp-001.");
  });

  it("leaves unknown variables as-is", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompt-"));
    writeFileSync(join(dir, "test.md"), "Hello {name}, today is {date}.");
    const result = loadPrompt(join(dir, "test.md"), { name: "Mike" });
    expect(result).toBe("Hello Mike, today is {date}.");
  });
});

describe("listPromptFiles", () => {
  it("lists all .md files in a prompts directory", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompts-"));
    writeFileSync(join(dir, "task_agent_system.md"), "task prompt");
    writeFileSync(join(dir, "evaluator_system.md"), "eval prompt");
    const files = listPromptFiles(dir);
    expect(files).toContain("task_agent_system.md");
    expect(files).toContain("evaluator_system.md");
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd tui && bun test`
Expected: FAIL

**Step 3: Write implementation**

```typescript
// tui/src/orchestrator/prompt-loader.ts
import { readFileSync, readdirSync } from "fs";

/**
 * Load a prompt template and substitute {variables}.
 * Unknown variables are left as-is (matching Python's behavior).
 */
export function loadPrompt(
  filePath: string,
  variables: Record<string, string> = {},
): string {
  let content = readFileSync(filePath, "utf-8");
  for (const [key, value] of Object.entries(variables)) {
    content = content.replaceAll(`{${key}}`, value);
  }
  return content;
}

/**
 * List all .md prompt files in a directory.
 */
export function listPromptFiles(promptsDir: string): string[] {
  return readdirSync(promptsDir).filter((f) => f.endsWith(".md")).sort();
}
```

**Step 4: Run test to verify it passes**

Run: `cd tui && bun test`
Expected: PASS

**Step 5: Commit**

```bash
git add tui/src/orchestrator/prompt-loader.ts tui/tests/prompt-loader.test.ts
git commit -m "feat(tui): add prompt template loader for agent .md files"
```

---

## Phase 3: Orchestrator

Build the LLM-driven orchestrator with agents-as-tools.

---

### Task 9: Agent Tool Definitions

**Files:**
- Create: `tui/src/orchestrator/agent-tools.ts`
- Test: `tui/tests/agent-tools.test.ts`

This task defines each agent role as a tool the orchestrator LLM can call. Each tool:
1. Reads the agent's .md prompt template
2. Substitutes project context variables
3. Calls pi-ai `streamSimple()` with the configured model
4. Returns the agent's text output

**Step 1: Write the failing test**

```typescript
// tui/tests/agent-tools.test.ts
import { describe, expect, it } from "bun:test";
import { buildAgentTools, AGENT_ROLES } from "../src/orchestrator/agent-tools";

describe("buildAgentTools", () => {
  it("creates a tool definition for each agent role", () => {
    const tools = buildAgentTools({
      promptsDir: "src/urika/agents/roles/prompts",
      projectDir: "/tmp/test",
      experimentId: "exp-001",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
    });
    // Should have one tool per role (excluding orchestrator itself)
    expect(tools.length).toBeGreaterThanOrEqual(8);
    const names = tools.map((t) => t.name);
    expect(names).toContain("planning_agent");
    expect(names).toContain("task_agent");
    expect(names).toContain("evaluator");
    expect(names).toContain("advisor");
  });

  it("each tool has name, description, and execute function", () => {
    const tools = buildAgentTools({
      promptsDir: "src/urika/agents/roles/prompts",
      projectDir: "/tmp/test",
      experimentId: "exp-001",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
    });
    for (const tool of tools) {
      expect(typeof tool.name).toBe("string");
      expect(typeof tool.description).toBe("string");
      expect(typeof tool.execute).toBe("function");
    }
  });
});

describe("AGENT_ROLES", () => {
  it("maps role names to prompt filenames", () => {
    expect(AGENT_ROLES.planning_agent).toBe("planning_agent_system.md");
    expect(AGENT_ROLES.task_agent).toBe("task_agent_system.md");
    expect(AGENT_ROLES.evaluator).toBe("evaluator_system.md");
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd tui && bun test`
Expected: FAIL

**Step 3: Write implementation**

```typescript
// tui/src/orchestrator/agent-tools.ts
import { loadPrompt } from "./prompt-loader";
import { join } from "path";

/** Maps agent role name to prompt template filename. */
export const AGENT_ROLES: Record<string, string> = {
  planning_agent: "planning_agent_system.md",
  task_agent: "task_agent_system.md",
  evaluator: "evaluator_system.md",
  advisor: "advisor_agent_system.md",
  tool_builder: "tool_builder_system.md",
  literature_agent: "literature_agent_system.md",
  data_agent: "data_agent_system.md",
  report_agent: "report_agent_system.md",
};

/** Role descriptions for the orchestrator to understand what each agent does. */
const ROLE_DESCRIPTIONS: Record<string, string> = {
  planning_agent:
    "Designs the analytical method pipeline. Call when starting a new approach or when strategy needs to change.",
  task_agent:
    "Executes experiments by writing and running Python code. Call after planning_agent produces a method plan.",
  evaluator:
    "Scores results against project success criteria. Read-only. Call after task_agent completes a run.",
  advisor:
    "Analyzes all results so far and proposes the next experiment or declares completion. Call after evaluator.",
  tool_builder:
    "Creates custom analysis tools for the project. Call when a needed tool doesn't exist.",
  literature_agent:
    "Searches the project knowledge base for relevant papers and notes. Call when domain context is needed.",
  data_agent:
    "Extracts and prepares features from raw data in privacy-preserving mode. Call in hybrid/private mode before task_agent.",
  report_agent:
    "Writes experiment narratives and summaries. Call after experiments complete.",
};

export interface AgentToolConfig {
  promptsDir: string;
  projectDir: string;
  experimentId: string;
  defaultModel: string;
  modelOverrides: Record<string, string>;
}

export interface AgentTool {
  name: string;
  description: string;
  model: string;
  systemPrompt: string;
  execute: (input: string) => Promise<string>;
}

/**
 * Build agent tool definitions for the orchestrator.
 * Each tool wraps an agent role: loads its prompt, resolves its model,
 * and provides an execute function that calls pi-ai.
 */
export function buildAgentTools(config: AgentToolConfig): AgentTool[] {
  const tools: AgentTool[] = [];

  for (const [role, promptFile] of Object.entries(AGENT_ROLES)) {
    const promptPath = join(config.promptsDir, promptFile);
    let systemPrompt: string;
    try {
      systemPrompt = loadPrompt(promptPath, {
        project_dir: config.projectDir,
        experiment_id: config.experimentId,
      });
    } catch {
      // Prompt file may not exist in test environments
      systemPrompt = `You are the ${role}.`;
    }

    const model = config.modelOverrides[role] ?? config.defaultModel;

    tools.push({
      name: role,
      description: ROLE_DESCRIPTIONS[role] ?? `Run the ${role} agent.`,
      model,
      systemPrompt,
      execute: async (input: string): Promise<string> => {
        // Phase 3 will wire this to pi-ai streamSimple()
        // For now, placeholder that will be replaced
        throw new Error(`Agent execution not yet wired: ${role}`);
      },
    });
  }

  return tools;
}
```

**Step 4: Run test to verify it passes**

Run: `cd tui && bun test`
Expected: PASS

**Step 5: Commit**

```bash
git add tui/src/orchestrator/agent-tools.ts tui/tests/agent-tools.test.ts
git commit -m "feat(tui): add agent tool definitions for orchestrator"
```

---

### Task 10: Orchestrator System Prompt

**Files:**
- Create: `tui/src/orchestrator/system-prompt.ts`
- Create: `src/urika/agents/roles/prompts/orchestrator_system.md`

**Step 1: Create the orchestrator system prompt template**

This is the most important prompt in the system. It tells the orchestrator LLM how to behave.

```markdown
# src/urika/agents/roles/prompts/orchestrator_system.md

You are the Urika Orchestrator — an AI research coordinator managing a scientific analysis project.

## Project Context
- **Project**: {project_name}
- **Research question**: {question}
- **Mode**: {mode}
- **Data**: {data_dir}
- **Current experiment**: {experiment_id}

## Your Role

You coordinate a team of specialist agents to answer the research question. You decide which agent to call, when, and with what instructions. You also talk directly to the user — answering questions, explaining decisions, and taking steering input.

## Available Agent Tools

You have the following agents available as tools:

- **planning_agent**: Designs the analytical method pipeline. Call when starting a new approach.
- **task_agent**: Executes experiments by writing and running Python code. Call after planning.
- **evaluator**: Scores results against success criteria. ALWAYS call after task_agent completes.
- **advisor**: Analyzes results and proposes next steps. Call after evaluator.
- **tool_builder**: Creates custom analysis tools. Call when a needed tool doesn't exist.
- **literature_agent**: Searches knowledge base for relevant research. Call when domain context is needed.
- **data_agent**: Extracts features in privacy-preserving mode. Call in hybrid/private mode before task_agent.
- **report_agent**: Writes experiment narratives. Call when experiments complete.

## Available State Tools

- **create_experiment**: Create a new experiment
- **append_run**: Record a run result
- **load_progress**: Read experiment progress
- **get_best_run**: Find the best result by metric
- **load_criteria**: Read current success criteria
- **finalize_project**: Run the finalize pipeline (finalizer -> report -> presentation -> README)

## Standard Protocol

The default experiment workflow is:

1. **planning_agent** — design the method
2. **data_agent** — extract features (hybrid/private mode only)
3. **task_agent** — execute the experiment
4. **evaluator** — score against criteria (NEVER skip this)
5. **advisor** — propose next steps or declare completion

Follow this sequence by default. You MAY deviate when it makes sense:
- Skip planning_agent if repeating a method with different parameters
- Call tool_builder if the evaluator identifies a missing capability
- Call literature_agent if the advisor suggests domain knowledge would help
- Run multiple task_agent calls with different approaches before evaluating
- Go directly to finalize_project if criteria are met and the user approves

## Rules

1. **NEVER skip the evaluator** after task_agent completes a run
2. **Respect user steering** — if the user says "try X", do X
3. **Explain your decisions** — briefly say what you're doing and why before calling an agent
4. **Track progress** — call append_run after each task_agent execution to record results
5. **Be adaptive** — if an approach isn't working after 2-3 attempts, change strategy
6. **Ask the user** when genuinely uncertain about direction, not when you can make a reasonable judgment

## Current State

{current_state}
```

**Step 2: Create the TS module that builds the prompt**

```typescript
// tui/src/orchestrator/system-prompt.ts
import { loadPrompt } from "./prompt-loader";
import { join } from "path";

export interface OrchestratorContext {
  promptsDir: string;
  projectName: string;
  question: string;
  mode: string;
  dataDir: string;
  experimentId: string;
  currentState: string;
}

/**
 * Load and populate the orchestrator's system prompt.
 */
export function buildOrchestratorPrompt(ctx: OrchestratorContext): string {
  return loadPrompt(join(ctx.promptsDir, "orchestrator_system.md"), {
    project_name: ctx.projectName,
    question: ctx.question,
    mode: ctx.mode,
    data_dir: ctx.dataDir,
    experiment_id: ctx.experimentId,
    current_state: ctx.currentState,
  });
}
```

**Step 3: Commit**

```bash
git add src/urika/agents/roles/prompts/orchestrator_system.md tui/src/orchestrator/system-prompt.ts
git commit -m "feat: add orchestrator system prompt template and loader"
```

---

### Task 11: Wire Orchestrator to pi-ai

**Files:**
- Create: `tui/src/orchestrator/orchestrator.ts`
- Test: `tui/tests/orchestrator.test.ts`

This is the core orchestrator — an LLM agent with agents-as-tools via pi-ai. This task wires the agent tool definitions to actual pi-ai `streamSimple()` calls.

**Note:** Full integration testing requires API keys. Unit tests verify structure; integration tests are manual.

**Step 1: Write the structural test**

```typescript
// tui/tests/orchestrator.test.ts
import { describe, expect, it } from "bun:test";
import { Orchestrator } from "../src/orchestrator/orchestrator";

describe("Orchestrator", () => {
  it("can be constructed with config", () => {
    const orch = new Orchestrator({
      projectDir: "/tmp/test",
      promptsDir: "src/urika/agents/roles/prompts",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
      pythonCommand: "python",
    });
    expect(orch).toBeDefined();
  });

  it("has agent tools registered", () => {
    const orch = new Orchestrator({
      projectDir: "/tmp/test",
      promptsDir: "src/urika/agents/roles/prompts",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
      pythonCommand: "python",
    });
    const toolNames = orch.getToolNames();
    expect(toolNames).toContain("planning_agent");
    expect(toolNames).toContain("task_agent");
    expect(toolNames).toContain("evaluator");
  });
});
```

**Step 2: Write implementation**

```typescript
// tui/src/orchestrator/orchestrator.ts
import { buildAgentTools, type AgentTool } from "./agent-tools";
import { buildOrchestratorPrompt } from "./system-prompt";
import { RpcClient } from "../rpc/client";
import type { UrikaConfig } from "../config/types";

export interface OrchestratorConfig {
  projectDir: string;
  promptsDir: string;
  defaultModel: string;
  modelOverrides: Record<string, string>;
  pythonCommand: string;
}

export interface OrchestratorEvents {
  onAgentStart?: (agent: string) => void;
  onAgentOutput?: (agent: string, text: string) => void;
  onAgentEnd?: (agent: string) => void;
  onStatusUpdate?: (status: string) => void;
  onError?: (error: string) => void;
}

/**
 * The adaptive orchestrator. Uses pi-ai to run an LLM that decides
 * which agents to call, in what order, based on project state and
 * user input.
 */
export class Orchestrator {
  private agentTools: AgentTool[];
  private config: OrchestratorConfig;
  private rpcClient: RpcClient | null = null;
  private events: OrchestratorEvents = {};

  constructor(config: OrchestratorConfig) {
    this.config = config;
    this.agentTools = buildAgentTools({
      promptsDir: config.promptsDir,
      projectDir: config.projectDir,
      experimentId: "", // Set per-run
      defaultModel: config.defaultModel,
      modelOverrides: config.modelOverrides,
    });
  }

  getToolNames(): string[] {
    return this.agentTools.map((t) => t.name);
  }

  setEvents(events: OrchestratorEvents): void {
    this.events = events;
  }

  /**
   * Start the Python RPC server and connect.
   */
  async connect(): Promise<void> {
    this.rpcClient = new RpcClient(this.config.pythonCommand, ["-m", "urika.rpc"]);
  }

  /**
   * Run a conversation turn: send user message to orchestrator LLM,
   * let it decide what agents to call.
   *
   * This is the main entry point. The orchestrator LLM receives:
   * - Its system prompt (with project context)
   * - The conversation history
   * - The user's message
   *
   * It responds with text and/or tool calls (agent invocations).
   * Tool calls are executed, results fed back, until the LLM
   * responds with text only (no more tool calls).
   */
  async processMessage(userMessage: string): Promise<string> {
    // TODO: Phase 3 full implementation
    // 1. Build orchestrator system prompt with current state
    // 2. Add user message to conversation history
    // 3. Call pi-ai streamSimple() with orchestrator model
    // 4. Process tool calls (agent invocations)
    // 5. Feed results back to orchestrator
    // 6. Repeat until orchestrator responds with text only
    // 7. Return final text response
    throw new Error("Orchestrator not yet fully wired to pi-ai");
  }

  /**
   * Disconnect from Python RPC server.
   */
  close(): void {
    this.rpcClient?.close();
  }
}
```

**Step 3: Run test to verify it passes**

Run: `cd tui && bun test`
Expected: PASS (structural tests only — no LLM calls)

**Step 4: Commit**

```bash
git add tui/src/orchestrator/orchestrator.ts tui/tests/orchestrator.test.ts
git commit -m "feat(tui): add orchestrator class with agent tools and RPC client"
```

---

### Task 12: Wire Agent Execution to pi-ai

**Files:**
- Modify: `tui/src/orchestrator/agent-tools.ts`
- Modify: `tui/src/orchestrator/orchestrator.ts`

This task replaces the placeholder `execute` functions with actual pi-ai calls. This requires `@mariozechner/pi-ai` to be installed.

**Step 1: Update agent-tools.ts execute function**

Replace the `execute` placeholder in `buildAgentTools` with:

```typescript
// In agent-tools.ts, update the execute function:
import { streamSimple, getModel } from "@mariozechner/pi-ai";

// Inside buildAgentTools, replace the execute function:
execute: async (input: string): Promise<string> => {
  const [provider, modelId] = model.includes("/")
    ? model.split("/", 2)
    : ["anthropic", model];
  
  const aiModel = getModel(provider, modelId);
  const stream = streamSimple(aiModel, {
    messages: [
      { role: "user", content: input },
    ],
    systemPrompt,
    tools: [], // Agent-specific tools added per role
  });

  let output = "";
  for await (const event of stream) {
    if (event.type === "text_delta") {
      output += event.text;
      config.onTextDelta?.(role, event.text);
    }
  }
  return output;
},
```

**Step 2: Update orchestrator.ts processMessage**

Wire the full orchestrator loop using pi-ai. The orchestrator LLM gets all agent tools as callable functions. When it calls a tool, we execute the corresponding agent, then feed the result back.

This is the most complex piece — the exact implementation depends on pi-ai's tool calling API. The pattern follows Pi's own `agentLoop()`:

1. Send user message + system prompt to orchestrator LLM
2. If LLM returns tool calls → execute each agent tool → feed results back
3. Repeat until LLM returns text without tool calls
4. Return the text response

**Step 3: Commit**

```bash
git add tui/src/orchestrator/
git commit -m "feat(tui): wire agent execution to pi-ai streamSimple"
```

---

## Phase 3.5: Pi-TUI Fork & Integration

---

### Task 13: Fork pi-tui Components

**Step 1: Copy pi-tui source files**

Clone or download the pi-tui package from `@mariozechner/pi-tui` and copy the source files into `tui/src/tui/pi-tui/`:

```
tui/src/tui/pi-tui/
  tui.ts
  terminal.ts
  editor.ts
  markdown.ts
  keys.ts
  utils.ts
  stdin-buffer.ts
  keybindings.ts
  autocomplete.ts
  kill-ring.ts
  undo-stack.ts
  components/
    box.ts
    text.ts
    input.ts
    select-list.ts
    loader.ts
    cancellable-loader.ts
    image.ts
    spacer.ts
    truncated-text.ts
    settings-list.ts
```

**Step 2: Add THIRD-PARTY-LICENSES file**

```
tui/THIRD-PARTY-LICENSES

pi-tui
Copyright (c) 2025 Mario Zechner
MIT License
https://github.com/badlogic/pi-mono

[Full MIT license text]
```

**Step 3: Verify it compiles**

Run: `cd tui && bun run build`
Expected: Compiles without errors

**Step 4: Commit**

```bash
git add tui/src/tui/pi-tui/ tui/THIRD-PARTY-LICENSES
git commit -m "feat(tui): fork pi-tui components (MIT license)"
```

---

### Task 14: Urika TUI App (Customization Layer)

**Files:**
- Create: `tui/src/tui/app.ts`
- Create: `tui/src/tui/agent-display.ts`
- Create: `tui/src/tui/commands.ts`
- Create: `tui/src/tui/status-bar.ts`

**Step 1: Build the Urika-customized TUI app**

This wraps pi-tui with Urika-specific components: agent color labels, status bar, slash commands, and branding.

```typescript
// tui/src/tui/status-bar.ts
import chalk from "chalk";

export interface StatusBarState {
  project: string;
  experimentId: string;
  turn: number;
  agent: string;
  model: string;
  tokens: number;
  cost: number;
  elapsed: number;
}

export function renderStatusBar(state: StatusBarState): string {
  const parts = [
    chalk.cyan(state.experimentId || "no experiment"),
    chalk.white(`turn ${state.turn}`),
    chalk.yellow(state.model),
    chalk.green(`$${state.cost.toFixed(2)}`),
    chalk.dim(`${Math.floor(state.elapsed / 1000)}s`),
  ];
  return parts.join(chalk.dim(" | "));
}
```

```typescript
// tui/src/tui/agent-display.ts
import chalk from "chalk";

const AGENT_COLORS: Record<string, (s: string) => string> = {
  planning_agent: chalk.cyan,
  task_agent: chalk.green,
  evaluator: chalk.yellow,
  advisor: chalk.magenta,
  tool_builder: chalk.hex("#FF8C00"),
  literature_agent: chalk.blueBright,
  report_agent: chalk.white,
  presentation_agent: chalk.greenBright,
  data_agent: chalk.cyanBright,
  finalizer: chalk.magentaBright,
  orchestrator: chalk.bold.white,
};

export function formatAgentLabel(role: string): string {
  const colorFn = AGENT_COLORS[role] ?? chalk.white;
  return colorFn(`> ${role.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}`);
}
```

```typescript
// tui/src/tui/commands.ts
import type { RpcClient } from "../rpc/client";

export interface SlashCommand {
  name: string;
  description: string;
  execute: (args: string, rpc: RpcClient, projectDir: string) => Promise<string>;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "status",
    description: "Show project/experiment status",
    execute: async (args, rpc, projectDir) => {
      const config = await rpc.call("project.load_config", { project_dir: projectDir });
      return JSON.stringify(config, null, 2);
    },
  },
  {
    name: "results",
    description: "Show experiment results",
    execute: async (args, rpc, projectDir) => {
      const experiments = await rpc.call("experiment.list", { project_dir: projectDir }) as any[];
      if (experiments.length === 0) return "No experiments yet.";
      const lastExp = experiments[experiments.length - 1];
      const progress = await rpc.call("progress.load", {
        project_dir: projectDir,
        experiment_id: lastExp.experiment_id,
      });
      return JSON.stringify(progress, null, 2);
    },
  },
  {
    name: "pause",
    description: "Pause current run",
    execute: async () => {
      // Signal the orchestrator to pause
      return "Pause requested.";
    },
  },
  {
    name: "stop",
    description: "Stop current run",
    execute: async () => {
      return "Stop requested.";
    },
  },
  {
    name: "quit",
    description: "Exit Urika TUI",
    execute: async () => {
      process.exit(0);
    },
  },
];
```

**Step 2: Commit**

```bash
git add tui/src/tui/
git commit -m "feat(tui): add Urika customization layer — status bar, agent display, slash commands"
```

---

### Task 15: Wire TUI to Orchestrator

**Files:**
- Modify: `tui/src/index.ts`

**Step 1: Update entry point to launch TUI + orchestrator**

```typescript
// tui/src/index.ts
import { Orchestrator } from "./orchestrator/orchestrator";
import { loadUrikaConfig } from "./config/loader";
import { resolve } from "path";

const args = process.argv.slice(2);
const headless = args.includes("--headless");
const projectDir = args.find((a) => !a.startsWith("--")) ?? process.cwd();

async function main() {
  const config = loadUrikaConfig(projectDir);
  const promptsDir = resolve(projectDir, "..", "..", "src", "urika", "agents", "roles", "prompts");
  // In production, promptsDir would be resolved from the installed package

  const orchestrator = new Orchestrator({
    projectDir: resolve(projectDir),
    promptsDir,
    defaultModel: config.defaultModel,
    modelOverrides: config.models,
    pythonCommand: "python",
  });

  await orchestrator.connect();

  if (headless) {
    // Headless mode: read stdin line by line, send to orchestrator, print response
    const readline = await import("readline");
    const rl = readline.createInterface({ input: process.stdin });
    for await (const line of rl) {
      const response = await orchestrator.processMessage(line);
      console.log(JSON.stringify({ type: "response", text: response }));
    }
  } else {
    // Interactive mode: launch pi-tui
    // TODO: Wire pi-tui components to orchestrator
    console.log(`Urika TUI — ${config.projectName}`);
    console.log("Interactive mode not yet implemented. Use --headless for now.");
  }

  orchestrator.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

**Step 2: Commit**

```bash
git add tui/src/index.ts
git commit -m "feat(tui): wire entry point to orchestrator and config loader"
```

---

## Phase 4: Python CLI Integration

---

### Task 16: Add `urika tui` and Update `urika run`

**Files:**
- Modify: `src/urika/cli/__init__.py` (or wherever the Click group is defined)
- Test: `tests/test_cli.py` (add test for new commands)

**Step 1: Add `urika tui` command**

```python
@cli.command()
@click.argument("project", required=False)
def tui(project):
    """Launch the interactive Urika TUI."""
    import shutil
    import subprocess

    tui_bin = shutil.which("urika-tui")
    if tui_bin is None:
        # Try local dev path
        tui_bin = str(Path(__file__).parent.parent.parent.parent / "tui" / "dist" / "urika-tui")
    if not Path(tui_bin).exists():
        click.echo("TUI binary not found. Run 'cd tui && bun run build' first.")
        raise SystemExit(1)

    args = [tui_bin]
    if project:
        project_dir = _resolve_project(project)
        args.append(str(project_dir))
    subprocess.run(args)
```

**Step 2: Add `--legacy` flag to `urika run`**

```python
@cli.command()
@click.argument("project")
@click.option("--legacy", is_flag=True, help="Use deterministic Python orchestrator")
@click.option("--max-turns", default=10, help="Maximum turns per experiment")
def run(project, legacy, max_turns):
    """Run experiments on a project."""
    if legacy:
        # Existing Python orchestrator
        _run_legacy(project, max_turns)
    else:
        # New TS orchestrator in headless mode
        import subprocess
        tui_bin = _find_tui_binary()
        project_dir = _resolve_project(project)
        subprocess.run([tui_bin, "--headless", str(project_dir),
                       "--max-turns", str(max_turns)])
```

**Step 3: Test**

```bash
pytest tests/test_cli.py -v -k "tui or legacy"
```

**Step 4: Commit**

```bash
git add src/urika/cli/ tests/test_cli.py
git commit -m "feat(cli): add 'urika tui' command and --legacy flag to 'urika run'"
```

---

## Phase 5: Notifications (Deferred)

Tasks 17-19 move Telegram/Slack to TypeScript. These can be implemented after the core orchestrator is working. Documented here for completeness but not detailed at task-level yet.

### Task 17: Telegram Bot Listener (TS)
- Create: `tui/src/notifications/telegram.ts`
- Listens for messages, injects into orchestrator as UserMessage
- Uses `node-telegram-bot-api` or equivalent

### Task 18: Slack Bot Listener (TS)
- Create: `tui/src/notifications/slack.ts`
- Socket Mode listener, injects into orchestrator as UserMessage

### Task 19: Event Dispatcher
- Create: `tui/src/notifications/dispatcher.ts`
- Subscribes to orchestrator events, routes formatted messages to channels

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| **1: Python RPC** | 1-4 | Python compute server, all core modules accessible via JSON-RPC |
| **2: TS Scaffolding** | 5-8 | TypeScript package, RPC client, config loader, prompt loader |
| **3: Orchestrator** | 9-12 | LLM-driven orchestrator with agents-as-tools via pi-ai |
| **3.5: TUI** | 13-15 | Pi-tui fork, Urika customization, wired to orchestrator |
| **4: CLI Integration** | 16 | `urika tui` command, `urika run` uses new orchestrator |
| **5: Notifications** | 17-19 | Telegram/Slack as message sources (deferred) |
