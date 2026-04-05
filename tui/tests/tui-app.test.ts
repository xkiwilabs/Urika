import { describe, expect, it } from "bun:test";
import { StatusBar } from "../src/tui/status-bar";
import { formatAgentLabel, getAgentColor } from "../src/tui/agent-display";
import { renderHeader } from "../src/tui/header";
import { handleSlashCommand } from "../src/tui/commands";

describe("StatusBar", () => {
  it("renders ready state when empty", () => {
    const bar = new StatusBar();
    const lines = bar.render(80);
    expect(lines.length).toBe(2); // divider + content
  });

  it("renders experiment info after update", () => {
    const bar = new StatusBar();
    bar.update({ experimentId: "exp-001", turn: 3, model: "sonnet" });
    const lines = bar.render(80);
    const joined = lines.join("");
    expect(joined).toContain("exp-001");
    expect(joined).toContain("turn 3");
  });
});

describe("formatAgentLabel", () => {
  it("formats agent names with color", () => {
    const label = formatAgentLabel("planning_agent");
    expect(label).toContain("Planning Agent");
  });

  it("handles unknown agents", () => {
    const label = formatAgentLabel("unknown_role");
    expect(label).toContain("Unknown Role");
  });
});

describe("getAgentColor", () => {
  it("returns a function for known agents", () => {
    const colorFn = getAgentColor("task_agent");
    expect(typeof colorFn).toBe("function");
  });
});

describe("renderHeader", () => {
  it("renders ASCII logo with project name", () => {
    const lines = renderHeader("sleep-study", "1.0.0");
    expect(lines.length).toBeGreaterThan(3);
    const joined = lines.join("\n");
    expect(joined).toContain("sleep-study");
    expect(joined).toContain("1.0.0");
  });

  it("renders without project name", () => {
    const lines = renderHeader("", "0.1.0");
    const joined = lines.join("\n");
    expect(joined).toContain("0.1.0");
  });
});

describe("handleSlashCommand", () => {
  it("handles /help", async () => {
    const result = await handleSlashCommand("/help", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("/status");
    expect(result.output).toContain("/quit");
  });

  it("handles unknown commands", async () => {
    const result = await handleSlashCommand("/unknown", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Unknown command");
  });

  it("returns not handled for non-slash input", async () => {
    const result = await handleSlashCommand("hello world", null, "/tmp");
    expect(result.handled).toBe(false);
  });

  it("handles /status without rpc client", async () => {
    const result = await handleSlashCommand("/status", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Not connected");
  });
});
