import { readFileSync, readdirSync } from "fs";

/**
 * Load a prompt template and substitute {variables}.
 * Unknown variables are left as-is (matching Python's behavior).
 */
export function loadPrompt(
  filePath: string,
  variables: Record<string, string> = {},
): string {
  let content = readFileSync(filePath, "utf-8");
  for (const [key, value] of Object.entries(variables)) {
    content = content.replaceAll(`{${key}}`, value);
  }
  return content;
}

/**
 * List all .md prompt files in a directory.
 */
export function listPromptFiles(promptsDir: string): string[] {
  return readdirSync(promptsDir).filter((f) => f.endsWith(".md")).sort();
}
