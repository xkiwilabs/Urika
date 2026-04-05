import { describe, expect, it } from "bun:test";
import { loadPrompt, listPromptFiles } from "../src/orchestrator/prompt-loader";
import { mkdtempSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

describe("loadPrompt", () => {
  it("loads and substitutes variables in a prompt template", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompt-"));
    writeFileSync(
      join(dir, "test.md"),
      "Analyze data in {project_dir} for experiment {experiment_id}.",
    );
    const result = loadPrompt(join(dir, "test.md"), {
      project_dir: "/tmp/my-project",
      experiment_id: "exp-001",
    });
    expect(result).toBe(
      "Analyze data in /tmp/my-project for experiment exp-001.",
    );
  });

  it("leaves unknown variables as-is", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompt-"));
    writeFileSync(join(dir, "test.md"), "Hello {name}, today is {date}.");
    const result = loadPrompt(join(dir, "test.md"), { name: "Mike" });
    expect(result).toBe("Hello Mike, today is {date}.");
  });

  it("handles empty variables", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompt-"));
    writeFileSync(join(dir, "test.md"), "No variables here.");
    const result = loadPrompt(join(dir, "test.md"));
    expect(result).toBe("No variables here.");
  });
});

describe("listPromptFiles", () => {
  it("lists all .md files in a prompts directory", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-prompts-"));
    writeFileSync(join(dir, "task_agent_system.md"), "task prompt");
    writeFileSync(join(dir, "evaluator_system.md"), "eval prompt");
    writeFileSync(join(dir, "not_a_prompt.txt"), "ignored");
    const files = listPromptFiles(dir);
    expect(files).toContain("task_agent_system.md");
    expect(files).toContain("evaluator_system.md");
    expect(files).not.toContain("not_a_prompt.txt");
  });
});
