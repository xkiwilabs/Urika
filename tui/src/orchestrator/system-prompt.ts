import { loadPrompt } from "./prompt-loader";
import { join } from "path";

export interface OrchestratorContext {
  promptsDir: string;
  projectName: string;
  question: string;
  mode: string;
  dataDir: string;
  experimentId: string;
  currentState: string;
}

/**
 * Load and populate the orchestrator's system prompt.
 */
export function buildOrchestratorPrompt(ctx: OrchestratorContext): string {
  return loadPrompt(join(ctx.promptsDir, "orchestrator_system.md"), {
    project_name: ctx.projectName,
    question: ctx.question,
    mode: ctx.mode,
    data_dir: ctx.dataDir,
    experiment_id: ctx.experimentId,
    current_state: ctx.currentState,
  });
}
