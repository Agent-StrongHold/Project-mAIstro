import { type ReactNode, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useUser } from "../App";
import { ModeToggle } from "./ModeToggle";
import { AppearanceToggle } from "./AppearanceToggle";
import { WorkspaceTabs } from "./WorkspaceTabs";
import { WorkspaceShare } from "./WorkspaceShare";
import { WorkspaceToolBindings } from "./WorkspaceToolBindings";
import { PersonaWizard } from "./PersonaWizard";
import {
  MessageCircle,
  LayoutDashboard,
  Target,
  Brain,
  Plug,
  KeyRound,
  Settings,
  Workflow,
  PlayCircle,
  Bot,
  Network,
  Zap,
  Repeat,
} from "lucide-react";

const fullNav = [
  { to: "/chat", icon: MessageCircle, label: "Chat" },
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/dags", icon: Workflow, label: "DAG Builder" },
  { to: "/dag-runs", icon: PlayCircle, label: "DAG Runs" },
  // Missions was reachable only from `pocNav`, so retiring POC mode left a
  // live route with no entry point anywhere in the app — the page still
  // renders, `App.tsx` still registers it, and a repo-wide search finds no
  // other Link or NavLink to it (#129).
  { to: "/missions", icon: Target, label: "Missions" },
  { to: "/agents", icon: Bot, label: "Agents" },
  { to: "/topology", icon: Network, label: "Topology" },
  { to: "/optimizer", icon: Zap, label: "Optimizer" },
  { to: "/knowledge", icon: Brain, label: "Inner Temple" },
  // M0 containment for #311: Deck Builder is intentionally absent until
  // model-authored HTML/SVG has a canonical sanitizer/structured renderer.
  { to: "/rsi", icon: Repeat, label: "RSI" },
  { to: "/mcp", icon: Plug, label: "Integrations" },
  { to: "/credentials", icon: KeyRound, label: "Credentials" },
  { to: "/settings", icon: Settings, label: "Settings" },
];


async function logout() {
  try {
    await fetch("/v1/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // best effort — even if it fails, redirecting lets the user log in fresh.
  }
  // Stay inside the Hive app (which auto-shows Login when no session); going
  // to "/" dumps the user at the external catalog page with no obvious way back.
  window.location.href = import.meta.env.BASE_URL || "/";
}

export function AppShell({ children }: { children?: ReactNode }) {
  const user = useUser();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const nav = fullNav;
  const shellTitle = "Hive Conductor";

  return (
    <div className="app-shell">
      <button
        className="hamburger"
        onClick={() => setDrawerOpen(true)}
        aria-label="Open menu"
      >
        <span /><span /><span />
      </button>

      <div className={`drawer-overlay${drawerOpen ? " open" : ""}`} onClick={() => setDrawerOpen(false)} />

      <nav className={`drawer${drawerOpen ? " open" : ""}`}>
        <div className="drawer-header">
          <span style={{ fontFamily: "var(--hand)", fontSize: 20, fontWeight: 700 }}>{shellTitle}</span>
          <ModeToggle />
          <AppearanceToggle />
          <button className="drawer-close" onClick={() => setDrawerOpen(false)} aria-label="Close menu">&#x2715;</button>
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", padding: "0 12px 8px" }}>
          Multi-agent · multi-MCP · Force Convergence sandbox
        </div>
        {user && (
          <div className="drawer-user">
            <span className="hex-badge" style={{ background: user.role === "admin" ? "var(--danger)" : "var(--accent)", color: "var(--paper)" }}>{user.role}</span>
            <NavLink to="/profile" style={{ fontFamily: "var(--mono)", fontSize: 10, color: "inherit", textDecoration: "none" }}>{user.username}</NavLink>
            {user.did && <span style={{ fontSize: 8, opacity: 0.6 }} title={user.did}>DID</span>}
          </div>
        )}
        <div className="drawer-nav">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `drawer-link${isActive ? " active" : ""}`}
              end={item.to === "/cli"}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-link-icon"><item.icon size={16} strokeWidth={1.5} /></span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button className="drawer-link" style={{ borderTop: "1px solid var(--rule)", marginTop: 8 }} onClick={() => void logout()}>
          <span className="drawer-link-icon">&#x2192;</span>
          <span>Sign out {user?.username}</span>
        </button>
      </nav>

      <nav className="icon-sidebar">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `nav-icon${isActive ? " active" : ""}`}
            end={item.to === "/cli"}
            title={item.label}
          >
            <span aria-hidden><item.icon size={16} strokeWidth={1.5} /></span>
            <span className="nav-icon-label">{item.label}</span>
          </NavLink>
        ))}
        <div style={{ flex: 1 }} />
        <AppearanceToggle />
        {user && (
          <div
            className="nav-icon"
            style={{
              color: "var(--pencil)",
              fontSize: 9,
              fontFamily: "var(--mono)",
              lineHeight: 1.2,
              textAlign: "center",
              padding: "6px 0",
              borderTop: "1px solid var(--rule)",
              marginTop: 4,
            }}
            title={`Signed in as ${user.username} (${user.role}) — click to sign out`}
          >
            <span
              style={{
                display: "inline-block",
                padding: "1px 4px",
                borderRadius: 2,
                background: user.role === "admin" ? "var(--danger)" : "var(--accent)",
                color: "var(--paper)",
                fontWeight: 700,
                fontSize: 7,
                letterSpacing: 0.5,
              }}
            >
              {(user.role || "user").toUpperCase()}
            </span>
            <div style={{ fontSize: 8, marginTop: 3, color: "var(--ink)" }}>
              {user.username}
            </div>
          </div>
        )}
        <button
          type="button"
          className="nav-icon"
          style={{
            background: "none",
            border: "none",
            color: "var(--danger)",
            cursor: "pointer",
            fontSize: 18,
            padding: "10px 0",
          }}
          onClick={() => void logout()}
          title="Sign out"
          aria-label="Sign out"
        >
          <span aria-hidden>⎋</span>
          <span className="nav-icon-label" style={{ color: "var(--danger)" }}>Sign out</span>
        </button>
      </nav>
      <main className="main-content">
        <div className="workspace-toolbar">
          <WorkspaceTabs />
          <WorkspaceShare />
          <WorkspaceToolBindings />
          <PersonaWizard />
        </div>
        {children ?? <Outlet />}
      </main>
    </div>
  );
}