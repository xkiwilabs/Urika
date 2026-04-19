import type { AgentRuntime, ManagedAgent, AgentConfig, ModelInfo, AuthStatus } from "./types";

/**
 * CodexRuntime — stub for OpenAI Codex backend.
 * Not yet implemented. All agent operations throw.
 */
export class CodexRuntime implements AgentRuntime {
  readonly name = "codex" as const;

  async authenticate(): Promise<void> {
    throw new Error("CodexRuntime not yet implemented");
  }

  isAuthenticated(): boolean {
    return false;
  }

  getAuthStatus(): AuthStatus {
    return { provider: "openai", method: "api-key", active: false };
  }

  createAgent(_config: AgentConfig): ManagedAgent {
    throw new Error("CodexRuntime not yet implemented");
  }

  listModels(): ModelInfo[] {
    return [];
  }

  getDefaultModel(): string {
    return "openai/gpt-4o";
  }
}
