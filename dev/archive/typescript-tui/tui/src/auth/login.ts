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
