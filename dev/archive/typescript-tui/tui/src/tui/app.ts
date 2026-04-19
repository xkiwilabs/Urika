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
  type Component,
  type EditorTheme,
  type MarkdownTheme,
  type SlashCommand as PiSlashCommand,
  type AutocompleteItem,
} from "@mariozechner/pi-tui";
import type { AgentEvent } from "@mariozechner/pi-agent-core";
import type { AssistantMessage } from "@mariozechner/pi-ai";
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

// ── Token/cost formatting (matches Pi's pattern) ──

function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1)}k`;
  if (n < 1000000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1000000).toFixed(1)}M`;
}

function formatCost(n: number): string {
  if (n < 0.01) return "$0.00";
  return `$${n.toFixed(2)}`;
}

function formatElapsed(startMs: number): string {
  const sec = Math.floor((Date.now() - startMs) / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m${sec % 60}s`;
}

/**
 * Dynamic footer that reads live session state on each render.
 * Matches Pi's FooterComponent pattern: project, model, tokens, cost.
 */
class FooterComponent implements Component {
  project = "";
  model = "";
  agent = "";
  tokensIn = 0;
  tokensOut = 0;
  cost = 0;
  startTime = 0;
  active = false;

  invalidate(): void {}

  render(width: number): string[] {
    const D = chalk.dim;
    const sep = D(" · ");

    // Left side: project + agent activity
    const left: string[] = [];
    if (this.project) left.push(chalk.cyan(this.project));

    if (this.active) {
      if (this.agent) left.push(chalk.yellow(this.agent.replace(/_/g, " ")));
      if (this.startTime) left.push(D(formatElapsed(this.startTime)));
    } else {
      left.push(D("ready"));
    }

    // Right side: model + tokens + cost
    const right: string[] = [];
    if (this.model) right.push(D(this.model));
    if (this.tokensIn > 0 || this.tokensOut > 0) {
      right.push(D(`↑${formatTokens(this.tokensIn)} ↓${formatTokens(this.tokensOut)}`));
    }
    if (this.cost > 0) right.push(chalk.green(formatCost(this.cost)));

    const leftStr = `  ${left.join(sep)}`;
    const rightStr = right.length > 0 ? `${right.join(sep)}  ` : "";

    // Pad between left and right
    const gap = Math.max(1, width - leftStr.length - rightStr.length + 20); // rough ANSI compensation
    const line = `${leftStr}${" ".repeat(Math.min(gap, width))}${rightStr}`;

    return [D("─".repeat(width)), line];
  }
}

export class UrikaApp {
  private tui: TUI;
  private chatContainer: Container;
  private statusContainer: Container;
  private editorContainer: Container;
  private editor: Editor;
  private footer: FooterComponent;
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

    // 5. Footer — dynamic, reads live state
    this.footer = new FooterComponent();
    this.footer.project = options.projectName;

    // Assemble layout
    this.tui.addChild(headerContainer);
    this.tui.addChild(this.chatContainer);
    this.tui.addChild(this.statusContainer);
    this.tui.addChild(this.editorContainer);
    this.tui.addChild(this.footer);
    this.tui.setFocus(this.editor);

    // Wire agent events
    this.setupSubscription();

    // Wire project switch
    this.options.orchestrator.onProjectSwitch = (info) => {
      this.options.projectDir = info.projectDir;
      this.options.projectName = info.projectName;
      this.footer.project = info.projectName;
      this.footer.active = false;
      this.rebuildAutocomplete();
      this.addChat(chalk.cyan(`Switched to project: ${info.projectName}`));
      this.setupSubscription();
    };
  }

  private get hasProject(): boolean {
    return this.options.projectDir !== "" && this.options.projectDir !== process.cwd();
  }

  private rebuildAutocomplete(): void {
    const rpcClient = this.options.rpcClient;
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

  // ── Output helpers ──

  private addChat(text: string, padding = 1): void {
    this.chatContainer.addChild(new Text(text, padding));
    this.tui.requestRender();
  }

  private addMarkdown(text: string): Markdown {
    const md = new Markdown(text, 1, 0, MARKDOWN_THEME);
    this.chatContainer.addChild(md);
    this.tui.requestRender();
    return md;
  }

  private showLoader(message: string): void {
    this.statusContainer.clear();
    this.loader = new CancellableLoader(this.tui, chalk.cyan, chalk.dim, message);
    this.loader.onAbort = () => {
      this.options.orchestrator.abort();
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

  private hideLoader(): void {
    this.loader?.stop();
    this.loader = null;
    this.statusContainer.clear();
    this.tui.requestRender();
  }

  // ── Agent event subscription ──

  private setupSubscription(): void {
    this.unsubscribe?.();
    const agent = this.options.orchestrator.getAgent();
    if (!agent) return;

    this.unsubscribe = agent.subscribe(async (event: AgentEvent) => {
      switch (event.type) {
        case "agent_start":
          this.footer.active = true;
          this.footer.startTime = Date.now();
          this.showLoader("Working...");
          break;

        case "message_start":
          // New LLM response — create streaming Markdown
          this.streamingText = "";
          this.streamingMarkdown = this.addMarkdown("");
          this.hideLoader();
          break;

        case "message_update": {
          const ame = event.assistantMessageEvent;
          if (ame.type === "text_delta") {
            this.streamingText += ame.delta;
            this.streamingMarkdown?.setText(this.streamingText);
            this.tui.requestRender();
          } else if (ame.type === "thinking_delta") {
            // Update loader with thinking indicator
            this.loader?.setMessage("Reasoning...");
          } else if (ame.type === "toolcall_start") {
            // LLM is deciding to call a tool
            this.showLoader("Selecting tool...");
          } else if (ame.type === "toolcall_end") {
            const toolName = ame.toolCall.name.replace(/_/g, " ");
            this.addChat(chalk.dim(`  → ${toolName}`));
          }

          // Update footer with usage from partial message
          if ("partial" in ame && ame.partial?.usage) {
            const u = ame.partial.usage;
            this.footer.tokensIn += 0; // partial doesn't have cumulative — updated on message_end
            this.footer.model = ame.partial.model || this.footer.model;
          }
          break;
        }

        case "message_end": {
          this.streamingMarkdown = null;
          this.streamingText = "";
          // Update footer with final usage
          const msg = event.message as AssistantMessage;
          if (msg && "usage" in msg && msg.usage) {
            this.footer.tokensIn += msg.usage.input;
            this.footer.tokensOut += msg.usage.output;
            this.footer.cost += msg.usage.cost?.total ?? 0;
            this.footer.model = msg.model || this.footer.model;
          }
          this.tui.requestRender();
          break;
        }

        case "tool_execution_start":
          this.footer.agent = event.toolName;
          this.showLoader(event.toolName.replace(/_/g, " "));
          break;

        case "tool_execution_end":
          this.footer.agent = "";
          this.hideLoader();
          if (event.isError) {
            this.addChat(chalk.red(`  ✗ ${event.toolName}: error`));
          }
          break;

        case "agent_end":
          this.hideLoader();
          this.processing = false;
          this.footer.active = false;
          this.footer.agent = "";
          this.tui.requestRender();
          break;
      }
    });
  }

  // ── Input handling ──

  private async handleInput(text: string): Promise<void> {
    if (!text.trim()) return;
    this.editor.addToHistory(text);

    // Slash commands
    const cmdResult = await handleSlashCommand(
      text,
      this.options.rpcClient,
      this.options.projectDir,
      { onOutput: (msg: string) => this.addChat(msg) },
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

    // Free text
    if (this.processing) {
      this.options.orchestrator.steer(text);
      this.addChat(chalk.dim(`> ${text} (steering)`));
      return;
    }

    this.processing = true;
    this.addChat(chalk.dim(`> ${text}`));
    // Loader and footer updates happen in agent_start event

    try {
      await this.options.orchestrator.processMessage(text);
    } catch (err: any) {
      this.addChat(chalk.red(`Error: ${err.message}`));
      this.processing = false;
      this.hideLoader();
      this.footer.active = false;
      this.tui.requestRender();
    }
  }

  // ── Project switching ──

  private async switchProject(newProjectDir: string): Promise<void> {
    this.showLoader("Switching project...");
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
      this.footer.project = projectName;
      this.footer.active = false;
      this.footer.tokensIn = 0;
      this.footer.tokensOut = 0;
      this.footer.cost = 0;
      this.rebuildAutocomplete();
      this.addChat(chalk.cyan(`Switched to project: ${projectName}`));
      this.setupSubscription();
    } catch (err: any) {
      this.addChat(chalk.red(`Failed to switch project: ${err.message}`));
    } finally {
      this.hideLoader();
    }
  }
}
