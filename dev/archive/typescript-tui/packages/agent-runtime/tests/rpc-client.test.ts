import { describe, expect, it } from "bun:test";
import { RpcClient } from "../src/rpc/client";

describe("RpcClient", () => {
  it("sends request and receives response from Python server", async () => {
    const client = new RpcClient("python", ["-m", "urika.rpc"]);
    try {
      const result = await client.call("tools.list", {});
      expect(Array.isArray(result)).toBe(true);
    } finally {
      client.close();
    }
  });

  it("handles multiple sequential requests", async () => {
    const client = new RpcClient("python", ["-m", "urika.rpc"]);
    try {
      const r1 = await client.call("tools.list", {});
      const r2 = await client.call("tools.list", {});
      expect(Array.isArray(r1)).toBe(true);
      expect(Array.isArray(r2)).toBe(true);
    } finally {
      client.close();
    }
  });

  it("handles method not found error", async () => {
    const client = new RpcClient("python", ["-m", "urika.rpc"]);
    try {
      await client.call("nonexistent.method", {});
      expect(true).toBe(false); // should not reach
    } catch (e: unknown) {
      expect((e as { code: number }).code).toBe(-32601);
    } finally {
      client.close();
    }
  });
});
