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
  onTextDelta?: (role: string, text: string) => void;
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
 * and provides an execute function.
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
      execute: async (_input: string): Promise<string> => {
        // Execution is handled by Orchestrator.executeAgentTool()
        // This placeholder exists for direct testing only
        throw new Error(
          `Use Orchestrator.executeAgentTool() instead of calling ${role}.execute() directly`,
        );
      },
    });
  }

  return tools;
}
