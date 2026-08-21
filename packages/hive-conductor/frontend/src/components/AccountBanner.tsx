import { type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "../App";

const ADMIN_GATED: string[] = [
  "Change server-wide Settings (PUT /v1/settings)",
  "Edit the MCP server catalog (POST/PUT/DELETE /v1/mcp/servers)",
  "Register or remove agents (POST/PUT/DELETE /v1/agents)",
  "Edit skills (POST/PUT/DELETE /v1/skills)",
];

const USER_GATED: string[] = [
  "Use Chat (admin is blocked — break-glass account, not daily-driver)",
  "Set your own integration PATs (per-user, encrypted)",
  "Run fleet pulses and view your own dashboards",
];

const bannerStyle: CSSProperties = {
  border: "1.3px solid var(--rule)",
  borderRadius: 6,
  padding: "10px 14px",
  marginBottom: 16,
  background: "var(--paper)",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
};

const badgeStyle = (role: string): CSSProperties => ({
  fontFamily: "var(--mono)",
  fontSize: 10,
  fontWeight: 700,
  padding: "3px 8px",
  borderRadius: 3,
  background: role === "admin" ? "var(--danger)" : "var(--accent)",
  color: "var(--paper)",
  letterSpacing: 0.5,
});

const btnStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 10,
  padding: "5px 12px",
  whiteSpace: "nowrap",
};

async function logout() {
  try {
    await fetch("/v1/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // ignore — even if the call fails, redirecting still gives the user
    // a fresh login.
  }
  // Send the user to the SPA root. AuthGuard sees no session and renders
  // <Login>. (Do NOT append "login" — there is no /login route, so a stale
  // /pm/login URL after subsequent re-login leaves the SPA with no
  // matching route and renders blank.)
  window.location.href = import.meta.env.BASE_URL || "/";
}

export function AccountBanner() {
  const user = useUser();
  const navigate = useNavigate();
  if (!user) return null;

  const role = user.role || "user";
  const helperText =
    role === "admin"
      ? "Break-glass account. Chat is blocked. Use this only to change server-wide config; log out to your daily user for normal work."
      : "Regular user. You can run the fleet, save your PATs, and chat — but server-wide config (Settings, MCP catalog) requires admin.";

  const gated = role === "admin" ? USER_GATED : ADMIN_GATED;
  const gatedLabel = role === "admin" ? "What only the daily user can do:" : "What only admin can do:";

  return (
    <div style={bannerStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 240 }}>
        <span style={badgeStyle(role)}>{role.toUpperCase()}</span>
        <div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>
            Signed in as {user.username}
          </div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 2, maxWidth: 540 }}>
            {helperText}
          </div>
          <details style={{ marginTop: 4 }}>
            <summary style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", cursor: "pointer" }}>
              {gatedLabel}
            </summary>
            <ul style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 4, paddingLeft: 18 }}>
              {gated.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          </details>
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button
          type="button"
          className="btn"
          onClick={() => navigate("/settings")}
          style={btnStyle}
        >
          ⚙ Settings
        </button>
        <button
          type="button"
          className="btn btn-accent"
          onClick={() => void logout()}
          style={btnStyle}
          title="End this session and return to the login page"
        >
          Sign out →
        </button>
      </div>
    </div>
  );
}
