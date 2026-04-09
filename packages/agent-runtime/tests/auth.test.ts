import { describe, expect, it, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, readFileSync, existsSync, statSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import {
  loadCredentials,
  saveCredentials,
  getProviderCredentials,
  removeProviderCredentials,
  clearCredentials,
  listProviders,
  type StoredCredentials,
} from "../src/auth/storage";

describe("auth/storage", () => {
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "urika-auth-test-"));
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("returns empty object when no credentials file exists", () => {
    const creds = loadCredentials(tempDir);
    expect(creds).toEqual({});
  });

  it("saves and loads credentials", () => {
    const creds: StoredCredentials = {
      anthropic: {
        type: "oauth",
        refresh: "refresh-token-abc",
        access: "access-token-xyz",
        expires: Date.now() + 3600000,
      },
    };

    saveCredentials(creds, tempDir);
    const loaded = loadCredentials(tempDir);

    expect(loaded).toEqual(creds);
    expect(loaded.anthropic.refresh).toBe("refresh-token-abc");
    expect(loaded.anthropic.access).toBe("access-token-xyz");
  });

  it("saves multiple providers", () => {
    const creds: StoredCredentials = {
      anthropic: {
        type: "oauth",
        refresh: "r1",
        access: "a1",
        expires: 1000,
      },
      "github-copilot": {
        type: "oauth",
        refresh: "r2",
        access: "a2",
        expires: 2000,
      },
    };

    saveCredentials(creds, tempDir);
    const loaded = loadCredentials(tempDir);

    expect(Object.keys(loaded)).toHaveLength(2);
    expect(loaded.anthropic.refresh).toBe("r1");
    expect(loaded["github-copilot"].refresh).toBe("r2");
  });

  it("overwrites existing credentials on save", () => {
    saveCredentials({
      anthropic: { type: "oauth", refresh: "old", access: "old", expires: 0 },
    }, tempDir);

    saveCredentials({
      anthropic: { type: "oauth", refresh: "new", access: "new", expires: 999 },
    }, tempDir);

    const loaded = loadCredentials(tempDir);
    expect(loaded.anthropic.refresh).toBe("new");
    expect(loaded.anthropic.expires).toBe(999);
  });

  it("sets restrictive file permissions (0600)", () => {
    saveCredentials({
      anthropic: { type: "oauth", refresh: "r", access: "a", expires: 0 },
    }, tempDir);

    const file = join(tempDir, "credentials.json");
    const stats = statSync(file);
    // 0o600 = owner read+write only = 0o100600
    const mode = stats.mode & 0o777;
    expect(mode).toBe(0o600);
  });

  it("writes valid JSON", () => {
    saveCredentials({
      anthropic: { type: "oauth", refresh: "r", access: "a", expires: 42 },
    }, tempDir);

    const file = join(tempDir, "credentials.json");
    const raw = readFileSync(file, "utf-8");
    const parsed = JSON.parse(raw);
    expect(parsed.anthropic.expires).toBe(42);
  });

  describe("getProviderCredentials", () => {
    it("returns credentials for an existing provider", () => {
      saveCredentials({
        anthropic: { type: "oauth", refresh: "r", access: "a", expires: 100 },
      }, tempDir);

      const cred = getProviderCredentials("anthropic", tempDir);
      expect(cred).not.toBeNull();
      expect(cred!.refresh).toBe("r");
    });

    it("returns null for a missing provider", () => {
      saveCredentials({
        anthropic: { type: "oauth", refresh: "r", access: "a", expires: 100 },
      }, tempDir);

      const cred = getProviderCredentials("openai", tempDir);
      expect(cred).toBeNull();
    });
  });

  describe("removeProviderCredentials", () => {
    it("removes a single provider", () => {
      saveCredentials({
        anthropic: { type: "oauth", refresh: "r1", access: "a1", expires: 1 },
        "github-copilot": { type: "oauth", refresh: "r2", access: "a2", expires: 2 },
      }, tempDir);

      removeProviderCredentials("anthropic", tempDir);
      const loaded = loadCredentials(tempDir);

      expect(loaded.anthropic).toBeUndefined();
      expect(loaded["github-copilot"]).toBeDefined();
    });

    it("is a no-op for a missing provider", () => {
      saveCredentials({
        anthropic: { type: "oauth", refresh: "r", access: "a", expires: 1 },
      }, tempDir);

      removeProviderCredentials("openai", tempDir);
      const loaded = loadCredentials(tempDir);
      expect(loaded.anthropic).toBeDefined();
    });
  });

  describe("clearCredentials", () => {
    it("deletes the credentials file", () => {
      saveCredentials({
        anthropic: { type: "oauth", refresh: "r", access: "a", expires: 1 },
      }, tempDir);

      const file = join(tempDir, "credentials.json");
      expect(existsSync(file)).toBe(true);

      clearCredentials(tempDir);
      expect(existsSync(file)).toBe(false);
    });

    it("does not throw when file does not exist", () => {
      expect(() => clearCredentials(tempDir)).not.toThrow();
    });
  });

  describe("listProviders", () => {
    it("returns empty array when no credentials", () => {
      expect(listProviders(tempDir)).toEqual([]);
    });

    it("lists all stored provider IDs", () => {
      saveCredentials({
        anthropic: { type: "oauth", refresh: "r1", access: "a1", expires: 1 },
        "github-copilot": { type: "oauth", refresh: "r2", access: "a2", expires: 2 },
      }, tempDir);

      const providers = listProviders(tempDir);
      expect(providers).toContain("anthropic");
      expect(providers).toContain("github-copilot");
      expect(providers).toHaveLength(2);
    });
  });
});
