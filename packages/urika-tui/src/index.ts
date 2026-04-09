/**
 * @urika/urika-tui — Urika-specific TUI entry point.
 *
 * Wires Urika's runtime.toml config, ASCII header, slash command
 * handlers, and prompt variable provider into the generic
 * @urika/agent-runtime framework.
 */

import { createApp } from "@urika/agent-runtime";
import { renderHeader } from "./header";
import { commandHandlers } from "./commands";
import { getPromptVariables, onProjectSwitch } from "./context";
import { resolve } from "path";

async function main() {
  const configPath = resolve(
    new URL("../runtime.toml", import.meta.url).pathname,
  );

  const app = await createApp({
    configPath,
    renderHeader,
    commandHandlers,
    getPromptVariables,
    onProjectSwitch,
  });

  process.on("SIGINT", () => {
    app.stop();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    app.stop();
    process.exit(0);
  });

  app.start();
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
