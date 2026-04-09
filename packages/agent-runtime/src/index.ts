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

export { PiRuntime } from "./runtime/pi-runtime";
export { ClaudeRuntime } from "./runtime/claude-runtime";
export { CodexRuntime } from "./runtime/codex-runtime";
export { GoogleRuntime } from "./runtime/google-runtime";
export { createRuntime } from "./runtime/factory";
export type { RuntimeFactoryOptions } from "./runtime/factory";

export * from "./config/types";
export * from "./config/loader";
export * from "./rpc/client";
export * from "./rpc/types";
export * from "./auth/storage";
export * from "./auth/login";
export * from "./orchestrator/prompt-loader";
export { GenericOrchestrator } from "./orchestrator/orchestrator";
export type { OrchestratorContext, ProjectSwitchResult, OnProjectSwitch } from "./orchestrator/orchestrator";

// App entry point
export { createApp } from "./app";
export type { App, AppOptions, AppContext, CommandContext as AppCommandContext, CommandHandler } from "./app";

// TUI components
export { AgentTuiApp, CMD_QUIT, CMD_PROJECT_PREFIX } from "./tui/app";
export type { AgentTuiAppOptions, CommandContext, SubscriptionHandlers } from "./tui/app";
export { FooterComponent, formatTokens, formatCost, formatElapsed } from "./tui/footer";
export type { FooterState } from "./tui/footer";
export { formatAgentLabel, getAgentColor, registerAgentColor } from "./tui/agent-display";
