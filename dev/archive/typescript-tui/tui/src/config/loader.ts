import { readFileSync } from "fs";
import { join } from "path";
import type { UrikaConfig } from "./types";

const DEFAULT_MODEL = "anthropic/claude-sonnet-4-6";

type TomlValue = string | number | boolean | string[];
type TomlSection = Record<string, TomlValue>;
type TomlDoc = Record<string, TomlSection>;

/**
 * Minimal TOML parser sufficient for urika.toml configuration files.
 *
 * Handles:
 *   [section] and [section.subsection] headers
 *   key = "string" and key = 'string'
 *   key = true/false
 *   key = 123 (integers and floats)
 *   key = ["array", "items"]
 *   # comments
 *   empty lines
 */
function parseTOML(text: string): TomlDoc {
  const result: TomlDoc = {};
  let currentSection = "";

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();

    // Skip empty lines and comments
    if (line === "" || line.startsWith("#")) continue;

    // Section header
    const sectionMatch = line.match(/^\[([^\]]+)\]$/);
    if (sectionMatch) {
      currentSection = sectionMatch[1].trim();
      if (!result[currentSection]) {
        result[currentSection] = {};
      }
      continue;
    }

    // Key = value
    const kvMatch = line.match(/^([A-Za-z0-9_-]+)\s*=\s*(.+)$/);
    if (kvMatch) {
      const key = kvMatch[1].trim();
      const rawValue = kvMatch[2].trim();
      const value = parseValue(rawValue);

      if (!result[currentSection]) {
        result[currentSection] = {};
      }
      result[currentSection][key] = value;
    }
  }

  return result;
}

function parseValue(raw: string): TomlValue {
  // Double-quoted string
  if (raw.startsWith('"') && raw.endsWith('"')) {
    return raw.slice(1, -1);
  }

  // Single-quoted string
  if (raw.startsWith("'") && raw.endsWith("'")) {
    return raw.slice(1, -1);
  }

  // Boolean
  if (raw === "true") return true;
  if (raw === "false") return false;

  // Array
  if (raw.startsWith("[") && raw.endsWith("]")) {
    return parseArray(raw);
  }

  // Number
  const num = Number(raw);
  if (!isNaN(num)) return num;

  // Fallback: return as string
  return raw;
}

function parseArray(raw: string): string[] {
  const inner = raw.slice(1, -1).trim();
  if (inner === "") return [];

  const items: string[] = [];
  let current = "";
  let inQuote: string | null = null;

  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i];

    if (inQuote) {
      if (ch === inQuote) {
        items.push(current);
        current = "";
        inQuote = null;
      } else {
        current += ch;
      }
    } else if (ch === '"' || ch === "'") {
      inQuote = ch;
    }
    // Skip commas and whitespace outside quotes
  }

  return items;
}

/**
 * Load a UrikaConfig from the urika.toml file in the given project directory.
 */
export function loadUrikaConfig(projectDir: string): UrikaConfig {
  const tomlPath = join(projectDir, "urika.toml");
  let doc: TomlDoc;

  try {
    const text = readFileSync(tomlPath, "utf-8");
    doc = parseTOML(text);
  } catch {
    // If the file doesn't exist or can't be read, return defaults
    doc = {};
  }

  const project = doc["project"] ?? {};
  const runtime = doc["runtime"] ?? {};
  const runtimeModels = doc["runtime.models"] ?? {};
  const privacy = doc["privacy"] ?? {};

  // Build models record — only include string values
  const models: Record<string, string> = {};
  for (const [key, value] of Object.entries(runtimeModels)) {
    if (typeof value === "string") {
      models[key] = value;
    }
  }

  // Build localRoles from privacy.local_roles
  let localRoles: string[] = [];
  if (Array.isArray(privacy["local_roles"])) {
    localRoles = privacy["local_roles"] as string[];
  }

  return {
    projectName: typeof project["name"] === "string" ? project["name"] : "",
    question: typeof project["question"] === "string" ? project["question"] : "",
    mode: typeof project["mode"] === "string" ? project["mode"] : "",
    defaultModel:
      typeof runtime["default_model"] === "string"
        ? runtime["default_model"]
        : DEFAULT_MODEL,
    models,
    privacyMode: typeof privacy["mode"] === "string" ? privacy["mode"] : "",
    localRoles,
  };
}
