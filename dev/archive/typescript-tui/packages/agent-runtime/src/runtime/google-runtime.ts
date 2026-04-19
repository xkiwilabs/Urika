import type { AgentRuntime, ManagedAgent, AgentConfig, ModelInfo, AuthStatus } from "./types";

/**
 * GoogleRuntime — stub for Google Gemini backend.
 * Not yet implemented. All agent operations throw.
 */
export class GoogleRuntime implements AgentRuntime {
  readonly name = "google" as const;

  async authenticate(): Promise<void> {
    throw new Error("GoogleRuntime not yet implemented");
  }

  isAuthenticated(): boolean {
    return false;
  }

  getAuthStatus(): AuthStatus {
    return { provider: "google", method: "api-key", active: false };
  }

  createAgent(_config: AgentConfig): ManagedAgent {
    throw new Error("GoogleRuntime not yet implemented");
  }

  listModels(): ModelInfo[] {
    return [];
  }

  getDefaultModel(): string {
    return "google/gemini-2.5-pro";
  }
}
