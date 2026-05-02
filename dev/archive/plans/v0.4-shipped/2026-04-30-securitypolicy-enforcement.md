# SecurityPolicy Enforcement — v0.4

**Status:** active (design)
**Date:** 2026-04-30
**Track:** 1 (carry-over from v0.3.2 CHANGELOG known-limitations)
**Effort:** ~4.5 dev-days

The v0.3.2 CHANGELOG explicitly promised this for v0.4.

## Problem

Every agent role declares `SecurityPolicy(writable_dirs=[...],
readable_dirs=[...], allowed_bash_prefixes=[...],
blocked_bash_patterns=[...])`, but **none of those fields are consumed
at runtime**. `agents/config.py:30-72` is explicit about it
("ADVISORY ONLY: not enforced at runtime"). The only real sandbox is
`allowed_tools` + `cwd`. The orchestrator chat's
`allowed_bash_prefixes=["urika ", "CLAUDECODE= urika "]` is paper —
`urika ; rm -rf /` matches the prefix.

## SDK hook surface

`claude-agent-sdk` 0.1.45 exposes a clean permission callback —
already there, no SDK upgrade needed:

```python
from claude_agent_sdk import (
    CanUseTool, ToolPermissionContext,
    PermissionResultAllow, PermissionResultDeny,
)
# CanUseTool = Callable[[str, dict, ToolPermissionContext],
#                       Awaitable[PermissionResult]]
```

`ClaudeAgentOptions.can_use_tool` (`types.py:749`) is the wiring
point. The internal dispatcher is `Query._handle_control_request`
(`_internal/query.py:242-283`).

**Critical:** `can_use_tool` only fires when `permission_mode` is
`"default"` or `"acceptEdits"`. Today we use `"bypassPermissions"`
which skips the callback entirely. **Drop the bypass.**

## Enforcement function

New module: `src/urika/agents/permission.py`.

```python
async def permission_check(
    tool_name: str, tool_input: dict, ctx: ToolPermissionContext, *,
    policy: SecurityPolicy, project_root: Path,
) -> PermissionResult:
    ...
```

Bound at runtime via `functools.partial(permission_check,
policy=config.security, project_root=config.cwd)` in `_build_options`.

### Path canonicalization

Resolve both sides — `Path.expanduser()` then `.resolve(strict=False)`
to collapse `..` and follow symlinks. Compare via `Path.is_relative_to`
against each policy dir (also resolved). Otherwise a symlink inside
`writable_dirs` to `/etc` would pass the check.

### Bash command parsing

Reject these shell metacharacters outright (no shellout chains):
`;`, `&&`, `||`, `|`, backticks, `$(`, `>`, `>>`, `<`, `&`, newline.

Then `shlex.split(cmd)` and:

1. Apply blocklist FIRST — `policy.blocked_bash_patterns` always
   wins, even over allowlist matches. Catches embedded-string
   shellouts like `python -c "..."` that try to run blocked commands.
2. Empty `allowed_bash_prefixes` → deny all Bash.
3. Match against tokenised prefix (NOT raw `startswith`). For each
   prefix, `head_tokens = shlex.split(prefix)`, then check
   `tokens[: len(head_tokens)] == head_tokens`.

### Tool families

| Tool | Field checked | Input keys |
|---|---|---|
| `Bash` | `allowed_bash_prefixes` + `blocked_bash_patterns` | `command` |
| `Read`, `Glob`, `Grep` | `readable_dirs` | `file_path`, `path`, `pattern` |
| `Write`, `Edit`, `MultiEdit`, `NotebookEdit` | `writable_dirs` | `file_path`, `notebook_path` |
| `WebFetch`, `WebSearch` | (default allow) | n/a |
| MCP tools (`mcp__*`) | (default allow) | n/a |
| Anything else | (default allow) | n/a |

### Whitelisting vs blacklisting

- **Read/Write paths:** pure whitelist — empty `writable_dirs` means
  deny all writes.
- **Bash:** blocklist FIRST, then whitelist. Empty
  `allowed_bash_prefixes` means deny all Bash.

## Wiring

In `src/urika/agents/adapters/claude_sdk.py:_build_options`:

```python
from functools import partial
from urika.agents.permission import permission_check

kwargs["permission_mode"] = "default"          # was "bypassPermissions"
kwargs["can_use_tool"] = partial(
    permission_check,
    policy=config.security,
    project_root=config.cwd or Path.cwd(),
)
# Audit needed: also set setting_sources=[] so user-level
# ~/.claude/settings.json permission rules don't override ours.
```

## Migration plan

1. **`task_agent` / `finalizer` / `tool_builder` / `data_agent` /
   `literature_agent`:** values look correct; will newly enforce.
   Add `"pytest "` to `task_agent.allowed_bash_prefixes` (currently
   only `tool_builder` has it). Smoke test: `pip install` works,
   `python -m urika.foo` works, `git push` blocked, destructive
   shellouts blocked.
2. **Read-only roles** (`planning_agent`, `evaluator`, `advisor_agent`,
   `report_agent`, `presentation_agent`, `project_summarizer`,
   `project_builder`): unchanged.
3. **Orchestrator chat (`chat.py:285`):** under shlex parsing, the
   existing `["urika ", "CLAUDECODE= urika "]` becomes broken — the
   second is two tokens. Replace with:
   ```python
   allowed_bash_prefixes = ["urika"]   # head must be exactly "urika"
   ```
   The `CLAUDECODE=` prefix path was an env-var inline workaround;
   instead set `env={"CLAUDECODE": "1", ...}` on `AgentConfig`. The
   metacharacter rejector eats `*` so the existing `cat */data/`
   blocked patterns become belt-and-braces — keep them.
4. **`echo`, `project_builder`, `project_summarizer`:** unchanged.

## Test strategy

`tests/test_agents/test_permission.py` (new), 19-row decision table
covering allow / deny across the tool families and policy combinations.
Includes a regression test that the orchestrator's `Bash: urika ;
<destructive>` invocation now fails permission rather than executing.

## Effort

| Task | Days |
|---|---|
| `permission.py` module + unit tests (decision table 1-18) | 1.5 |
| Wire into `ClaudeSDKRunner._build_options`, drop `bypassPermissions` | 0.5 |
| Migrate orchestrator chat allowlist + env-var fix | 0.25 |
| Audit `task_agent` allowlist (add `pytest `) + verify all 13 roles | 0.5 |
| Regression test #19 + integration smoke (one task_agent end-to-end run that writes inside `experiment_dir`, one that tries to escape) | 0.75 |
| CHANGELOG / doc update / remove "ADVISORY ONLY" warning in `config.py:32-39` | 0.25 |
| Buffer for SDK quirks (callback timing, async loop integration) | 0.75 |
| **Total** | **~4.5 days** |

## Risks

- **False denials.** Agents that built up muscle memory under
  `bypassPermissions` will hit denies on `python -c "..."` style
  shellouts. Mitigation: deny `message` field is surfaced back to the
  agent — make it actionable ("use Write tool instead of `python -c`",
  "split into two Bash calls").
- **Symlink denial in user data dirs.** Researchers commonly symlink
  large datasets into a project; `readable_dirs=[project_dir]` plus
  `resolve()` will reject reads through a symlink to outside-tree
  data. Mitigation: add resolved symlink targets to `readable_dirs`
  automatically in `data_agent.py` when a symlink is detected.
- **`permission_mode` change side-effects.** Moving off
  `bypassPermissions` may also respect user-level
  `~/.claude/settings.json` permission rules unless we set
  `setting_sources=[]`. Audit + smoke before flipping.
- **Hybrid-mode privacy interaction.** `data_agent` is the primary
  defence against data exfiltration in hybrid mode. If the
  enforcement function silently passes (e.g. `_resolve_safe → None`
  treated as allow), we leak. Mitigation: `_resolve_safe → None` MUST
  deny, never allow.
- **Orchestrator chat UX regression.** Today the chat will happily
  run `urika status; urika logs` (chained). Post-migration that's a
  deny. Retrain the orchestrator system prompt to issue separate Bash
  calls. 1-line prompt change.

## Files

- `src/urika/agents/config.py:29-72`
- `src/urika/agents/adapters/claude_sdk.py:315-353`
- `src/urika/orchestrator/chat.py:285,299-310`
- `src/urika/agents/roles/{task_agent,finalizer,tool_builder,data_agent,literature_agent,advisor_agent,planning_agent,evaluator,report_agent,presentation_agent,project_summarizer,project_builder,echo}.py`
- claude-agent-sdk: `__init__.py` (exports), `types.py:124-157,716-770`,
  `_internal/query.py:233-283`
- Tests to extend: `tests/test_agents/test_config.py`,
  `tests/test_agents/test_task_agent_role.py`,
  `tests/test_agents/test_claude_sdk_adapter.py`; new file
  `tests/test_agents/test_permission.py`
