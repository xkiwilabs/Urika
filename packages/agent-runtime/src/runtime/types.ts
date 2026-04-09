/** Runtime backend identifier */
export type RuntimeBackend = "claude" | "pi" | "codex" | "google";

/** Unified streaming event — all runtimes emit these */
export type RuntimeEvent =
  | { type: "text_delta"; delta: string }
  | { type: "thinking_delta"; delta: string }
  | { type: "tool_start"; name: string; args: any }
  | { type: "tool_end"; name: string; result: any; isError: boolean }
  | { type: "agent_start" }
  | { type: "agent_end"; usage: UsageStats }
  | { type: "error"; message: string };

/** Usage statistics from a run */
export interface UsageStats {
  tokensIn: number;
  tokensOut: number;
  cost: number;
  model: string;
  elapsed: number;
}

/** Agent configuration passed to runtime.createAgent() */
export interface AgentConfig {
  name: string;
  systemPrompt: string;
  tools: ToolDefinition[];
  model?: string;
  runtime?: RuntimeBackend;
  privacy?: "local" | "cloud";
  /** Tool executor functions keyed by tool name. The orchestrator builds these
   *  and passes them in — the runtime wires them to the underlying agent SDK. */
  toolExecutors?: Record<string, (args: any, signal?: AbortSignal) => Promise<any>>;
}

/** Tool definition — declared in runtime.toml or programmatically */
export interface ToolDefinition {
  name: string;
  description: string;
  scope: "global" | "project";
  params?: Record<string, ParamDefinition>;
  /** RPC method to call on the host system */
  rpcMethod?: string;
  /** Special handling (e.g. "switch_project") */
  special?: string;
}

/** Parameter definition for tool schemas */
export interface ParamDefinition {
  type: "string" | "number" | "boolean" | "object" | "any";
  description?: string;
  optional?: boolean;
}

/** Agent declaration from runtime.toml */
export interface AgentDeclaration {
  name: string;
  prompt: string;
  description: string;
  tools?: string[];
  privacy?: "local" | "cloud";
  model?: string;
}

/** Slash command declaration from runtime.toml */
export interface CommandDeclaration {
  name: string;
  description: string;
  scope: "global" | "project";
  autocomplete_rpc?: string;
}

/** Model info returned by listModels() */
export interface ModelInfo {
  id: string;
  provider: string;
  name: string;
}

/** Auth status */
export interface AuthStatus {
  provider: string;
  method: "oauth" | "api-key" | "cli";
  active: boolean;
}

/** The unified agent interface that all runtimes expose */
export interface ManagedAgent {
  prompt(message: string): Promise<void>;
  subscribe(listener: (event: RuntimeEvent) => void): () => void;
  steer(message: string): void;
  abort(): void;
  readonly isRunning: boolean;
}

/** Runtime backend interface — each backend implements this */
export interface AgentRuntime {
  readonly name: RuntimeBackend;
  authenticate(): Promise<void>;
  isAuthenticated(): boolean;
  getAuthStatus(): AuthStatus;
  createAgent(config: AgentConfig): ManagedAgent;
  listModels(): ModelInfo[];
  getDefaultModel(): string;
}
