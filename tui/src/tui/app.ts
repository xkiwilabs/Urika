import {
  TUI,
  Editor,
  Text,
  Loader,
  ProcessTerminal,
  CombinedAutocompleteProvider,
  type EditorTheme,
  type SlashCommand as PiSlashCommand,
  type AutocompleteItem,
} from "@mariozechner/pi-tui";
import chalk from "chalk";
import { join } from "path";
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

export class UrikaApp {
  private tui: TUI;
  private editor: Editor;
  private loader: Loader;
  private statusLine: Text;
  private options: UrikaAppOptions;
  private processing = false;

  constructor(options: UrikaAppOptions) {
    this.options = options;
    const terminal = new ProcessTerminal();
    this.tui = new TUI(terminal, true);

    // Print header once (enters scrollback immediately)
    const headerLines = renderHeader(options.projectName, options.version);
    const header = new Text(headerLines.join("\n"));
    this.tui.addChild(header);

    // Editor — always at bottom, user types here
    this.editor = new Editor(this.tui, EDITOR_THEME);
    this.editor.onSubmit = async (text: string) => {
      await this.handleInput(text);
    };

    // Build slash commands with dynamic completions (needs rpcClient access)
    const rpcClient = options.rpcClient;
    const slashCommands: PiSlashCommand[] = [
      { name: "help", description: "Show available commands" },
      {
        name: "project",
        description: "Open a project",
        getArgumentCompletions: async (prefix: string): Promise<AutocompleteItem[]> => {
          if (!rpcClient) return [];
          try {
            const projects = await rpcClient.call("project.list", {}) as any[];
            return projects
              .filter((p: any) => p.name.toLowerCase().startsWith(prefix.toLowerCase()))
              .map((p: any) => ({
                value: p.name,
                label: p.name,
                description: p.path,
              }));
          } catch {
            return [];
          }
        },
      },
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

    // Autocomplete for slash commands
    const autocomplete = new CombinedAutocompleteProvider(slashCommands);
    this.editor.setAutocompleteProvider(autocomplete);

    // Loader — animated spinner, shown during agent work
    this.loader = new Loader(this.tui, chalk.cyan, chalk.dim, "");

    // Status line — one line below editor showing project + state
    const statusText = options.projectName
      ? chalk.dim(`  ${options.projectName} · ready`)
      : chalk.dim("  ready · type /help for commands");
    this.statusLine = new Text(statusText);

    // Layout: editor then status below
    this.tui.addChild(this.editor);
    this.tui.addChild(this.statusLine);
    this.tui.setFocus(this.editor);

    // Wire orchestrator events
    this.wireOrchestratorEvents();
  }

  start(): void {
    this.tui.start();
  }

  stop(): void {
    this.loader.stop();
    this.tui.stop();
  }

  shutdown(): void {
    this.stop();
    this.options.orchestrator.close();
    this.options.rpcClient?.close();
    process.exit(0);
  }

  /** Add a text message to the output (scrolls up into history). */
  private addOutput(text: string): void {
    // Insert a Text component before the editor
    const msg = new Text(text);
    const editorIndex = this.tui.children.indexOf(this.editor);
    if (editorIndex >= 0) {
      this.tui.children.splice(editorIndex, 0, msg);
    } else {
      this.tui.addChild(msg);
    }
    this.tui.requestRender();
  }

  private showLoader(message: string): void {
    this.loader.setMessage(message);
    // Insert loader before editor if not already there
    const editorIndex = this.tui.children.indexOf(this.editor);
    if (!this.tui.children.includes(this.loader) && editorIndex >= 0) {
      this.tui.children.splice(editorIndex, 0, this.loader);
    }
    this.loader.start();
    this.tui.requestRender();
  }

  private hideLoader(): void {
    this.loader.stop();
    const idx = this.tui.children.indexOf(this.loader);
    if (idx >= 0) this.tui.children.splice(idx, 1);
    this.tui.requestRender();
  }

  private updateStatus(text: string): void {
    this.statusLine.setText(chalk.dim(`  ${text}`));
    this.tui.requestRender();
  }

  private wireOrchestratorEvents(): void {
    this.options.orchestrator.setEvents({
      onAgentStart: (name) => {
        this.addOutput(formatAgentLabel(name));
        this.showLoader(name.replace(/_/g, " "));
      },
      onAgentOutput: (_name, text) => {
        this.addOutput(text);
      },
      onAgentEnd: (_name) => {
        this.hideLoader();
      },
      onText: (text) => {
        this.addOutput(text);
      },
      onToolCall: (name, args) => {
        const summary = JSON.stringify(args).slice(0, 60);
        this.addOutput(chalk.dim(`  → ${name}(${summary})`));
      },
      onError: (error) => {
        this.hideLoader();
        this.addOutput(chalk.red(`  ✗ ${error}`));
      },
    });
  }

  private async handleInput(text: string): Promise<void> {
    if (!text.trim()) return;
    this.editor.addToHistory(text);

    // Slash commands
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
      if (cmdResult.output.startsWith("__PROJECT__:")) {
        const newProjectDir = cmdResult.output.slice("__PROJECT__:".length);
        await this.switchProject(newProjectDir);
        return;
      }
      if (cmdResult.output) {
        this.addOutput(cmdResult.output);
      }
      return;
    }

    // Send to orchestrator
    if (this.processing) {
      this.addOutput(chalk.yellow("  Still processing..."));
      return;
    }

    this.processing = true;
    this.addOutput(chalk.dim(`> ${text}`));
    this.showLoader("thinking");
    this.updateStatus(`${this.options.projectName} · processing`);

    try {
      await this.options.orchestrator.processMessage(text);
    } catch (err: any) {
      this.addOutput(chalk.red(`  ✗ ${err.message}`));
    } finally {
      this.processing = false;
      this.hideLoader();
      this.updateStatus(`${this.options.projectName} · ready`);
    }
  }

  private async switchProject(newProjectDir: string): Promise<void> {
    this.showLoader("switching project");
    try {
      // Load the new project config to get name + question
      const rpcClient = this.options.rpcClient;
      if (!rpcClient) {
        this.addOutput(chalk.red("  Not connected to backend."));
        return;
      }

      const config = await rpcClient.call("project.load_config", {
        project_dir: newProjectDir,
      }) as any;

      const projectName = config.name || "Urika";

      // Reinitialize the orchestrator with the new project
      await this.options.orchestrator.initialize({
        projectName,
        question: config.question || "",
        mode: config.mode || "exploratory",
        dataDir: join(newProjectDir, "data"),
        experimentId: "",
        currentState: "Project switched. Awaiting user instructions.",
      });

      // Update app state
      this.options.projectDir = newProjectDir;
      this.options.projectName = projectName;
      this.updateStatus(`${projectName} · ready`);
      this.addOutput(chalk.cyan(`  Switched to project: ${projectName}`));
    } catch (err: any) {
      this.addOutput(chalk.red(`  Failed to switch project: ${err.message}`));
    } finally {
      this.hideLoader();
    }
  }
}
