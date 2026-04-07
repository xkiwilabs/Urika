import {
  TUI,
  Editor,
  Text,
  Loader,
  CancellableLoader,
  ProcessTerminal,
  CombinedAutocompleteProvider,
  type Component,
  type EditorTheme,
  type SlashCommand as PiSlashCommand,
} from "@mariozechner/pi-tui";
import chalk from "chalk";
import { renderHeader } from "./header";
import { formatAgentLabel } from "./agent-display";
import { handleSlashCommand } from "./commands";
import type { Orchestrator } from "../orchestrator/orchestrator";
import type { RpcClient } from "../rpc/client";

export interface UrikaAppOptions {
  projectName: string;
  version: string;
  projectDir: string;
  orchestrator: Orchestrator;
  rpcClient: RpcClient | null;
}

/**
 * OutputArea — accumulates rendered lines into native terminal scrollback.
 */
class OutputArea implements Component {
  private lines: string[] = [];

  appendText(text: string): void {
    this.lines.push(...text.split("\n"));
  }

  clear(): void {
    this.lines = [];
  }

  invalidate(): void {}

  render(_width: number): string[] {
    return this.lines;
  }
}

/**
 * ThinkingIndicator — shows agent activity below the editor.
 * Matches the REPL's ThinkingPanel behavior.
 */
class ThinkingIndicator implements Component {
  private agent = "";
  private turn = 0;
  private model = "";
  private cost = 0;
  private elapsed = 0;
  private project = "";
  private experimentId = "";
  private active = false;

  update(partial: {
    agent?: string;
    turn?: number;
    model?: string;
    cost?: number;
    elapsed?: number;
    project?: string;
    experimentId?: string;
    active?: boolean;
  }): void {
    if (partial.agent !== undefined) this.agent = partial.agent;
    if (partial.turn !== undefined) this.turn = partial.turn;
    if (partial.model !== undefined) this.model = partial.model;
    if (partial.cost !== undefined) this.cost = partial.cost;
    if (partial.elapsed !== undefined) this.elapsed = partial.elapsed;
    if (partial.project !== undefined) this.project = partial.project;
    if (partial.experimentId !== undefined) this.experimentId = partial.experimentId;
    if (partial.active !== undefined) this.active = partial.active;
  }

  invalidate(): void {}

  render(width: number): string[] {
    const D = chalk.dim;
    const sep = D(" │ ");
    const divider = D("─".repeat(width));

    if (!this.active) {
      // Idle state — show project info
      const parts: string[] = [];
      if (this.project) parts.push(chalk.cyan(this.project));
      if (this.experimentId) parts.push(chalk.white(this.experimentId));
      parts.push(D("ready"));
      return [divider, `  ${parts.join(sep)}`];
    }

    // Active state — show agent activity
    const parts: string[] = [];
    if (this.experimentId) parts.push(chalk.cyan(this.experimentId));
    if (this.turn > 0) parts.push(chalk.white(`turn ${this.turn}`));
    if (this.agent) parts.push(chalk.yellow(this.agent.replace(/_/g, " ")));
    if (this.model) parts.push(D(this.model));
    if (this.cost > 0) parts.push(chalk.green(`$${this.cost.toFixed(2)}`));
    if (this.elapsed > 0) parts.push(D(`${Math.floor(this.elapsed / 1000)}s`));

    return [divider, `  ${parts.join(sep)}`];
  }
}

const EDITOR_THEME: EditorTheme = {
  borderColor: chalk.dim,
  selectList: {
    selectedPrefix: chalk.cyan,
    selectedText: chalk.bgCyan.black,
    description: chalk.dim,
    scrollInfo: chalk.dim,
    noMatch: chalk.dim,
  },
};

/** Slash commands for autocomplete. */
const SLASH_COMMANDS: PiSlashCommand[] = [
  { name: "help", description: "Show available commands" },
  { name: "project", description: "Open a project" },
  { name: "list", description: "List all projects" },
  { name: "new", description: "Create a new project" },
  { name: "status", description: "Show project status" },
  { name: "results", description: "Show experiment results" },
  { name: "config", description: "Show/edit configuration" },
  { name: "login", description: "Login to a provider (e.g. /login anthropic)" },
  { name: "logout", description: "Logout from a provider" },
  { name: "auth", description: "Show authentication status" },
  { name: "pause", description: "Pause current run" },
  { name: "stop", description: "Stop current run" },
  { name: "quit", description: "Exit Urika TUI" },
];

export class UrikaApp {
  private tui: TUI;
  private output: OutputArea;
  private thinking: ThinkingIndicator;
  private editor: Editor;
  private options: UrikaAppOptions;
  private processing = false;

  constructor(options: UrikaAppOptions) {
    this.options = options;
    const terminal = new ProcessTerminal();
    this.tui = new TUI(terminal, true);

    // Output area — scrolling content
    this.output = new OutputArea();

    // Editor — user input with autocomplete
    this.editor = new Editor(this.tui, EDITOR_THEME);
    this.editor.onSubmit = async (text: string) => {
      await this.handleInput(text);
    };

    // Wire autocomplete for slash commands
    const autocomplete = new CombinedAutocompleteProvider(SLASH_COMMANDS);
    this.editor.setAutocompleteProvider(autocomplete);

    // Thinking indicator — below editor
    this.thinking = new ThinkingIndicator();
    this.thinking.update({ project: options.projectName });

    // Layout: header → output → editor → thinking
    const headerLines = renderHeader(options.projectName, options.version);
    const header = new Text(headerLines.join("\n"));

    this.tui.addChild(header);
    this.tui.addChild(this.output);
    this.tui.addChild(this.editor);
    this.tui.addChild(this.thinking);
    this.tui.setFocus(this.editor);

    // Wire orchestrator events
    this.wireOrchestratorEvents();
  }

  start(): void {
    this.tui.start();
  }

  stop(): void {
    this.tui.stop();
  }

  shutdown(): void {
    this.tui.stop();
    this.options.orchestrator.close();
    this.options.rpcClient?.close();
    process.exit(0);
  }

  private wireOrchestratorEvents(): void {
    this.options.orchestrator.setEvents({
      onAgentStart: (name) => {
        this.output.appendText(formatAgentLabel(name));
        this.thinking.update({ agent: name, active: true });
        this.tui.requestRender();
      },
      onAgentOutput: (_name, text) => {
        this.output.appendText(text);
        this.tui.requestRender();
      },
      onAgentEnd: (_name) => {
        this.thinking.update({ agent: "", active: false });
        this.tui.requestRender();
      },
      onText: (text) => {
        this.output.appendText(text);
        this.tui.requestRender();
      },
      onToolCall: (name, args) => {
        const summary = JSON.stringify(args).slice(0, 60);
        this.output.appendText(chalk.dim(`  → ${name}(${summary})`));
        this.tui.requestRender();
      },
      onError: (error) => {
        this.output.appendText(chalk.red(`  ✗ ${error}`));
        this.thinking.update({ active: false });
        this.tui.requestRender();
      },
    });
  }

  private async handleInput(text: string): Promise<void> {
    if (!text.trim()) return;

    // Add to editor history for up/down arrow
    this.editor.addToHistory(text);

    // Check for slash commands
    const cmdResult = await handleSlashCommand(
      text,
      this.options.rpcClient,
      this.options.projectDir,
    );
    if (cmdResult.handled) {
      if (cmdResult.output === "__QUIT__") {
        this.shutdown();
        return;
      }
      if (cmdResult.output) {
        this.output.appendText(cmdResult.output);
        this.tui.requestRender();
      }
      return;
    }

    // Send to orchestrator
    if (this.processing) {
      this.output.appendText(chalk.yellow("  Still processing..."));
      this.tui.requestRender();
      return;
    }

    this.processing = true;
    this.output.appendText(chalk.dim(`  > ${text}`));
    this.thinking.update({ active: true });
    this.tui.requestRender();

    try {
      await this.options.orchestrator.processMessage(text);
    } catch (err: any) {
      this.output.appendText(chalk.red(`  ✗ ${err.message}`));
    } finally {
      this.processing = false;
      this.thinking.update({ active: false });
      this.tui.requestRender();
    }
  }
}
