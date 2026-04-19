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

  it("handles /project without args and no rpc client", async () => {
    const result = await handleSlashCommand("/project", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Not connected");
  });

  it("handles /project <name> without rpc client", async () => {
    const result = await handleSlashCommand("/project myproj", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("Not connected");
  });

  it("handles /project <name> with mock rpc returning __PROJECT__ signal", async () => {
    const mockRpc = {
      call: async (method: string, _params: any) => {
        if (method === "project.list") {
          return [{ name: "sleep-study", path: "/home/user/sleep-study" }];
        }
        return {};
      },
      close: () => {},
    } as any;
    const result = await handleSlashCommand("/project sleep-study", mockRpc, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toBe("__PROJECT__:/home/user/sleep-study");
  });

  it("handles /project <name> not found", async () => {
    const mockRpc = {
      call: async (method: string, _params: any) => {
        if (method === "project.list") return [];
        return {};
      },
      close: () => {},
    } as any;
    const result = await handleSlashCommand("/project nonexistent", mockRpc, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("not found");
  });

  it("handles /auth command", async () => {
    const result = await handleSlashCommand("/auth", null, "/tmp");
    expect(result.handled).toBe(true);
    // Output depends on whether user has active logins
    expect(result.output.length).toBeGreaterThan(0);
  });

  it("handles /login without provider", async () => {
    const result = await handleSlashCommand("/login", null, "/tmp");
    expect(result.handled).toBe(true);
    expect(result.output).toContain("anthropic");
    expect(result.output).toContain("/login <number>");
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
