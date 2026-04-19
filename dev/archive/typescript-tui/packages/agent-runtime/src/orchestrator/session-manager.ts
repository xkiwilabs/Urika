import type { RpcClient } from "../rpc/client";

/** Structure matching Python OrchestratorSession dataclass. */
export interface OrchestratorSession {
  session_id: string;
  started: string;
  updated: string;
  older_summary: string;
  recent_messages: any[];
  preview: string;
}

export interface SessionListEntry {
  session_id: string;
  started: string;
  updated: string;
  preview: string;
  turn_count: number;
  has_older_summary: boolean;
}

/** Max turns (user+assistant pairs) kept verbatim before compaction. */
export const MAX_RECENT_TURNS = 20;
/** When compacting, how many of the oldest turns to summarize. */
export const COMPACT_CHUNK_SIZE = 10;

/** Build a simple text summary of a list of messages (truncation-based).
 * Future work: use an LLM to produce a semantic summary.
 */
function summarizeMessages(messages: any[]): string {
  const lines: string[] = [`[${messages.length} earlier messages]`];
  for (const msg of messages) {
    const role = msg?.role ?? "?";
    let text = "";
    if (typeof msg?.content === "string") {
      text = msg.content;
    } else if (Array.isArray(msg?.content)) {
      const textBlock = msg.content.find((b: any) => b?.type === "text");
      if (textBlock) text = textBlock.text;
    }
    if (text) {
      const snippet = text.slice(0, 100).replace(/\n/g, " ");
      lines.push(`  ${role}: ${snippet}${text.length > 100 ? "..." : ""}`);
    }
  }
  return lines.join("\n");
}

/**
 * SessionManager — persists orchestrator conversation history per-project.
 * Sessions live under {project_dir}/.urika/sessions/ and are managed via RPC.
 */
export class SessionManager {
  private rpc: RpcClient;
  private projectDir: string;
  private currentSession: OrchestratorSession | null = null;

  constructor(rpc: RpcClient, projectDir: string) {
    this.rpc = rpc;
    this.projectDir = projectDir;
  }

  setProjectDir(projectDir: string): void {
    this.projectDir = projectDir;
    // Clear current session when switching projects
    this.currentSession = null;
  }

  /** Create a new empty session. */
  newSession(): OrchestratorSession {
    const now = new Date().toISOString();
    const id = now.replace(/\..+/, "").replace(/:/g, "-");
    this.currentSession = {
      session_id: id,
      started: now,
      updated: now,
      older_summary: "",
      recent_messages: [],
      preview: "",
    };
    return this.currentSession;
  }

  /** Get the current session, creating one if needed. */
  getCurrentSession(): OrchestratorSession {
    if (!this.currentSession) return this.newSession();
    return this.currentSession;
  }

  /** Set the current session (e.g. after resume). */
  setCurrentSession(session: OrchestratorSession): void {
    this.currentSession = session;
  }

  /** Clear current session (e.g. /new-session). */
  clearCurrentSession(): void {
    this.currentSession = null;
  }

  /** Whether there's an active session with messages. */
  hasMessages(): boolean {
    return (this.currentSession?.recent_messages?.length ?? 0) > 0;
  }

  /** Update messages and persist to disk.
   *
   * If messages exceed MAX_RECENT_TURNS*2, older messages are truncated
   * into a simple text summary (LLM-based summarization is future work).
   */
  async saveMessages(messages: any[]): Promise<void> {
    const session = this.getCurrentSession();

    // Simple truncation-based compaction: when too many messages,
    // move older ones into older_summary as a plain count/preview.
    const maxRecent = MAX_RECENT_TURNS * 2;
    if (messages.length > maxRecent) {
      const splitAt = COMPACT_CHUNK_SIZE * 2;
      const older = messages.slice(0, splitAt);
      const recent = messages.slice(splitAt);

      // Build a text summary of the older messages
      const olderSummary = summarizeMessages(older);
      const existingSummary = session.older_summary;
      session.older_summary = existingSummary
        ? `${existingSummary}\n${olderSummary}`
        : olderSummary;
      session.recent_messages = recent;
    } else {
      session.recent_messages = messages;
    }

    // Set preview from first user message (if not already set)
    if (!session.preview) {
      const firstUser = messages.find((m: any) => m?.role === "user");
      if (firstUser) {
        const content = firstUser.content;
        if (typeof content === "string") {
          session.preview = content.slice(0, 80);
        } else if (Array.isArray(content)) {
          const textBlock = content.find((b: any) => b?.type === "text");
          if (textBlock) session.preview = String(textBlock.text).slice(0, 80);
        }
      }
    }

    await this.rpc.call("sessions.save", {
      project_dir: this.projectDir,
      session,
    });
  }

  /** True if messages exceed verbatim limit — compaction needed. */
  needsCompaction(): boolean {
    const session = this.currentSession;
    if (!session) return false;
    return session.recent_messages.length > MAX_RECENT_TURNS * 2;
  }

  /** Split messages into (to-summarize, to-keep). */
  splitForCompaction(): { toSummarize: any[]; toKeep: any[] } {
    const session = this.getCurrentSession();
    const messages = session.recent_messages;
    const splitAt = COMPACT_CHUNK_SIZE * 2;
    return {
      toSummarize: messages.slice(0, splitAt),
      toKeep: messages.slice(splitAt),
    };
  }

  /** Apply compaction: replace older messages with a summary. */
  applyCompaction(summary: string, keptMessages: any[]): void {
    const session = this.getCurrentSession();
    const existingSummary = session.older_summary;
    session.older_summary = existingSummary
      ? `${existingSummary}\n\n${summary}`
      : summary;
    session.recent_messages = keptMessages;
  }

  /** List recent sessions for the current project. */
  async listSessions(limit = 20): Promise<SessionListEntry[]> {
    return (await this.rpc.call("sessions.list", {
      project_dir: this.projectDir,
      limit,
    })) as SessionListEntry[];
  }

  /** Load a specific session by ID. */
  async loadSession(sessionId: string): Promise<OrchestratorSession | null> {
    const result = await this.rpc.call("sessions.load", {
      project_dir: this.projectDir,
      session_id: sessionId,
    });
    return result as OrchestratorSession | null;
  }

  /** Get the most recent session for this project. */
  async getMostRecent(): Promise<OrchestratorSession | null> {
    const result = await this.rpc.call("sessions.most_recent", {
      project_dir: this.projectDir,
    });
    return result as OrchestratorSession | null;
  }

  /** Delete a session by ID. */
  async deleteSession(sessionId: string): Promise<boolean> {
    const result = await this.rpc.call("sessions.delete", {
      project_dir: this.projectDir,
      session_id: sessionId,
    });
    return result as boolean;
  }
}
