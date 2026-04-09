import { Agent } from "@mariozechner/pi-agent-core";
import type {
  AgentEvent,
  AgentMessage,
  AgentTool as PiAgentTool,
  AgentToolResult,
} from "@mariozechner/pi-agent-core";
import {
  getModel,
  getModels,
  getProviders,
  streamSimple,
  Type,
} from "@mariozechner/pi-ai";
import type {
  Model,
  Message,
  AssistantMessage,
  AssistantMessageEvent,
  KnownProvider,
} from "@mariozechner/pi-ai";
import type {
  AgentRuntime,
  ManagedAgent,
  RuntimeEvent,
  AgentConfig,
  UsageStats,
  ModelInfo,
  AuthStatus,
  ToolDefinition,
} from "./types";

// ---------------------------------------------------------------------------
// PiRuntime — wraps pi-agent-core's Agent as an AgentRuntime backend
// ---------------------------------------------------------------------------

export class PiRuntime implements AgentRuntime {
  readonly name = "pi" as const;
  private apiKeyResolver?: (provider: string) => Promise<string | undefined>;

  constructor(options?: {
    getApiKey?: (provider: string) => Promise<string | undefined>;
  }) {
    this.apiKeyResolver = options?.getApiKey;
  }

  async authenticate(): Promise<void> {
    // Pi uses API keys via environment variables — no interactive auth flow.
    // Callers should set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY.
  }

  isAuthenticated(): boolean {
    return !!(
      process.env.ANTHROPIC_API_KEY ||
      process.env.OPENAI_API_KEY ||
      process.env.GEMINI_API_KEY
    );
  }

  getAuthStatus(): AuthStatus {
    return {
      provider: "pi-multi",
      method: "api-key",
      active: this.isAuthenticated(),
    };
  }

  createAgent(config: AgentConfig): ManagedAgent {
    return new PiManagedAgent(config, this.apiKeyResolver);
  }

  listModels(): ModelInfo[] {
    const models: ModelInfo[] = [];
    try {
      for (const provider of getProviders()) {
        for (const model of getModels(provider)) {
          models.push({
            id: model.id,
            provider: model.provider,
            name: model.name,
          });
        }
      }
    } catch {
      // pi-ai may not have all providers loaded
    }
    return models;
  }

  getDefaultModel(): string {
    return "anthropic/claude-sonnet-4-6";
  }
}

// ---------------------------------------------------------------------------
// PiManagedAgent — wraps a single pi-agent-core Agent instance
// ---------------------------------------------------------------------------

class PiManagedAgent implements ManagedAgent {
  private agent: Agent;
  private listeners: Set<(event: RuntimeEvent) => void> = new Set();
  private _isRunning = false;

  constructor(
    config: AgentConfig,
    apiKeyResolver?: (provider: string) => Promise<string | undefined>,
  ) {
    const model = resolveModel(config.model ?? "anthropic/claude-sonnet-4-6");
    const piTools = config.tools.map((t) =>
      toPiAgentTool(t, config.toolExecutors),
    );

    this.agent = new Agent({
      initialState: {
        systemPrompt: config.systemPrompt,
        model,
        tools: piTools,
        thinkingLevel: "off",
      },
      convertToLlm: (messages: AgentMessage[]) =>
        messages.filter(
          (m): m is Message =>
            typeof m === "object" &&
            m !== null &&
            "role" in m &&
            ((m as any).role === "user" ||
              (m as any).role === "assistant" ||
              (m as any).role === "toolResult"),
        ),
      getApiKey: apiKeyResolver,
      streamFn: streamSimple,
    });

    // Map pi-agent-core events to RuntimeEvents
    this.agent.subscribe(async (event: AgentEvent) => {
      const mapped = mapEvent(event);
      if (mapped) {
        for (const listener of this.listeners) {
          listener(mapped);
        }
      }
    });
  }

  async prompt(message: string): Promise<void> {
    this._isRunning = true;
    try {
      await this.agent.prompt(message);
    } finally {
      this._isRunning = false;
    }
  }

  subscribe(listener: (event: RuntimeEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  steer(message: string): void {
    this.agent.steer({
      role: "user" as const,
      content: message,
      timestamp: Date.now(),
    });
  }

  abort(): void {
    this.agent.abort();
  }

  get isRunning(): boolean {
    return this._isRunning;
  }

  getMessages(): any[] {
    return this.agent.state.messages ?? [];
  }

  setMessages(messages: any[]): void {
    this.agent.state.messages = messages;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Parse "provider/model-id" and return a pi-ai Model. */
function resolveModel(modelString: string): Model<any> {
  const [provider, ...modelParts] = modelString.split("/");
  const modelId = modelParts.join("/");
  return getModel(provider as any, modelId as any);
}

/**
 * Convert a ToolDefinition to a pi-agent-core AgentTool.
 *
 * The execute function comes from `toolExecutors` on the AgentConfig.
 * If no executor is provided, the tool returns an error when called.
 */
function toPiAgentTool(
  def: ToolDefinition,
  executors?: Record<string, (args: any, signal?: AbortSignal) => Promise<any>>,
): PiAgentTool<any> {
  // Build a TypeBox schema from the param definitions
  const schemaProps: Record<string, any> = {};
  if (def.params) {
    for (const [key, param] of Object.entries(def.params)) {
      let schema: any;
      switch (param.type) {
        case "string":
          schema = Type.String({ description: param.description });
          break;
        case "number":
          schema = Type.Number({ description: param.description });
          break;
        case "boolean":
          schema = Type.Boolean({ description: param.description });
          break;
        case "object":
          schema = Type.Any({ description: param.description });
          break;
        default:
          schema = Type.Any({ description: param.description });
      }
      if (param.optional) {
        schema = Type.Optional(schema);
      }
      schemaProps[key] = schema;
    }
  }

  const executor = executors?.[def.name];

  return {
    name: def.name,
    label: def.name
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase()),
    description: def.description,
    parameters: Type.Object(schemaProps),
    execute: async (
      _toolCallId: string,
      params: any,
      signal?: AbortSignal,
    ): Promise<AgentToolResult<any>> => {
      if (!executor) {
        return {
          content: [
            {
              type: "text",
              text: `Error: no executor registered for tool "${def.name}"`,
            },
          ],
          details: { error: true },
        };
      }
      try {
        const result = await executor(params, signal);
        const text =
          typeof result === "string" ? result : JSON.stringify(result);
        return {
          content: [{ type: "text", text }],
          details: { toolName: def.name },
        };
      } catch (err: any) {
        return {
          content: [
            {
              type: "text",
              text: `Error: ${err?.message ?? String(err)}`,
            },
          ],
          details: { error: true },
        };
      }
    },
  };
}

/**
 * Map a pi-agent-core AgentEvent to a RuntimeEvent.
 * Returns null for events that have no RuntimeEvent equivalent.
 */
function mapEvent(event: AgentEvent): RuntimeEvent | null {
  switch (event.type) {
    case "agent_start":
      return { type: "agent_start" };

    case "agent_end": {
      // Extract usage from the last assistant message
      const usage = extractUsage(event.messages);
      return { type: "agent_end", usage };
    }

    case "message_update": {
      const assistantEvent: AssistantMessageEvent =
        event.assistantMessageEvent;
      if (assistantEvent.type === "text_delta") {
        return { type: "text_delta", delta: assistantEvent.delta };
      }
      if (assistantEvent.type === "thinking_delta") {
        return { type: "thinking_delta", delta: assistantEvent.delta };
      }
      if (assistantEvent.type === "error") {
        return {
          type: "error",
          message:
            assistantEvent.error.errorMessage ?? "Unknown streaming error",
        };
      }
      return null;
    }

    case "tool_execution_start":
      return {
        type: "tool_start",
        name: event.toolName,
        args: event.args,
      };

    case "tool_execution_end":
      return {
        type: "tool_end",
        name: event.toolName,
        result: event.result,
        isError: event.isError,
      };

    // Events without RuntimeEvent equivalents
    case "turn_start":
    case "turn_end":
    case "message_start":
    case "message_end":
    case "tool_execution_update":
      return null;

    default:
      return null;
  }
}

/** Extract usage stats from the final assistant messages in a run. */
function extractUsage(messages: AgentMessage[]): UsageStats {
  let tokensIn = 0;
  let tokensOut = 0;
  let cost = 0;
  let model = "unknown";
  const startTime = messages.length > 0 ? (messages[0] as any)?.timestamp ?? 0 : 0;
  const endTime =
    messages.length > 0
      ? (messages[messages.length - 1] as any)?.timestamp ?? 0
      : 0;

  for (const msg of messages) {
    if (
      typeof msg === "object" &&
      msg !== null &&
      "role" in msg &&
      (msg as any).role === "assistant"
    ) {
      const assistant = msg as AssistantMessage;
      if (assistant.usage) {
        tokensIn += assistant.usage.input;
        tokensOut += assistant.usage.output;
        cost += assistant.usage.cost?.total ?? 0;
      }
      if (assistant.model) {
        model = assistant.model;
      }
    }
  }

  return {
    tokensIn,
    tokensOut,
    cost,
    model,
    elapsed: endTime > 0 && startTime > 0 ? endTime - startTime : 0,
  };
}
