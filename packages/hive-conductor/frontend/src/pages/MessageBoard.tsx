import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "../lib/api";
import {
  Card,
  ConfirmDialog,
  EmptyState,
  LoadingSpinner,
  PageHeader,
  SearchInput,
  useToast,
} from "../components/shared";

type MessagePriority = "info" | "warning" | "critical";

type Message = {
  id: string;
  from_agent: string;
  to: string;
  subject: string;
  body: string;
  priority: MessagePriority;
  read: boolean;
  category: string;
  created_at: string;
};

type UnreadCount = { count: number };

const FILTER_TABS = ["All", "Unread", "Security", "Mission", "System", "Quota"];

const PRIORITY_COLORS: Record<MessagePriority, { bg: string; fg: string }> = {
  info: { bg: "rgba(120,120,120,0.15)", fg: "#888" },
  warning: { bg: "rgba(212,160,23,0.15)", fg: "#b8860b" },
  critical: { bg: "rgba(196,69,42,0.15)", fg: "#c4452a" },
};

function priorityBadge(p: MessagePriority) {
  const c = PRIORITY_COLORS[p];
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 3, fontSize: 8,
      fontFamily: "var(--mono)", fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {p}
    </span>
  );
}

function categoryBadge(cat: string) {
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 3, fontSize: 8,
      fontFamily: "var(--mono)", fontWeight: 500,
      background: "rgba(91,143,179,0.12)", color: "#3a6a9a",
    }}>
      {cat}
    </span>
  );
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

export default function MessageBoard() {
  const toast = useToast();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Message | null>(null);
  const [filterTab, setFilterTab] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [unreadCount, setUnreadCount] = useState(0);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const loadMessages = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filterTab === 1) params.set("unread", "true");
      if (filterTab >= 2) params.set("category", FILTER_TABS[filterTab].toLowerCase());
      if (searchQuery) params.set("q", searchQuery);
      const qs = params.toString();
      const data = await apiGet<Message[]>(`/v1/messages${qs ? `?${qs}` : ""}`);
      setMessages(data);
    } catch {
      toast("Failed to load messages", "error");
    } finally {
      setLoading(false);
    }
  }, [filterTab, searchQuery, toast]);

  const loadUnreadCount = useCallback(async () => {
    try {
      const data = await apiGet<UnreadCount>("/v1/messages/unread-count");
      setUnreadCount(data.count);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => { loadMessages(); }, [loadMessages]);
  useEffect(() => { loadUnreadCount(); }, [loadUnreadCount, messages]);

  const handleSelect = useCallback(async (msg: Message) => {
    if (!msg.read) {
      try {
        await apiPatch(`/v1/messages/${msg.id}/read`);
        setMessages((prev) => prev.map((m) => m.id === msg.id ? { ...m, read: true } : m));
      } catch {
        // still show the message
      }
    }
    setSelected(msg);
  }, []);

  const handleMarkRead = useCallback(async () => {
    if (!selected || selected.read) return;
    try {
      await apiPatch(`/v1/messages/${selected.id}/read`);
      setMessages((prev) => prev.map((m) => m.id === selected.id ? { ...m, read: true } : m));
      setSelected({ ...selected, read: true });
      toast("Marked as read");
    } catch {
      toast("Failed to mark as read", "error");
    }
  }, [selected, toast]);

  const handleMarkAllRead = useCallback(async () => {
    try {
      await apiPost("/v1/messages/mark-all-read");
      setMessages((prev) => prev.map((m) => ({ ...m, read: true })));
      if (selected) setSelected({ ...selected, read: true });
      setUnreadCount(0);
      toast("All messages marked as read");
    } catch {
      toast("Failed to mark all as read", "error");
    }
  }, [selected, toast]);

  const handleDelete = useCallback(async () => {
    if (!deleteId) return;
    try {
      await apiDelete(`/v1/messages/${deleteId}`);
      toast("Message deleted");
      if (selected?.id === deleteId) setSelected(null);
      setDeleteId(null);
      await loadMessages();
    } catch {
      toast("Delete failed", "error");
    }
    setDeleteId(null);
  }, [deleteId, selected, loadMessages, toast]);

  const filteredMessages = searchQuery
    ? messages.filter((m) =>
        m.subject.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.from_agent.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.body.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : messages;

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader
        title="Message Board"
        subtitle={`${unreadCount} unread — alerts and updates from your agents`}
        helpHref="/docs#messages"
      />
      <div style={{ display: "flex", gap: 0, height: "calc(100vh - 140px)" }}>
        <div style={{
          width: 280, minWidth: 280, borderRight: "1.3px solid var(--rule)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}>
          <div style={{
            padding: "10px 12px", borderBottom: "1.3px solid var(--rule)",
            display: "flex", flexDirection: "column", gap: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: "var(--pencil)" }}>
                  Messages
                </span>
                {unreadCount > 0 && (
                  <span style={{
                    background: "var(--accent)", color: "var(--paper)",
                    borderRadius: "50%", width: 20, height: 20,
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "var(--mono)", fontSize: 9, fontWeight: 700,
                  }}>
                    {formatTokens(unreadCount)}
                  </span>
                )}
              </div>
              <button
                onClick={handleMarkAllRead}
                disabled={unreadCount === 0}
                style={{
                  background: "none", border: "1px solid var(--rule)", borderRadius: 3,
                  padding: "3px 8px", cursor: unreadCount > 0 ? "pointer" : "default",
                  fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)",
                  opacity: unreadCount > 0 ? 1 : 0.4,
                }}
              >
                Mark All Read
              </button>
            </div>
            <div style={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
              {FILTER_TABS.map((tab, i) => (
                <button
                  key={tab}
                  onClick={() => setFilterTab(i)}
                  style={{
                    background: filterTab === i ? "var(--accent)" : "transparent",
                    color: filterTab === i ? "var(--paper)" : "var(--pencil)",
                    border: filterTab === i ? "1px solid var(--accent)" : "1px solid var(--rule)",
                    borderRadius: 3, padding: "2px 8px", cursor: "pointer",
                    fontFamily: "var(--mono)", fontSize: 8, fontWeight: filterTab === i ? 600 : 400,
                  }}
                >
                  {tab}
                </button>
              ))}
            </div>
            <SearchInput value={searchQuery} onChange={setSearchQuery} placeholder="Search messages..." />
          </div>

          <div style={{ flex: 1, overflow: "auto" }}>
            {loading ? (
              <LoadingSpinner />
            ) : filteredMessages.length === 0 ? (
              <EmptyState icon="🐝" title="No messages" />
            ) : (
              filteredMessages.map((msg) => (
                <div
                  key={msg.id}
                  onClick={() => handleSelect(msg)}
                  style={{
                    padding: "10px 12px", borderBottom: "1px solid var(--rule)",
                    cursor: "pointer", background: selected?.id === msg.id ? "var(--paper-2, #f5f5f0)" : "transparent",
                    borderLeft: selected?.id === msg.id ? "3px solid var(--accent)" : "3px solid transparent",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      {!msg.read && (
                        <span style={{
                          width: 7, height: 7, borderRadius: "50%",
                          background: "var(--accent)", flexShrink: 0,
                        }} />
                      )}
                      <span style={{
                        fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)",
                        fontWeight: msg.read ? 400 : 700,
                      }}>
                        {msg.from_agent}
                      </span>
                    </div>
                    {priorityBadge(msg.priority)}
                  </div>
                  <div style={{
                    fontFamily: "var(--hand)", fontSize: 12,
                    fontWeight: msg.read ? 400 : 700,
                    color: msg.read ? "var(--ink)" : "var(--ink)",
                    marginBottom: 3,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {msg.subject}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)" }}>
                      {relativeTime(msg.created_at)}
                    </span>
                    {categoryBadge(msg.category)}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div style={{ flex: 1, overflow: "auto", padding: 20 }}>
          {selected ? (
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <h2 style={{ fontFamily: "var(--hand)", fontSize: 22, fontWeight: 700, margin: 0 }}>
                  {selected.subject}
                </h2>
                <div style={{ display: "flex", gap: 6 }}>
                  {!selected.read && (
                    <button
                      onClick={handleMarkRead}
                      style={{
                        padding: "5px 14px", borderRadius: 4, cursor: "pointer",
                        fontFamily: "var(--mono)", fontSize: 10,
                        border: "1.3px solid var(--accent)",
                        background: "var(--accent)", color: "var(--paper)",
                      }}
                    >
                      Mark Read
                    </button>
                  )}
                  <button
                    onClick={() => setDeleteId(selected.id)}
                    style={{
                      padding: "5px 14px", borderRadius: 4, cursor: "pointer",
                      fontFamily: "var(--mono)", fontSize: 10,
                      border: "1.3px solid #c4452a",
                      background: "transparent", color: "#c4452a",
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>

              <Card>
                <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", marginBottom: 16, fontFamily: "var(--mono)", fontSize: 10 }}>
                  <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>From</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontWeight: 600 }}>{selected.from_agent}</span>
                    <span style={{
                      padding: "1px 6px", borderRadius: 3, fontSize: 7,
                      background: "rgba(139,92,246,0.12)", color: "#8b5cf6",
                      fontFamily: "var(--mono)", fontWeight: 600,
                    }}>
                      agent
                    </span>
                  </div>

                  <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>To</span>
                  <span style={{ fontWeight: 500 }}>{selected.to}</span>

                  <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Time</span>
                  <span title={formatTimestamp(selected.created_at)}>{formatTimestamp(selected.created_at)}</span>

                  <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Priority</span>
                  <div>{priorityBadge(selected.priority)}</div>

                  <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Category</span>
                  <div>{categoryBadge(selected.category)}</div>
                </div>
              </Card>

              <Card>
                <div style={{
                  fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.6,
                  whiteSpace: "pre-wrap" as const, color: "var(--ink)",
                }}>
                  {selected.body}
                </div>
              </Card>
            </div>
          ) : (
            <EmptyState icon="💌" title="Select a message" />
          )}
        </div>
      </div>

      <ConfirmDialog
        open={deleteId !== null}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        title="Delete Message"
        message="This message will be permanently deleted."
      />
    </div>
  );
}
