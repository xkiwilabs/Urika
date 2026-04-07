import { describe, expect, it } from "bun:test";
import { formatAgentLabel, getAgentColor } from "../src/tui/agent-display";
import { renderHeader } from "../src/tui/header";
import { handleSlashCommand } from "../src/tui/commands";

describe("formatAgentLabel", () => {
  it("formats agent names with color and arrow", () => {
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
    expect(typeof getAgentColor("task_agent")).toBe("function");
  });

  it("returns a function for unknown agents", () => {
    expect(typeof getAgentColor("nonexistent")).toBe("function");
  });
});

describe("renderHeader", () => {
  it("renders Unicode box header with project name", () => {
    const lines = renderHeader("sleep-study", "1.0.0");
    expect(lines.length).toBeGreaterThan(5);
    const joined = lines.join("\n");
    expect(joined).toContain("sleep-study");
    expect(joined).toContain("1.0.0");
    expect(joined).toContain("╭");
    expect(joined).toContain("╰");
  });

  it("renders without project name", () => {
    const lines = renderHeader("", "0.1.0");
    const joined = lines.join("\n");
    expect(joined).toContain("0.1.0");
    expect(joined).toContain("Multi-agent");
  });
});

describe("handleSlashCommand", () => {
  it("handles /help", async () => {
    const result = await handleSlashCommand("/help", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("/project");
    expect(result.output).toContain("/list");
    expect(result.output).toContain("/status");
    expect(result.output).toContain("/login");
    expect(result.output).toContain("/quit");
  });

  it("handles /quit as special signal", async () => {
    const result = await handleSlashCommand("/quit", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toBe("__QUIT__");
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

  it("handles /list without rpc client", async () => {
    const result = await handleSlashCommand("/list", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Not connected");
  });

  it("handles /project without args", async () => {
    const result = await handleSlashCommand("/project", null, "/tmp");
    expect(result.handled).toBe(true);
  });

  it("handles /auth with no logins", async () => {
    const result = await handleSlashCommand("/auth", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("No active logins");
  });

  it("handles /login without provider", async () => {
    const result = await handleSlashCommand("/login", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Available providers");
    expect(result.output).toContain("anthropic");
  });

  it("handles unknown commands", async () => {
    const result = await handleSlashCommand("/foobar", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Unknown command");
  });

  it("handles /config without rpc client", async () => {
    const result = await handleSlashCommand("/config", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Not connected");
  });
});
