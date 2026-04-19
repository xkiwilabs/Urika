import type { AgentRuntime } from "./types";
import { PiRuntime } from "./pi-runtime";
import { ClaudeRuntime } from "./claude-runtime";
import { CodexRuntime } from "./codex-runtime";
import { GoogleRuntime } from "./google-runtime";

export interface RuntimeFactoryOptions {
  /** Resolve API keys for multi-provider runtimes (Pi). */
  getApiKey?: (provider: string) => Promise<string | undefined>;
  /** Path to the `claude` CLI binary (ClaudeRuntime). */
  claudePath?: string;
}

/**
 * Create an AgentRuntime by backend name.
 *
 * Supported backends: "claude", "pi", "codex", "google".
 */
export function createRuntime(
  backend: string,
  options?: RuntimeFactoryOptions,
): AgentRuntime {
  switch (backend) {
    case "claude":
      return new ClaudeRuntime({ claudePath: options?.claudePath });
    case "pi":
      return new PiRuntime({ getApiKey: options?.getApiKey });
    case "codex":
      return new CodexRuntime();
    case "google":
      return new GoogleRuntime();
    default:
      throw new Error(
        `Unknown runtime backend: ${backend}. Available: claude, pi, codex, google`,
      );
  }
}
