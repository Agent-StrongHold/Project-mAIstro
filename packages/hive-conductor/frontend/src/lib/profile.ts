/**
 * Profile page transport helpers (#1050).
 *
 * Kept under `lib/` so the Profile surface does not mint bare `fetch(` call
 * sites (typed-client ratchet). Wire shapes for the durable preferences
 * document live here too — same reason for `ProfilePayload`.
 */

import { apiGet } from "./api";

export type ProfilePayload = {
  preferences?: Record<string, unknown>;
};

export type ProfileUser = {
  id: string;
  username?: string;
  role?: string;
  session_policy?: {
    idle_timeout_seconds: number;
    absolute_ttl_seconds: number;
    effective_expires_at: string;
  };
};

type WhoamiResponse = {
  user?: ProfileUser;
};

export async function loadProfile(): Promise<ProfilePayload> {
  return apiGet<ProfilePayload>("/v1/profile");
}

export async function loadWhoamiUser(): Promise<WhoamiResponse["user"] | null> {
  const data = await apiGet<WhoamiResponse>("/v1/auth/whoami");
  return data.user ?? null;
}

export async function loadMemoryEntries(): Promise<unknown[]> {
  const data = await apiGet<unknown>("/v1/memory/entries");
  return Array.isArray(data) ? data : [];
}

export async function loadRecentAuditEntries(limit = 10): Promise<unknown[]> {
  const data = await apiGet<{ entries?: unknown[] }>("/v1/audit");
  return Array.isArray(data?.entries) ? data.entries.slice(0, limit) : [];
}

export async function loadRecentChatSessions(limit = 5): Promise<unknown[]> {
  const data = await apiGet<unknown>("/v1/chat/sessions");
  return Array.isArray(data) ? data.slice(0, limit) : [];
}

/**
 * Ask chat to summarize stored memories for the Profile panel.
 * Uses a dedicated fetch (streaming body) — not the short-timeout CRUD client.
 */
export async function summarizeMemoriesFromContext(memoryContext: string): Promise<string> {
  const response = await fetch("/v1/chat/stream", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: [
        {
          role: "system",
          content:
            "You are summarizing what you know about a user based on their stored memories. Be concise, warm, and specific. Write 2-3 sentences about who they are, what they work on, and their preferences. If no memories exist, say so briefly.",
        },
        {
          role: "user",
          content: `Here are my stored memories:\n${memoryContext}\n\nSummarize what you know about me.`,
        },
      ],
    }),
  });
  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  let acc = "";
  if (reader) {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of decoder.decode(value, { stream: true }).split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6)) as {
            type?: string;
            content?: string;
            token?: string;
          };
          if (event.type === "token" || event.type === "content") {
            acc += event.content || event.token || "";
          } else if (event.type === "done" && event.content && !acc) {
            acc = event.content;
          }
        } catch {
          // SSE chunk split a JSON payload mid-object — wait for the rest.
        }
      }
    }
  }
  return acc;
}
