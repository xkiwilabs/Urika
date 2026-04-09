import {
  TUI,
  Container,
  Editor,
  Text,
  Markdown,
  CancellableLoader,
  Spacer,
  ProcessTerminal,
  CombinedAutocompleteProvider,
  type EditorTheme,
  type MarkdownTheme,
  type SlashCommand as PiSlashCommand,
  type AutocompleteItem,
} from "@mariozechner/pi-tui";
import chalk from "chalk";
import { FooterComponent, type FooterState } from "./footer";
import type { RpcClient } from "../rpc/client";
import type { CommandDeclaration } from "../runtime/types";

// ── Themes ──

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

// ── Context passed to command handlers ──

export interface CommandContext {
  projectName: string;
  projectDir: string;
  rpcClient: RpcClient | null;
  addChat: (text: string) => void;
  showLoader: (message: string) => void;
  hideLoader: () => void;
}

// ── Subscription handlers the host wires up ──

export interface SubscriptionHandlers {
  addChat: (text: string) => void;
  addMarkdown: (text: string) => Markdown;
  showLoader: (message: string) => void;
  hideLoader: () => void;
  updateFooter: (data: Partial<FooterState>) => void;
  requestRender: () => void;
}

// ── App options — everything injected, nothing hardcoded ──

export interface AgentTuiAppOptions {
  projectName: string;
  version: string;
  projectDir: string;

  /** Render the header — returns string[] of lines */
  renderHeader: (projectName: string, version: string) => string[];

  /** Slash command declarations (from runtime.toml) */
  commands: CommandDeclaration[];

  /** Custom command handlers — return output string, or special signals */
  commandHandlers: Record<string, (args: string, ctx: CommandContext) => Promise<string>>;

  /** RPC client for host system calls */
  rpcClient: RpcClient | null;

  /**
   * Subscribe to runtime events for streaming.
   * Called once at startup and again on project switch.
   * Returns an unsubscribe function.
   */
  onSetupSubscription: (handlers: SubscriptionHandlers) => () => void;

  /** Process user message (send to orchestrator) */
  onMessage: (text: string) => Promise<void>;

  /** Steer the orchestrator mid-run */
  onSteer: (text: string) => void;

  /** Abort the current run */
  onAbort: () => void;

  /** Called when the app is shutting down */
  onShutdown?: () => void;
}

// ── Special command return signals ──

/** Return from a command handler to quit the app */
export const CMD_QUIT = "__QUIT__";
/** Return from a command handler to switch project: `__PROJECT__:/path/to/dir` */
export const CMD_PROJECT_PREFIX = "__PROJECT__:";

/**
 * Generic agent TUI application.
 *
 * Renders a pi-tui terminal interface with:
 * - Configurable header
 * - Streaming markdown chat area
 * - Cancellable loader for agent activity
 * - Editor with slash-command autocomplete
 * - Dynamic footer (project, agent, model, tokens, cost)
 *
 * All host-system specifics are injected via AgentTuiAppOptions.
 */
export class AgentTuiApp {
  private tui: TUI;
  private chatContainer: Container;
  private statusContainer: Container;
  private editorContainer: Container;
  private editor: Editor;
  private footer: FooterComponent;
  private loader: CancellableLoader | null = null;
  private options: AgentTuiAppOptions;
  private processing = false;

  /** Accumulated text for the current streaming Markdown response. */
  private streamingText = "";
  /** The Markdown component currently being streamed to. */
  private streamingMarkdown: Markdown | null = null;
  /** Unsubscribe function for the current event subscription. */
  private unsubscribe: (() => void) | null = null;

  constructor(options: AgentTuiAppOptions) {
    this.options = options;
    const terminal = new ProcessTerminal();
    this.tui = new TUI(terminal, true);

    // 1. Header container
    const headerContainer = new Container();
    const headerLines = options.renderHeader(options.projectName, options.version);
    headerContainer.addChild(new Text(headerLines.join("\n")));
    headerContainer.addChild(new Spacer(1));

    // 2. Chat container
    this.chatContainer = new Container();

    // 3. Status container (loader)
    this.statusContainer = new Container();

    // 4. Editor container
    this.editorContainer = new Container();
    this.editor = new Editor(this.tui, EDITOR_THEME);
    this.editor.onSubmit = async (text: string) => {
      await this.handleInput(text);
    };
    this.editorContainer.addChild(this.editor);

    // Autocomplete
    this.rebuildAutocomplete();

    // 5. Footer
    this.footer = new FooterComponent();
    this.footer.project = options.projectName;

    // Assemble layout
    this.tui.addChild(headerContainer);
    this.tui.addChild(this.chatContainer);
    this.tui.addChild(this.statusContainer);
    this.tui.addChild(this.editorContainer);
    this.tui.addChild(this.footer);
    this.tui.setFocus(this.editor);

    // Wire event subscription
    this.setupSubscription();
  }

  // ── Public API ──

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
    this.options.onShutdown?.();
    process.exit(0);
  }

  /** Get the footer component for direct state inspection. */
  getFooter(): FooterComponent {
    return this.footer;
  }

  /** Trigger autocomplete rebuild (e.g. after project switch). */
  rebuildAutocomplete(): void {
    const { commands, rpcClient } = this.options;

    const piCommands: PiSlashCommand[] = commands.map((cmd) => {
      const piCmd: PiSlashCommand = {
        name: cmd.name,
        description: cmd.description,
      };

      // Wire up RPC-based autocomplete if declared
      if (cmd.autocomplete_rpc && rpcClient) {
        const rpcMethod = cmd.autocomplete_rpc;
        piCmd.getArgumentCompletions = async (prefix: string): Promise<AutocompleteItem[]> => {
          try {
            const items = (await rpcClient.call(rpcMethod, { prefix })) as any[];
            return items.map((item: any) => ({
              value: item.value ?? item.name,
              label: item.label ?? item.name,
              description: item.description ?? item.path ?? "",
            }));
          } catch {
            return [];
          }
        };
      }

      return piCmd;
    });

    this.editor.setAutocompleteProvider(new CombinedAutocompleteProvider(piCommands));
  }

  /** Add a chat message to the chat area. */
  addChat(text: string, padding = 1): void {
    this.chatContainer.addChild(new Text(text, padding));
    this.tui.requestRender();
  }

  /** Add a markdown block to the chat area. */
  addMarkdown(text: string): Markdown {
    const md = new Markdown(text, 1, 0, MARKDOWN_THEME);
    this.chatContainer.addChild(md);
    this.tui.requestRender();
    return md;
  }

  /** Update project context (e.g. after project switch). */
  updateProject(projectName: string, projectDir: string): void {
    this.options.projectName = projectName;
    this.options.projectDir = projectDir;
    this.footer.project = projectName;
    this.footer.active = false;
    this.footer.resetUsage();
    this.rebuildAutocomplete();
    this.setupSubscription();
  }

  // ── Loader ──

  showLoader(message: string): void {
    this.statusContainer.clear();
    this.loader = new CancellableLoader(this.tui, chalk.cyan, chalk.dim, message);
    this.loader.onAbort = () => {
      this.options.onAbort();
      this.hideLoader();
      this.addChat(chalk.yellow("Aborted."));
      this.processing = false;
      this.footer.active = false;
      this.tui.requestRender();
    };
    this.statusContainer.addChild(this.loader);
    this.loader.start();
    this.tui.requestRender();
  }

  hideLoader(): void {
    this.loader?.stop();
    this.loader = null;
    this.statusContainer.clear();
    this.tui.requestRender();
  }

  /** Update the loader message (e.g. "Reasoning..."). */
  setLoaderMessage(message: string): void {
    this.loader?.setMessage(message);
  }

  // ── Event subscription ──

  setupSubscription(): void {
    this.unsubscribe?.();

    this.unsubscribe = this.options.onSetupSubscription({
      addChat: (text: string) => this.addChat(text),
      addMarkdown: (text: string) => this.addMarkdown(text),
      showLoader: (message: string) => this.showLoader(message),
      hideLoader: () => this.hideLoader(),
      updateFooter: (data: Partial<FooterState>) => this.footer.update(data),
      requestRender: () => this.tui.requestRender(),
    });
  }

  // ── Input handling ──

  private async handleInput(text: string): Promise<void> {
    if (!text.trim()) return;
    this.editor.addToHistory(text);

    // Slash commands
    if (text.startsWith("/")) {
      const spaceIdx = text.indexOf(" ");
      const cmdName = spaceIdx === -1 ? text.slice(1) : text.slice(1, spaceIdx);
      const cmdArgs = spaceIdx === -1 ? "" : text.slice(spaceIdx + 1).trim();

      // Built-in commands (framework-level)
      if (cmdName === "quit" || cmdName === "exit" || cmdName === "q") {
        this.shutdown();
        return;
      }
      if (cmdName === "help") {
        const lines = this.options.commands.map(
          (c) => `  /${c.name.padEnd(14)} ${c.description}`,
        );
        this.addChat("\n  Commands:\n\n" + lines.join("\n") + "\n\n  Everything else is sent to the orchestrator.\n");
        return;
      }
      if (cmdName === "login") {
        const { handleLogin } = await import("../auth/login");
        try {
          this.addChat("  Logging in...");
          await handleLogin(cmdArgs, (msg: string) => this.addChat(msg));
        } catch (err: any) {
          this.addChat(chalk.red(`  Login failed: ${err.message}`));
        }
        return;
      }
      if (cmdName === "logout") {
        const { handleLogout } = await import("../auth/login");
        this.addChat(handleLogout(cmdArgs));
        return;
      }
      if (cmdName === "auth") {
        const { handleAuthStatus } = await import("../auth/login");
        this.addChat(handleAuthStatus());
        return;
      }

      // Host-specific command handlers
      const handler = this.options.commandHandlers[cmdName];
      if (handler) {
        const ctx: CommandContext = {
          projectName: this.options.projectName,
          projectDir: this.options.projectDir,
          rpcClient: this.options.rpcClient,
          addChat: (msg: string) => this.addChat(msg),
          showLoader: (msg: string) => this.showLoader(msg),
          hideLoader: () => this.hideLoader(),
        };

        try {
          const result = await handler(cmdArgs, ctx);

          if (result === CMD_QUIT) {
            this.shutdown();
            return;
          }

          if (result.startsWith(CMD_PROJECT_PREFIX)) {
            const newProjectDir = result.slice(CMD_PROJECT_PREFIX.length);
            this.updateProject(
              newProjectDir.split("/").pop() || "project",
              newProjectDir,
            );
            this.addChat(chalk.cyan(`Switched to project: ${this.options.projectName}`));
            return;
          }

          if (result) {
            this.addChat(result);
          }
        } catch (err: any) {
          this.addChat(chalk.red(`Command error: ${err.message}`));
        }
        return;
      }

      // No handler found for this slash command
      this.addChat(chalk.dim(`  Unknown command: /${cmdName}. Type /help for commands.`));
      return;
    }

    // Free text — if already processing, steer
    if (this.processing) {
      this.options.onSteer(text);
      this.addChat(chalk.dim(`> ${text} (steering)`));
      return;
    }

    // Send to orchestrator
    this.processing = true;
    this.addChat(chalk.dim(`> ${text}`));

    try {
      await this.options.onMessage(text);
    } catch (err: any) {
      this.addChat(chalk.red(`Error: ${err.message}`));
    } finally {
      this.processing = false;
      this.hideLoader();
      this.footer.active = false;
      this.tui.requestRender();
    }
  }
}
