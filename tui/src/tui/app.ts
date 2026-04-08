import {
  TUI,
  Container,
  Editor,
  Text,
  Loader,
  Spacer,
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

/**
 * UrikaApp — follows Pi's container hierarchy pattern:
 *
 *   TUI
 *     +-- headerContainer    (static header, shown once)
 *     +-- chatContainer      (messages grow here)
 *     +-- statusContainer    (loader/spinner when processing)
 *     +-- editorContainer    (editor OR selector, swapped as needed)
 *     +-- footer             (project name, state)
 */
export class UrikaApp {
  private tui: TUI;
  private chatContainer: Container;
  private statusContainer: Container;
  private editorContainer: Container;
  private editor: Editor;
  private footer: Text;
  private loader: Loader | null = null;
  private options: UrikaAppOptions;
  private processing = false;

  constructor(options: UrikaAppOptions) {
    this.options = options;
    const terminal = new ProcessTerminal();
    this.tui = new TUI(terminal, true);

    // 1. Header container
    const headerContainer = new Container();
    const headerLines = renderHeader(options.projectName, options.version);
    headerContainer.addChild(new Text(headerLines.join("\n")));
    headerContainer.addChild(new Spacer(1));

    // 2. Chat container — all messages go here
    this.chatContainer = new Container();

    // 3. Status container — loader appears here during agent work
    this.statusContainer = new Container();

    // 4. Editor container — wraps editor, can be swapped for selectors
    this.editorContainer = new Container();
    this.editor = new Editor(this.tui, EDITOR_THEME);
    this.editor.onSubmit = async (text: string) => {
      await this.handleInput(text);
    };
    this.editorContainer.addChild(this.editor);

    // Autocomplete for slash commands
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
              .map((p: any) => ({ value: p.name, label: p.name, description: p.path }));
          } catch { return []; }
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
    const autocomplete = new CombinedAutocompleteProvider(slashCommands);
    this.editor.setAutocompleteProvider(autocomplete);

    // 5. Footer — status line
    const footerText = options.projectName
      ? chalk.dim(`  ${options.projectName} · ready`)
      : chalk.dim("  ready · type /help for commands");
    this.footer = new Text(footerText);

    // Assemble layout — order determines visual stacking
    this.tui.addChild(headerContainer);
    this.tui.addChild(this.chatContainer);
    this.tui.addChild(this.statusContainer);
    this.tui.addChild(this.editorContainer);
    this.tui.addChild(this.footer);
    this.tui.setFocus(this.editor);

    // Wire orchestrator events
    this.wireOrchestratorEvents();
  }

  start(): void {
    this.tui.start();
  }

  stop(): void {
    this.loader?.stop();
    this.tui.stop();
  }

  shutdown(): void {
    this.stop();
    this.options.orchestrator.close();
    this.options.rpcClient?.close();
    process.exit(0);
  }

  // ── Output helpers (following Pi's pattern) ──

  /** Add a message to chat (scrolls up naturally). */
  private addChat(text: string, padding = 1): void {
    this.chatContainer.addChild(new Text(text, padding));
    this.tui.requestRender();
  }

  /** Show the loader spinner in statusContainer. */
  private showLoader(message: string): void {
    this.statusContainer.clear();
    this.loader = new Loader(this.tui, chalk.cyan, chalk.dim, message);
    this.statusContainer.addChild(this.loader);
    this.loader.start();
    this.tui.requestRender();
  }

  /** Hide the loader spinner. */
  private hideLoader(): void {
    this.loader?.stop();
    this.loader = null;
    this.statusContainer.clear();
    this.tui.requestRender();
  }

  /** Update the footer status text. */
  private updateFooter(text: string): void {
    this.footer.setText(chalk.dim(`  ${text}`));
    this.tui.requestRender();
  }

  // ── Event wiring ──

  private wireOrchestratorEvents(): void {
    this.options.orchestrator.setEvents({
      onAgentStart: (name) => {
        this.addChat(formatAgentLabel(name));
        this.showLoader(name.replace(/_/g, " "));
      },
      onAgentOutput: (_name, text) => {
        this.addChat(text);
      },
      onAgentEnd: (_name) => {
        this.hideLoader();
      },
      onText: (text) => {
        this.addChat(text);
      },
      onToolCall: (name, args) => {
        const summary = JSON.stringify(args).slice(0, 60);
        this.addChat(chalk.dim(`→ ${name}(${summary})`));
      },
      onError: (error) => {
        this.hideLoader();
        this.addChat(chalk.red(`✗ ${error}`));
      },
    });
  }

  // ── Input handling ──

  private async handleInput(text: string): Promise<void> {
    if (!text.trim()) return;
    this.editor.addToHistory(text);

    // Slash commands — handled directly, don't go to orchestrator
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
        this.addChat(cmdResult.output);
      }
      return;
    }

    // Free text — send to orchestrator
    if (this.processing) {
      this.addChat(chalk.yellow("Still processing..."));
      return;
    }

    this.processing = true;
    this.addChat(chalk.dim(`> ${text}`));
    this.showLoader("thinking");
    this.updateFooter(`${this.options.projectName} · processing`);

    try {
      await this.options.orchestrator.processMessage(text);
    } catch (err: any) {
      this.addChat(chalk.red(`✗ ${err.message}`));
    } finally {
      this.processing = false;
      this.hideLoader();
      this.updateFooter(`${this.options.projectName} · ready`);
    }
  }

  // ── Project switching ──

  private async switchProject(newProjectDir: string): Promise<void> {
    this.showLoader("switching project");
    try {
      const rpcClient = this.options.rpcClient;
      if (!rpcClient) {
        this.addChat(chalk.red("Not connected to backend."));
        return;
      }

      const config = await rpcClient.call("project.load_config", {
        project_dir: newProjectDir,
      }) as any;

      const projectName = config.name || "Urika";

      await this.options.orchestrator.initialize({
        projectName,
        question: config.question || "",
        mode: config.mode || "exploratory",
        dataDir: join(newProjectDir, "data"),
        experimentId: "",
        currentState: "Project switched. Awaiting user instructions.",
      });

      this.options.projectDir = newProjectDir;
      this.options.projectName = projectName;
      this.updateFooter(`${projectName} · ready`);
      this.addChat(chalk.cyan(`Switched to project: ${projectName}`));
    } catch (err: any) {
      this.addChat(chalk.red(`Failed to switch project: ${err.message}`));
    } finally {
      this.hideLoader();
    }
  }
}
