import { isGatedCapability } from "../lib/pmCapabilities";
import { StatusDot } from "./shared";

export type FleetAgent = {
  id: string;
  name: string;
  description: string;
  tagline?: string;
  primary_capability?: string;
  primary_action_label?: string;
  status: "idle" | "busy" | "offline" | "error";
  capabilities: string[];
  config?: {
    tagline?: string;
    primary_capability?: string;
    primary_action_label?: string;
  };
};

const STATUS_MAP = {
  idle: "idle" as const,
  busy: "running" as const,
  offline: "idle" as const,
  error: "error" as const,
};

type Props = {
  agent: FleetAgent;
  invoking: boolean;
  onInvoke: (agentId: string, capability: string) => void;
  onGatedInvoke?: (agentId: string, capability: string) => void;
  disabled?: boolean;
};

export function AgentFleetCard({
  agent,
  invoking,
  onInvoke,
  onGatedInvoke,
  disabled = false,
}: Props) {
  const tagline = agent.tagline || agent.config?.tagline || agent.description;
  const primaryCap =
    agent.primary_capability || agent.config?.primary_capability || agent.capabilities[0] || "";
  const primaryLabel = agent.primary_action_label || agent.config?.primary_action_label || "Run";
  const gated = primaryCap ? isGatedCapability(primaryCap) : false;

  const handlePrimary = () => {
    if (!primaryCap) return;
    // Intake "Propose Initiative" always opens the Jira draft flow (not a direct task).
    const openDraft =
      (gated && onGatedInvoke) ||
      (agent.id === "intake" && onGatedInvoke);
    if (openDraft) {
      onGatedInvoke(agent.id, gated ? primaryCap : "create_initiative");
    } else {
      onInvoke(agent.id, primaryCap);
    }
  };

  return (
    <article
      style={{
        background: "var(--paper)",
        border: "1.3px solid var(--rule)",
        borderRadius: 8,
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 220,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div>
          <h3 style={{ margin: 0, fontFamily: "var(--hand)", fontSize: 18 }}>{agent.name}</h3>
          <p style={{ margin: "4px 0 0", fontSize: 11, color: "var(--pencil)", lineHeight: 1.4 }}>{tagline}</p>
        </div>
        <StatusDot status={STATUS_MAP[agent.status] || "idle"} />
      </div>
      <code style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", wordBreak: "break-all" }}>
        {agent.id}
      </code>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {agent.capabilities.slice(0, 5).map((cap) => (
          <span
            key={cap}
            style={{
              fontFamily: "var(--mono)",
              fontSize: 8,
              padding: "2px 6px",
              borderRadius: 3,
              border: isGatedCapability(cap) ? "1px dashed var(--accent)" : "1px solid var(--rule)",
              background: "var(--paper-2, #f5f5f0)",
            }}
            title={isGatedCapability(cap) ? "Requires draft approval before Jira post" : "Runs autonomously"}
          >
            {cap}
          </span>
        ))}
        {agent.capabilities.length > 5 && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)" }}>
            +{agent.capabilities.length - 5}
          </span>
        )}
      </div>
      <div style={{ marginTop: "auto" }}>
        <button
          type="button"
          disabled={disabled || invoking || !primaryCap}
          onClick={handlePrimary}
          style={{
            width: "100%",
            padding: "8px 12px",
            borderRadius: 4,
            border: "none",
            background: disabled ? "var(--rule)" : "var(--accent)",
            color: "var(--paper)",
            fontFamily: "var(--mono)",
            fontSize: 10,
            cursor: disabled || invoking ? "not-allowed" : "pointer",
            opacity: disabled || invoking ? 0.6 : 1,
          }}
        >
          {disabled ? "Awaiting interview" : invoking ? "Running…" : primaryLabel}
        </button>
      </div>
    </article>
  );
}
