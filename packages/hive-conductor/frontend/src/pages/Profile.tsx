import { Fragment, useEffect, useState } from "react";
import { useToast } from "../components/shared";
import { claimUiState, clearUiState, storedUiState } from "../lib/uiState";

export default function Profile() {
  const [user, setUser] = useState<ProfileUser | null>(null);
  const [summary, setSummary] = useState<string>("");
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [activity, setActivity] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const toast = useToast();
  const [stored, setStored] = useState(() => storedUiState());

  useEffect(() => {
    loadWhoamiUser()
      .then((next) => {
        if (next) setUser(next);
      })
      .catch(() => {});

    loadProfile()
      .then((p) => {
        setLanding(resolveLandingPath(p.preferences?.[LANDING_PREF_KEY]));
        setRestore(resolveRestoreAggressiveness(p.preferences?.[RESTORE_PREF_KEY]));
      })
      .catch(() => {});

    (async () => {
      try {
        const memories = await loadMemoryEntries();
        const memoryContext =
          memories.length > 0
            ? memories
                .map((m: any) => `[${m.namespace}] ${m.key}: ${m.value}`)
                .join("\n")
            : "No memories stored yet.";
        const acc = await summarizeMemoriesFromContext(memoryContext);
        setSummary(acc || "No memories stored yet — start chatting to build context.");
      } catch {
        setSummary("Could not load memories.");
      } finally {
        setSummaryLoading(false);
      }
    })();

    loadRecentAuditEntries(10)
      .then((entries) => setActivity(entries as any[]))
      .catch(() => {});

    loadRecentChatSessions(5)
      .then((rows) => setSessions(rows as any[]))
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
          <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>{user.role} · MyID authenticated</div>
        </div>
      </div>

      {/* What this browser keeps for this account (#1418, #1419): the four
          conveniences, their current values, and a way to forget them. */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 8 }}>
          STORED IN THIS BROWSER
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 13, color: "var(--pencil)", marginBottom: 8 }}>
          Kept in this browser only, for this account, until you sign out or clear it here.
          Nothing below leaves your device.
        </div>
        <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontFamily: "var(--mono)", fontSize: 12 }}>
          {stored.map((row) => (
            <Fragment key={row.key}>
              <dt style={{ color: "var(--ink)" }}>{row.what}</dt>
              <dd style={{ margin: 0, color: "var(--pencil)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {row.value ?? "not set"}
              </dd>
            </Fragment>
          ))}
        </dl>
        <button
          type="button"
          className="btn"
          style={{ marginTop: 10, fontSize: 12 }}
          onClick={() => {
            clearUiState();
            claimUiState(user.id);
            setStored(storedUiState());
            toast("Browser state cleared", "ok");
          }}
        >
          Clear browser state
        </button>
      </div>

      {/* AI Summary */}
      <div className="card" style={{ marginBottom: 12, borderLeft: "3px solid var(--accent)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--accent)", marginBottom: 8 }}>WHAT I KNOW ABOUT YOU</div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 14, lineHeight: 1.6, color: "var(--ink)" }}>
          {summaryLoading ? <span style={{ color: "var(--pencil)" }}>Thinking...</span> : summary}
        </div>
      </div>

      {/* Recent Sessions */}
      {sessions.length > 0 && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 8 }}>RECENT CONVERSATIONS</div>
          {sessions.map((s: any) => (
            <div key={s.id} style={{ padding: "6px 0", borderBottom: "1px dotted var(--rule)", fontFamily: "var(--mono)", fontSize: 12, display: "flex", justifyContent: "space-between" }}>
              <span>{s.title || "Untitled"}</span>
              <span style={{ color: "var(--pencil)", fontSize: 12 }}>{s.message_count || 0} msgs</span>
            </div>
          ))}
        </div>
      )}

      {/* Recent Activity */}
      {activity.length > 0 && (
        <div className="card">
          <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 8 }}>RECENT ACTIVITY</div>
          {activity.map((a: any, i: number) => (
            <div key={i} style={{ padding: "4px 0", borderBottom: "1px dotted var(--rule)", fontFamily: "var(--mono)", fontSize: 12, display: "flex", gap: 8 }}>
              <span style={{ color: "var(--accent)", minWidth: 80 }}>{a.action}</span>
              <span style={{ color: "var(--pencil)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.target || ""}</span>
              <span style={{ color: "var(--pencil)", fontSize: 12 }}>{a.actor}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
