import { spawn, execFileSync, type ChildProcess } from "child_process";
import { createInterface } from "readline";
import type {
  AgentRuntime,
  ManagedAgent,
  RuntimeEvent,
  AgentConfig,
  UsageStats,
  ModelInfo,
  AuthStatus,
} from "./types";

/**
 * ClaudeRuntime — delegates to the `claude` CLI for subscription-based auth.
 *
 * Uses `claude --print --output-format stream-json` for non-interactive
 * streaming execution with JSONL output on stdout.
 */
export class ClaudeRuntime implements AgentRuntime {
  readonly name = "claude" as const;
  private claudePath: string;

  constructor(options?: { claudePath?: string }) {
    this.claudePath = options?.claudePath ?? "claude";
  }

  async authenticate(): Promise<void> {
    // Check if claude CLI is available and logged in
    if (this.isAuthenticated()) return;

    // Not logged in — spawn interactive login
    const proc = spawn(this.claudePath, ["login"], { stdio: "inherit" });
    await new Promise<void>((resolve, reject) => {
      proc.on("exit", (code) =>
        code === 0 ? resolve() : reject(new Error("Login failed")),
      );
    });
  }

  isAuthenticated(): boolean {
    // Quick check: claude CLI exists and can respond
    try {
      execFileSync(this.claudePath, ["--version"], {
        stdio: "pipe",
        timeout: 5000,
      });
      // CLI exists — auth is handled by Claude Code's own login system
      // If not logged in, the CLI will return an auth error on first use
      return true;
    } catch {
      return false;
    }
  }

  getAuthStatus(): AuthStatus {
    return {
      provider: "anthropic",
      method: "cli",
      active: this.isAuthenticated(),
    };
  }

  createAgent(config: AgentConfig): ManagedAgent {
    return new ClaudeManagedAgent(this.claudePath, config);
  }

  listModels(): ModelInfo[] {
    return [
      {
        id: "claude-sonnet-4-6",
        provider: "anthropic",
        name: "Claude Sonnet 4.6",
      },
      {
        id: "claude-opus-4-6",
        provider: "anthropic",
        name: "Claude Opus 4.6",
      },
      {
        id: "claude-haiku-4-5",
        provider: "anthropic",
        name: "Claude Haiku 4.5",
      },
    ];
  }

  getDefaultModel(): string {
    return "sonnet";
  }
}

/**
 * ClaudeManagedAgent — wraps a single `claude --print` subprocess.
 *
 * Spawns the CLI with `--output-format stream-json --include-partial-messages`
 * and translates JSONL events into unified RuntimeEvent emissions.
 */
class ClaudeManagedAgent implements ManagedAgent {
  private claudePath: string;
  private config: AgentConfig;
  private process: ChildProcess | null = null;
  private listeners: Set<(event: RuntimeEvent) => void> = new Set();
  private _isRunning = false;

  constructor(claudePath: string, config: AgentConfig) {
    this.claudePath = claudePath;
    this.config = config;
  }

  async prompt(message: string): Promise<void> {
    this._isRunning = true;
    this.emit({ type: "agent_start" });

    const startTime = Date.now();
    const args = this.buildArgs(message);

    // Spawn claude CLI
    this.process = spawn(this.claudePath, args, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    let totalCost = 0;
    let tokensIn = 0;
    let tokensOut = 0;
    let model = this.config.model ?? "sonnet";

    // Read stdout line by line (JSONL)
    const rl = createInterface({ input: this.process.stdout! });

    try {
      for await (const line of rl) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          this.handleClaudeEvent(event);

          // Extract usage from result event
          if (event.type === "result") {
            totalCost = event.cost_usd ?? 0;
            tokensIn = event.num_input_tokens ?? 0;
            tokensOut = event.num_output_tokens ?? 0;
            model = event.model ?? model;

            if (event.is_error) {
              this.emit({
                type: "error",
                message: event.result ?? "Unknown error from claude CLI",
              });
            }
          }
        } catch {
          // Ignore unparseable lines
        }
      }
    } catch (err: any) {
      this.emit({ type: "error", message: err.message ?? "Stream read error" });
    }

    // Wait for process to exit
    if (this.process) {
      await new Promise<void>((resolve) => {
        this.process!.on("exit", () => resolve());
        // If already exited, resolve immediately
        if (this.process!.exitCode !== null) resolve();
      });
    }

    this.emit({
      type: "agent_end",
      usage: {
        tokensIn,
        tokensOut,
        cost: totalCost,
        model,
        elapsed: Date.now() - startTime,
      },
    });

    this._isRunning = false;
    this.process = null;
  }

  subscribe(listener: (event: RuntimeEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  steer(message: string): void {
    // Write to stdin in stream-json format
    if (this.process?.stdin && !this.process.stdin.destroyed) {
      this.process.stdin.write(
        JSON.stringify({ type: "user", content: message }) + "\n",
      );
    }
  }

  abort(): void {
    if (this.process) {
      this.process.kill("SIGINT");
      this._isRunning = false;
    }
  }

  get isRunning(): boolean {
    return this._isRunning;
  }

  // --- Private helpers ---

  private buildArgs(message: string): string[] {
    const args = [
      "--print",
      "--output-format",
      "stream-json",
      "--verbose",
      "--include-partial-messages",
    ];

    // System prompt
    if (this.config.systemPrompt) {
      args.push("--append-system-prompt", this.config.systemPrompt);
    }

    // Model — claude CLI accepts short names like "sonnet", "opus", "haiku"
    if (this.config.model) {
      const modelName = this.config.model
        .replace("anthropic/", "")
        .replace("claude-", "");
      args.push("--model", modelName);
    }

    // Allowed tools
    if (this.config.tools.length > 0) {
      const toolNames = this.config.tools.map((t) => t.name).join(",");
      args.push("--allowed-tools", toolNames);
    }

    // Message
    args.push(message);

    return args;
  }

  private handleClaudeEvent(event: any): void {
    switch (event.type) {
      case "system":
        // Init event — skip (contains session_id, tools, model info)
        break;

      case "content_block_delta":
        if (event.delta?.type === "text_delta") {
          this.emit({ type: "text_delta", delta: event.delta.text });
        } else if (event.delta?.type === "thinking_delta") {
          this.emit({ type: "thinking_delta", delta: event.delta.thinking });
        }
        break;

      case "assistant":
        // Full assistant message — extract text blocks
        if (event.message?.content) {
          for (const block of event.message.content) {
            if (block.type === "text") {
              this.emit({ type: "text_delta", delta: block.text });
            }
          }
        }
        // Check for auth errors
        if (event.error === "authentication_failed") {
          this.emit({ type: "error", message: "Not logged in. Run: claude login" });
        }
        break;

      case "tool_use":
        this.emit({
          type: "tool_start",
          name: event.name,
          args: event.input,
        });
        break;

      case "tool_result":
        this.emit({
          type: "tool_end",
          name: event.tool_use_id ?? event.name ?? "unknown",
          result: event.content,
          isError: event.is_error ?? false,
        });
        break;

      case "result":
        // Final result — handled in prompt() for usage extraction
        break;
    }
  }

  private emit(event: RuntimeEvent): void {
    for (const listener of this.listeners) {
      listener(event);
    }
  }
}
