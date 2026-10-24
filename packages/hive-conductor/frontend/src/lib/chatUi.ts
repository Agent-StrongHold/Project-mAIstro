/** Chat page UI shapes (#1822). Under `lib/` for the typed-client ratchet. */

export type Role = "user" | "assistant";
export type StepStatus = "running" | "done" | "error";

export interface ToolStep {
  id: string;
  tool: string;
  args?: Record<string, unknown>;
  status: StepStatus;
  summary?: string;
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  reasoning?: string; // assistant only — streamed thinking / reasoning tokens
  steps?: ToolStep[]; // assistant only — the live tool/status timeline
  status?: string; // assistant only — transient status line while streaming
  timestamp: Date;
}

/** The brief so far, as the chat stream's `brief` event carries it
 * (SPEC-091726-7c2a): the interview's summary and next question while it is
 * open, or the draft once the person committed. */
export interface BriefField {
  key: string;
  label: string;
  value: string | null;
  source: "user" | "verbatim" | "record" | "assumed" | "open";
}

export interface BriefView {
  event: string;
  summary: {
    known: number;
    needed: number;
    ready: boolean;
    fields: BriefField[];
    notes: string[];
  } | null;
  question: {
    key: string;
    label: string;
    question: string;
    can_assume: boolean;
  } | null;
  draft?: { fields: Record<string, string>; assumed: string[]; notes: string[] };
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  brief?: BriefView | null;
}
