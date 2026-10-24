/** Durable Workspace chat session wire shapes (#1822). Under `lib/` for typed-client. */

export type ChatSessionSummary = {
  id: string;
  user_id: string;
  workspace_id: string | null;
  title: string;
  message_count: number;
  updated_at: string;
};

export type ChatApiMessage = {
  id: string;
  user_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  timestamp: string | null;
};

export type ChatSessionDetail = {
  id: string;
  user_id: string;
  workspace_id: string | null;
  title: string;
  messages: ChatApiMessage[];
  created_at: string;
  updated_at: string;
};

export function sessionsListPath(workspaceId: string): string {
  return `/v1/chat/sessions?workspace_id=${encodeURIComponent(workspaceId)}`;
}

export function sessionPath(sessionId: string): string {
  return `/v1/chat/sessions/${encodeURIComponent(sessionId)}`;
}

/** Models catalog — bare fetch lives in lib/ for the typed-client ratchet. */
export function fetchModelsCatalog(): Promise<Response> {
  return fetch("/v1/settings/models", { credentials: "same-origin" });
}

/** Streaming chat completion — bare fetch lives in lib/ for the ratchet. */
export function openChatStream(
  body: {
    model: string;
    messages: Array<{ role: string; content: string }>;
    workspace_id: string;
    session_id: string;
  },
  signal: AbortSignal,
): Promise<Response> {
  return fetch("/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    signal,
    body: JSON.stringify(body),
  });
}
