import { useEffect, useState } from "react";

export default function Profile() {
  const [user, setUser] = useState<any>(null);
  const [summary, setSummary] = useState<string>("");
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [activity, setActivity] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);

  useEffect(() => {
    fetch("/v1/auth/whoami", { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => { if (d.user) setUser(d.user); });

    // Fetch memories and generate summary
    fetch("/v1/memory/entries", { credentials: "same-origin" })
      .then(r => r.json())
      .then(async (memories) => {
        const memoryContext = Array.isArray(memories)
          ? memories.map((m: any) => `[${m.namespace}] ${m.key}: ${m.value}`).join("\n")
          : "No memories stored yet.";

        const r = await fetch("/v1/chat/stream", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: [
              { role: "system", content: "You are summarizing what you know about a user based on their stored memories. Be concise, warm, and specific. Write 2-3 sentences about who they are, what they work on, and their preferences. If no memories exist, say so briefly." },
              { role: "user", content: `Here are my stored memories:\n${memoryContext}\n\nSummarize what you know about me.` }
            ]
          })
        });
        const reader = r.body?.getReader();
        const decoder = new TextDecoder();
        let acc = "";
        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            for (const line of decoder.decode(value, { stream: true }).split("\n")) {
              if (!line.startsWith("data: ")) continue;
              try {
                const e = JSON.parse(line.slice(6));
                if (e.type === "token" || e.type === "content") acc += e.content || e.token || "";
                else if (e.type === "done" && e.content && !acc) acc = e.content;
              } catch {
                // SSE chunk split a JSON payload mid-object — wait for the rest.
              }
            }
            setSummary(acc);
          }
        }
        if (!acc) setSummary("No memories stored yet — start chatting to build context.");
        setSummaryLoading(false);
      })
      .catch(() => { setSummary("Could not load memories."); setSummaryLoading(false); });

    // Recent audit activity
    fetch("/v1/audit", { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => setActivity(Array.isArray(d) ? d.slice(0, 10) : []))
      .catch(() => {});

    // Recent chat sessions
    fetch("/v1/chat/sessions", { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => setSessions(Array.isArray(d) ? d.slice(0, 5) : []))
      .catch(() => {});
  }, []);

  if (!user) return <div style={{ padding: 40, fontFamily: "var(--mono)", color: "var(--pencil)" }}>Loading...</div>;

  const initials = (user.username || "U").split("-").map((w: string) => w[0]).join("").toUpperCase().slice(0, 2);

  return (
    <div style={{ padding: "2rem", maxWidth: 700 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 700, color: "var(--paper)" }}>
          {initials}
        </div>
        <div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 24, fontWeight: 700 }}>{user.username}</div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>{user.role} · MyID authenticated</div>
        </div>
      </div>

      {/* AI Summary */}
      <div className="card" style={{ marginBottom: 12, borderLeft: "3px solid var(--accent)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--accent)", marginBottom: 8 }}>WHAT I KNOW ABOUT YOU</div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 14, lineHeight: 1.6, color: "var(--ink)" }}>
          {summaryLoading ? <span style={{ color: "var(--pencil)" }}>Thinking...</span> : summary}
        </div>
      </div>

      {/* Recent Sessions */}
      {sessions.length > 0 && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 8 }}>RECENT CONVERSATIONS</div>
          {sessions.map((s: any) => (
            <div key={s.id} style={{ padding: "6px 0", borderBottom: "1px dotted var(--rule)", fontFamily: "var(--mono)", fontSize: 11, display: "flex", justifyContent: "space-between" }}>
              <span>{s.title || "Untitled"}</span>
              <span style={{ color: "var(--pencil)", fontSize: 9 }}>{s.message_count || 0} msgs</span>
            </div>
          ))}
        </div>
      )}

      {/* Recent Activity */}
      {activity.length > 0 && (
        <div className="card">
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 8 }}>RECENT ACTIVITY</div>
          {activity.map((a: any, i: number) => (
            <div key={i} style={{ padding: "4px 0", borderBottom: "1px dotted var(--rule)", fontFamily: "var(--mono)", fontSize: 10, display: "flex", gap: 8 }}>
              <span style={{ color: "var(--accent)", minWidth: 80 }}>{a.action}</span>
              <span style={{ color: "var(--pencil)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.target || ""}</span>
              <span style={{ color: "var(--pencil)", fontSize: 9 }}>{a.actor}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
