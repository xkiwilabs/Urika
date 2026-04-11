import chalk from "chalk";
import { type Component, type TUI, visibleWidth, truncateToWidth } from "@mariozechner/pi-tui";

/** Descriptive words that rotate during thinking. */
const THINKING_VERBS = [
  "Thinking",
  "Reasoning",
  "Analyzing",
  "Writing",
  "Contemplating",
  "Processing",
  "Exploring",
  "Evaluating",
  "Considering",
  "Reviewing",
];

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/** Spinner interval — 160ms (half the speed of pi-tui's default 80ms). */
const SPINNER_INTERVAL = 160;

/** How often to rotate the verb (in ms). */
const VERB_INTERVAL = 4000;

/**
 * ThinkingLoader — a slower spinner with rotating descriptive words.
 *
 * Shows: "⠋ Thinking..." → "⠙ Reasoning..." → "⠹ Analyzing..." etc.
 *
 * When a specific tool/agent is provided via setMessage(), it shows that
 * instead of the rotating verb.
 */
export class ThinkingLoader implements Component {
  private ui: TUI;
  private spinnerFrame = 0;
  private verbIndex = 0;
  private spinnerInterval: ReturnType<typeof setInterval> | null = null;
  private verbInterval: ReturnType<typeof setInterval> | null = null;
  private customMessage = "";
  private aborted = false;

  /** Called when user presses Escape. */
  onAbort?: () => void;

  constructor(ui: TUI) {
    this.ui = ui;
  }

  /** Set a specific message (overrides rotating verbs). Empty string = use verbs. */
  setMessage(message: string): void {
    this.customMessage = message;
  }

  start(): void {
    this.aborted = false;
    this.spinnerFrame = 0;
    this.verbIndex = Math.floor(Math.random() * THINKING_VERBS.length);

    this.spinnerInterval = setInterval(() => {
      this.spinnerFrame = (this.spinnerFrame + 1) % SPINNER_FRAMES.length;
      this.ui.requestRender();
    }, SPINNER_INTERVAL);

    this.verbInterval = setInterval(() => {
      if (!this.customMessage) {
        this.verbIndex = (this.verbIndex + 1) % THINKING_VERBS.length;
      }
    }, VERB_INTERVAL);
  }

  stop(): void {
    if (this.spinnerInterval) {
      clearInterval(this.spinnerInterval);
      this.spinnerInterval = null;
    }
    if (this.verbInterval) {
      clearInterval(this.verbInterval);
      this.verbInterval = null;
    }
  }

  invalidate(): void {}

  handleInput?(data: string): void {
    // Check for Escape key
    if (data === "\x1b" || data === "\x1b\x1b") {
      this.aborted = true;
      this.stop();
      this.onAbort?.();
    }
  }

  render(width: number): string[] {
    const frame = chalk.cyan(SPINNER_FRAMES[this.spinnerFrame]);
    const verb = this.customMessage || `${THINKING_VERBS[this.verbIndex]}...`;
    const text = `${frame} ${chalk.dim(verb)}`;
    return ["", truncateToWidth(text, width)];
  }
}
