/**
 * @urika/agent-runtime — Reusable multi-SDK agent runtime with TUI
 *
 * Provides:
 * - Runtime backends (Claude CLI, Pi multi-provider, Codex, Google)
 * - Terminal UI (pi-tui based)
 * - Generic orchestrator
 * - JSON-RPC client for host system communication
 * - Auth management
 */

export const VERSION = "0.1.0";

// Runtime types
export type {
  RuntimeBackend,
  RuntimeEvent,
  UsageStats,
  AgentConfig,
  ToolDefinition,
  ParamDefinition,
  AgentDeclaration,
  CommandDeclaration,
  ModelInfo,
  AuthStatus,
  ManagedAgent,
  AgentRuntime,
} from "./runtime/types";
