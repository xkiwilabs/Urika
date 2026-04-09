import {
  TUI,
  Container,
  Editor,
  Text,
  Markdown,
  CancellableLoader,
  Spacer,
  TruncatedText,
  ProcessTerminal,
  CombinedAutocompleteProvider,
  type EditorTheme,
  type MarkdownTheme,
  type SlashCommand as PiSlashCommand,
  type AutocompleteItem,
} from "@mariozechner/pi-tui";
import type { AgentEvent } from "@mariozechner/pi-agent-core";
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

const MARKDOWN_THEME: MarkdownTheme = {
  heading: chalk.bold.cyan,
  link: chalk.cyan.underline,
  linkUrl: chalk.dim,
  code: chalk.yellow,
  codeBlock: chalk.white,
  codeBlockBorder: chalk.dim,
  quote: chalk.italic,
  quoteBorder: chalk.dim,
  hr: chalk.dim,
  listBullet: chalk.cyan,
  bold: chalk.bold,
  italic: chalk.italic,
  strikethrough: chalk.strikethrough,
  underline: chalk.underline,
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
  private footer: TruncatedText;
  private loader: CancellableLoader | null = null;
  private options: UrikaAppOptions;
  private processing = false;

  /** Accumulated text for the current streaming Markdown response. */
  private streamingText = "";
  /** The Markdown component currently being streamed to. */
  private streamingMarkdown: Markdown | null = null;

  /** Unsubscribe function for the current agent subscription. */
  private unsubscribe: (() => void) | null = null;

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

    // Autocomplete — rebuilt when project state changes
    this.rebuildAutocomplete();

    // 5. Footer — status line
    const footerText = options.projectName
      ? chalk.dim(`  ${options.projectName} · ready`)
      : chalk.dim("  ready · type /help for commands");
    this.footer = new TruncatedText(footerText);

    // Assemble layout — order determines visual stacking
    this.tui.addChild(headerContainer);
    this.tui.addChild(this.chatContainer);
    this.tui.addChild(this.statusContainer);
    this.tui.addChild(this.editorContainer);
    this.tui.addChild(this.footer);
    this.tui.setFocus(this.editor);

    // Wire orchestrator agent events
    this.setupSubscription();

    // Wire project switch callback
    this.options.orchestrator.onProjectSwitch = (info) => {
      this.options.projectDir = info.projectDir;
      this.options.projectName = info.projectName;
      this.updateFooter(`${info.projectName} · ready`);
      this.rebuildAutocomplete();
      this.addChat(chalk.cyan(`Switched to project: ${info.projectName}`));
      // Re-subscribe since initialize() recreates the Agent
      this.setupSubscription();
    };
  }

  /** Whether a project is currently loaded. */
  private get hasProject(): boolean {
    return this.options.projectDir !== "" && this.options.projectDir !== process.cwd();
  }

  /** Rebuild slash command autocomplete based on current state. */
  private rebuildAutocomplete(): void {
    const rpcClient = this.options.rpcClient;

    // Global commands — always available
    const commands: PiSlashCommand[] = [
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
      { name: "login", description: "Login to a provider (e.g. /login anthropic)" },
      { name: "logout", description: "Logout from a provider" },
      { name: "auth", description: "Show authentication status" },
      { name: "quit", description: "Exit Urika TUI" },
    ];

    // Project-level commands — only when a project is loaded
    if (this.hasProject) {
      commands.push(
        { name: "status", description: "Show project status" },
        { name: "results", description: "Show experiment results" },
        { name: "config", description: "Show project configuration" },
        { name: "pause", description: "Pause current run" },
        { name: "stop", description: "Stop current run" },
      );
    }

    this.editor.setAutocompleteProvider(new CombinedAutocompleteProvider(commands));
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
    this.unsubscribe?.();
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

  /** Add a Markdown-rendered message to chat. */
  private addMarkdown(text: string): Markdown {
    const md = new Markdown(text, 1, 0, MARKDOWN_THEME);
    this.chatContainer.addChild(md);
    this.tui.requestRender();
    return md;
  }

  /** Show the CancellableLoader in statusContainer. */
  private showLoader(message: string): void {
    this.statusContainer.clear();
    this.loader = new CancellableLoader(this.tui, chalk.cyan, chalk.dim, message);
    this.loader.onAbort = () => {
      this.options.orchestrator.abort();
      this.hideLoader();
      this.addChat(chalk.yellow("Aborted."));
      this.processing = false;
      this.updateFooter(`${this.options.projectName} · ready`);
    };
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
    // TruncatedText doesn't have setText — replace it
    this.tui.removeChild(this.footer);
    this.footer = new TruncatedText(chalk.dim(`  ${text}`));
    this.tui.addChild(this.footer);
    this.tui.requestRender();
  }

  // ── Agent event subscription ──

  /**
   * Subscribe to the orchestrator's pi-agent-core Agent events.
   * Handles streaming text, tool execution, and lifecycle events.
   */
  private setupSubscription(): void {
    // Unsubscribe from previous agent if any
    this.unsubscribe?.();

    const agent = this.options.orchestrator.getAgent();
    if (!agent) return;

    this.unsubscribe = agent.subscribe(async (event: AgentEvent, signal: AbortSignal) => {
      switch (event.type) {
        case "agent_start":
          // Run started — nothing to show yet
          break;

        case "message_start":
          // New LLM response starting — create a Markdown component
          this.streamingText = "";
          this.streamingMarkdown = this.addMarkdown("");
          this.hideLoader();
          break;

        case "message_update": {
          const ame = event.assistantMessageEvent;
          if (ame.type === "text_delta") {
            // Stream text to the Markdown component
            this.streamingText += ame.delta;
            this.streamingMarkdown?.setText(this.streamingText);
            this.tui.requestRender();
          }
          break;
        }

        case "message_end":
          // LLM response complete — finalize streaming
          this.streamingMarkdown = null;
          this.streamingText = "";
          break;

        case "tool_execution_start":
          // Show loader with tool name
          this.showLoader(event.toolName.replace(/_/g, " "));
          this.addChat(
            chalk.dim(`  ${formatAgentLabel(event.toolName)}`),
          );
          break;

        case "tool_execution_end":
          // Tool finished — hide loader, show brief result
          this.hideLoader();
          if (event.isError) {
            this.addChat(chalk.red(`  Tool error: ${event.toolName}`));
          }
          break;

        case "agent_end":
          // Entire run done
          this.hideLoader();
          this.processing = false;
          this.updateFooter(`${this.options.projectName} · ready`);
          break;
      }
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
      {
        onOutput: (msg: string) => this.addChat(msg),
      },
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
      // If agent is running, steer it instead of blocking
      this.options.orchestrator.steer(text);
      this.addChat(chalk.dim(`> ${text} (steering)`));
      return;
    }

    this.processing = true;
    this.addChat(chalk.dim(`> ${text}`));
    this.showLoader("thinking");
    this.updateFooter(`${this.options.projectName} · processing`);

    try {
      await this.options.orchestrator.processMessage(text);
    } catch (err: any) {
      this.addChat(chalk.red(`Error: ${err.message}`));
      this.processing = false;
      this.hideLoader();
      this.updateFooter(`${this.options.projectName} · ready`);
    }
    // Note: processing=false and footer update now happen in agent_end event
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
      this.rebuildAutocomplete(); // Add project-level commands
      this.addChat(chalk.cyan(`Switched to project: ${projectName}`));
      // Re-subscribe since initialize() recreates the Agent
      this.setupSubscription();
    } catch (err: any) {
      this.addChat(chalk.red(`Failed to switch project: ${err.message}`));
    } finally {
      this.hideLoader();
    }
  }
}
