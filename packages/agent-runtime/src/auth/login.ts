import {
  getOAuthProvider,
  getOAuthProviders,
  getOAuthApiKey,
  type OAuthCredentials,
} from "@mariozechner/pi-ai/oauth";
import { loadCredentials, saveCredentials } from "./storage";

/** Supported provider IDs for display and validation. */
export function getSupportedProviders(): { id: string; name: string }[] {
  return getOAuthProviders().map((p) => ({ id: p.id, name: p.name }));
}

export interface LoginCallbacks {
  onUrl: (url: string, instructions?: string) => void;
  onPrompt: (message: string) => Promise<string>;
  onProgress: (message: string) => void;
}

/**
 * Run the OAuth login flow for a provider.
 * Opens the browser, waits for the callback, and stores credentials.
 *
 * Returns true on success, false if the provider is not found.
 * Throws on flow errors (network, user cancellation, etc.).
 */
export async function loginProvider(
  provider: string,
  callbacks: LoginCallbacks,
): Promise<boolean> {
  const oauthProvider = getOAuthProvider(provider);
  if (!oauthProvider) return false;

  const credentials = await oauthProvider.login({
    onAuth: (info) => callbacks.onUrl(info.url, info.instructions),
    onPrompt: (prompt) => callbacks.onPrompt(prompt.message),
    onProgress: (msg) => callbacks.onProgress(msg),
  });

  // Persist
  const stored = loadCredentials();
  stored[provider] = {
    type: "oauth",
    refresh: credentials.refresh,
    access: credentials.access,
    expires: credentials.expires,
  };
  saveCredentials(stored);

  return true;
}

/**
 * Get a valid API key for a provider, automatically refreshing if expired.
 * Returns null if no credentials are stored for the provider.
 */
export async function getApiKeyForProvider(
  provider: string,
): Promise<string | null> {
  const stored = loadCredentials();
  if (!(provider in stored)) return null;

  // Build the credentials map that getOAuthApiKey expects
  const credMap: Record<string, OAuthCredentials> = {};
  for (const [id, cred] of Object.entries(stored)) {
    credMap[id] = {
      refresh: cred.refresh,
      access: cred.access,
      expires: cred.expires,
    };
  }

  const result = await getOAuthApiKey(provider, credMap);
  if (!result) return null;

  // Persist refreshed credentials
  stored[provider] = {
    type: "oauth",
    refresh: result.newCredentials.refresh,
    access: result.newCredentials.access,
    expires: result.newCredentials.expires,
  };
  saveCredentials(stored);

  return result.apiKey;
}

/**
 * Check whether a provider has stored credentials (may be expired).
 */
export function isLoggedIn(provider: string): boolean {
  const stored = loadCredentials();
  return provider in stored;
}

// ── TUI-friendly command handlers ──

/**
 * Handle /login command from TUI. Shows providers or runs login flow.
 * Uses `output` callback to show messages immediately during the async flow.
 */
export async function handleLogin(
  providerArg: string,
  output: (msg: string) => void,
): Promise<void> {
  const providers = getSupportedProviders();

  if (!providerArg) {
    const list = providers
      .map((p, i) => `    ${i + 1}. ${p.id} — ${p.name}`)
      .join("\n");
    output(`\n  Login to a provider:\n\n${list}\n\n  Type /login <number> or /login <name>\n`);
    return;
  }

  // Accept number or name
  let provider = providerArg;
  const num = parseInt(provider, 10);
  if (!isNaN(num) && num >= 1 && num <= providers.length) {
    provider = providers[num - 1].id;
  }

  if (isLoggedIn(provider)) {
    output(`  Already logged in to ${provider}. Use /logout ${provider} first.`);
    return;
  }

  output(`  Logging in to ${provider}...`);

  const success = await loginProvider(provider, {
    onUrl: (url, instructions) => {
      output(`  Open this URL:\n    ${url}`);
      if (instructions) output(`  ${instructions}`);
    },
    onPrompt: async () => "",
    onProgress: (msg) => output(`  ${msg}`),
  });

  if (success) {
    output(`  ✓ Logged in to ${provider}.`);
  } else {
    output(`  Unknown provider: ${provider}. Use /login to see options.`);
  }
}

/** Handle /logout command from TUI. */
export function handleLogout(provider: string): string {
  if (!provider) return "  Usage: /logout <provider>";
  if (!isLoggedIn(provider)) return `  Not logged in to ${provider}.`;
  const { removeProviderCredentials } = require("./storage");
  removeProviderCredentials(provider);
  return `  ✓ Logged out of ${provider}.`;
}

/** Handle /auth command from TUI. */
export function handleAuthStatus(): string {
  const { listProviders } = require("./storage");
  const providers = listProviders();
  if (providers.length === 0) {
    return "  No active logins. Use /login <provider>.";
  }
  return "\n  Authenticated:\n" + providers.map((p: string) => `    ✓ ${p}`).join("\n") + "\n";
}
