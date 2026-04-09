import type { AppContext } from "@urika/agent-runtime";

/**
 * Supply Urika-specific prompt template variables at runtime.
 * These are injected into {{variable}} placeholders in agent prompts.
 */
export async function getPromptVariables(
  ctx: AppContext,
): Promise<Record<string, string>> {
  return {
    project_name: ctx.projectName,
    question: ctx.projectConfig?.question ?? "",
    data_dir: ctx.projectDir ? ctx.projectDir + "/data" : "",
    mode: ctx.projectConfig?.mode ?? "exploratory",
    experiment_id: "",
    current_state: ctx.projectDir
      ? "Project loaded. Awaiting instructions."
      : "No project selected. Tell me which project to work on, or type /help.",
  };
}

/**
 * Called when a project switch occurs (via the switch_project tool or /project command).
 * Loads the project config via RPC and returns the resolved project info.
 */
export async function onProjectSwitch(
  projectDir: string,
  ctx: AppContext,
): Promise<{ projectName: string; projectDir: string }> {
  const config = (await ctx.rpc.call("project.load_config", {
    project_dir: projectDir,
  })) as any;
  return {
    projectName: config.name ?? "Unknown",
    projectDir,
  };
}
