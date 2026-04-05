import { spawn, type ChildProcess } from "child_process";
import { createInterface, type Interface } from "readline";
import type { RpcRequest, RpcResponse } from "./types";
import { RpcError } from "./types";

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

  constructor(command: string, args: string[]) {
    this.process = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.readline = createInterface({ input: this.process.stdout! });
    this.readline.on("line", (line: string) => {
      if (!line.trim()) return;
      const resp: RpcResponse = JSON.parse(line);
      const handler = this.pending.get(resp.id);
      if (!handler) return;
      this.pending.delete(resp.id);
      if (resp.error) {
        handler.reject(new RpcError(resp.error.code, resp.error.message));
      } else {
        handler.resolve(resp.result);
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

  close(): void {
    this.process.stdin!.end();
    this.readline.close();
  }
}
