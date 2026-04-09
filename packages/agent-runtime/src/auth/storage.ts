import { readFileSync, writeFileSync, mkdirSync, existsSync, unlinkSync } from "fs";
import { join } from "path";
import { homedir } from "os";

const AUTH_DIR = join(homedir(), ".urika", "auth");
const CREDENTIALS_FILE = join(AUTH_DIR, "credentials.json");

export interface StoredCredentials {
  [provider: string]: {
    type: "oauth";
    refresh: string;
    access: string;
    expires: number;
  };
}

/**
 * Load all stored OAuth credentials from disk.
 * Returns an empty object if the file doesn't exist or is corrupt.
 */
export function loadCredentials(dir?: string): StoredCredentials {
  const file = dir ? join(dir, "credentials.json") : CREDENTIALS_FILE;
  try {
    return JSON.parse(readFileSync(file, "utf-8"));
  } catch {
    return {};
  }
}

/**
 * Save all OAuth credentials to disk.
 * Creates the auth directory if it doesn't exist.
 */
export function saveCredentials(creds: StoredCredentials, dir?: string): void {
  const targetDir = dir ?? AUTH_DIR;
  const file = join(targetDir, "credentials.json");
  mkdirSync(targetDir, { recursive: true });
  writeFileSync(file, JSON.stringify(creds, null, 2), { mode: 0o600 });
}

/**
 * Get credentials for a single provider, or null if not stored.
 */
export function getProviderCredentials(
  provider: string,
  dir?: string,
): StoredCredentials[string] | null {
  const creds = loadCredentials(dir);
  return creds[provider] ?? null;
}

/**
 * Remove credentials for a single provider.
 */
export function removeProviderCredentials(provider: string, dir?: string): void {
  const creds = loadCredentials(dir);
  delete creds[provider];
  saveCredentials(creds, dir);
}

/**
 * Remove all stored credentials (logout all providers).
 */
export function clearCredentials(dir?: string): void {
  const file = dir ? join(dir, "credentials.json") : CREDENTIALS_FILE;
  try {
    unlinkSync(file);
  } catch {
    // File didn't exist — nothing to clear
  }
}

/**
 * List all providers that have stored credentials.
 */
export function listProviders(dir?: string): string[] {
  return Object.keys(loadCredentials(dir));
}
