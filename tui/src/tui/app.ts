import {
  TUI,
  Editor,
  Text,
  ProcessTerminal,
  type Component,
  type EditorTheme,
} from "@mariozechner/pi-tui";
import chalk from "chalk";
import { StatusBar } from "./status-bar";
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
 * OutputArea -- a component that accumulates rendered lines.
 * New content is appended, entering the terminal's native scrollback.
 */
class OutputArea implements Component {
  private lines: string[] = [];

  appendLines(newLines: string[]): void {
    this.lines.push(...newLines);
  }

  appendText(text: string): void {
    this.lines.push(...text.split("\n"));
  }

  invalidate(): void {}

  render(_width: number): string[] {
    return this.lines;
  }
}

const DEFAULT_EDITOR_THEME: EditorTheme = {
  borderColor: chalk.dim,
  selectList: {
    selectedPrefix: chalk.cyan,
    selectedText: chalk.bgCyan.black,
    description: chalk.dim,
    scrollInfo: chalk.dim,
    noMatch: chalk.dim,
  },
};

export class UrikaApp {
  private tui: TUI;
  private output: OutputArea;
  private statusBar: StatusBar;
  private editor: Editor;
  private options: UrikaAppOptions;
  private processing = false;

  constructor(options: UrikaAppOptions) {
    this.options = options;
    const terminal = new ProcessTerminal();
    this.tui = new TUI(terminal, true);

    // Output area -- scrolling agent output
    this.output = new OutputArea();

    // Status bar
    this.statusBar = new StatusBar();
    this.statusBar.update({ project: options.projectName });

    // Editor -- user input (requires tui + theme)
    this.editor = new Editor(this.tui, DEFAULT_EDITOR_THEME);
    this.editor.onSubmit = async (text: string) => {
      await this.handleInput(text);
    };

    // Assemble layout: header + output + status + editor
    const headerLines = renderHeader(options.projectName, options.version);
    const header = new Text(headerLines.join("\n"));

    this.tui.addChild(header);
    this.tui.addChild(this.output);
    this.tui.addChild(this.statusBar);
    this.tui.addChild(this.editor);
    this.tui.setFocus(this.editor);

    // Wire orchestrator events
    options.orchestrator.setEvents({
      onAgentStart: (name) => {
        this.output.appendText(formatAgentLabel(name));
        this.statusBar.update({ agent: name });
        this.tui.requestRender();
      },
      onAgentOutput: (_name, text) => {
        this.output.appendText(text);
        this.tui.requestRender();
      },
      onAgentEnd: (_name) => {
        this.statusBar.update({ agent: "" });
        this.tui.requestRender();
      },
      onText: (text) => {
        this.output.appendText(text);
        this.tui.requestRender();
      },
      onToolCall: (name, args) => {
        this.output.appendText(chalk.dim(`  → ${name}(${JSON.stringify(args).slice(0, 80)})`));
        this.tui.requestRender();
      },
      onError: (error) => {
        this.output.appendText(chalk.red(`Error: ${error}`));
        this.tui.requestRender();
      },
    });
  }

  start(): void {
    this.tui.start();
  }

  stop(): void {
    this.tui.stop();
  }

  /** Clean shutdown — stop TUI, close connections, exit. */
  shutdown(): void {
    this.tui.stop();
    this.options.orchestrator.close();
    this.options.rpcClient?.close();
    process.exit(0);
  }

  private async handleInput(text: string): Promise<void> {
    if (!text.trim()) return;

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
      this.output.appendText(chalk.yellow("Still processing previous request..."));
      this.tui.requestRender();
      return;
    }

    this.processing = true;
    this.output.appendText(chalk.dim(`> ${text}`));
    this.tui.requestRender();

    try {
      await this.options.orchestrator.processMessage(text);
      // Response is already displayed via onText event
    } catch (err: any) {
      this.output.appendText(chalk.red(`Error: ${err.message}`));
    } finally {
      this.processing = false;
      this.tui.requestRender();
    }
  }
}
