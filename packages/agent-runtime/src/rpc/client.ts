import { spawn, type ChildProcess } from "child_process";
import { createInterface, type Interface } from "readline";
import type { RpcRequest, RpcResponse } from "./types";
import { RpcError } from "./types";

export type NotificationListener = (
  method: string,
  params: Record<string, unknown>,
) => void;

export class RpcClient {
  private process: ChildProcess;
  private readline: Interface;
  private nextId = 1;
  private pending = new Map<
    number,
    {
      resolve: (value: unknown) => void;
      reject: (error: RpcError) => void;
    }
  >();
  private notificationListeners: Set<NotificationListener> = new Set();

  constructor(command: string, args: string[]) {
    this.process = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.readline = createInterface({ input: this.process.stdout! });
    this.readline.on("line", (line: string) => {
      if (!line.trim()) return;
      try {
        const msg = JSON.parse(line);

        // Notification (no `id` field) — dispatch to notification listeners
        if (msg.id === undefined && msg.method) {
          for (const listener of this.notificationListeners) {
            try {
              listener(msg.method, msg.params ?? {});
            } catch {
              // Never let a bad listener break the RPC loop
            }
          }
          return;
        }

        // Normal response — resolve pending call
        const resp: RpcResponse = msg;
        const handler = this.pending.get(resp.id);
        if (!handler) return;
        this.pending.delete(resp.id);
        if (resp.error) {
          handler.reject(new RpcError(resp.error.code, resp.error.message));
        } else {
          handler.resolve(resp.result);
        }
      } catch {
        // Ignore unparseable lines (e.g. stderr leaking to stdout)
      }
    });

    this.process.on("error", (err: Error) => {
      for (const [id, handler] of this.pending) {
        handler.reject(new RpcError(-32000, `RPC process error: ${err.message}`));
        this.pending.delete(id);
      }
    });

    this.process.on("exit", (code: number | null) => {
      for (const [id, handler] of this.pending) {
        handler.reject(new RpcError(-32001, `RPC process exited with code ${code}`));
        this.pending.delete(id);
      }
    });
  }

  async call(
    method: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    const id = this.nextId++;
    const req: RpcRequest = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin!.write(JSON.stringify(req) + "\n");
    });
  }

  /** Subscribe to JSON-RPC notifications from the server. */
  onNotification(listener: NotificationListener): () => void {
    this.notificationListeners.add(listener);
    return () => {
      this.notificationListeners.delete(listener);
    };
  }

  /** Kill the RPC subprocess forcefully. Use when /stop needs to abort a long-running operation. */
  kill(): void {
    try {
      this.process.kill("SIGKILL");
    } catch {
      // Already dead
    }
    this.readline.close();
    // Reject all pending calls
    for (const [, handler] of this.pending) {
      handler.reject(new RpcError(-32001, "RPC process killed"));
    }
    this.pending.clear();
  }

  /** Restart the RPC subprocess after a kill. */
  restart(command: string, args: string[]): void {
    this.process = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.readline = createInterface({ input: this.process.stdout! });
    this.readline.on("line", (line: string) => {
      if (!line.trim()) return;
      try {
        const msg = JSON.parse(line);
        if (msg.id === undefined && msg.method) {
          for (const listener of this.notificationListeners) {
            try { listener(msg.method, msg.params ?? {}); } catch {}
          }
          return;
        }
        const resp: RpcResponse = msg;
        const handler = this.pending.get(resp.id);
        if (!handler) return;
        this.pending.delete(resp.id);
        if (resp.error) {
          handler.reject(new RpcError(resp.error.code, resp.error.message));
        } else {
          handler.resolve(resp.result);
        }
      } catch {}
    });
    this.process.on("error", (err: Error) => {
      for (const [id, handler] of this.pending) {
        handler.reject(new RpcError(-32000, `RPC process error: ${err.message}`));
        this.pending.delete(id);
      }
    });
    this.process.on("exit", (code: number | null) => {
      for (const [id, handler] of this.pending) {
        handler.reject(new RpcError(-32001, `RPC process exited with code ${code}`));
        this.pending.delete(id);
      }
    });
  }

  close(): void {
    try {
      this.process.kill();
    } catch {}
    this.process.stdin!.end();
    this.readline.close();
  }
}
