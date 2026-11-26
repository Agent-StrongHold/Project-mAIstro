import { type ReactNode, useEffect, useRef, useState } from "react";
import { clearUiState } from "../lib/uiState";
import { LandingSuggestionBanner } from "./LandingSuggestionBanner";
import { LastSurfaceTracker } from "./LastSurfaceTracker";
import { NavLink, Outlet } from "react-router-dom";
import { useUser } from "../App";
import { useAuthorization } from "../context/AuthorizationContext";
import { AppearanceToggle } from "./AppearanceToggle";
import { DegradedBanner } from "./DegradedBanner";
import { WorkspaceTabs } from "./WorkspaceTabs";
import { WorkspaceShare } from "./WorkspaceShare";
import { WorkspaceAgentPersonaControl } from "./WorkspaceAgentPersona";
import { WorkspaceToolBindings } from "./WorkspaceToolBindings";
import { PersonaWizard } from "./PersonaWizard";
import {
  MessageCircle,
  Home,
  Target,
  Flag,
  Brain,
  KeyRound,
  Palette,
  Settings,
  Workflow,
  PlayCircle,
  Boxes,
  Repeat,
  ListTodo,
  CalendarClock,
  Bell,
  Gauge,
  ScrollText,
  Terminal,
  Container,
  ClipboardCheck,
} from "lucide-react";

const fullNav = [
  // #1048 / #2274: Home is the default Workspace landing; legacy Dashboard
  // page deleted (old /dashboard URL redirects to /home).
  { to: "/home", icon: Home, label: "Home" },
  { to: "/chat", icon: MessageCircle, label: "Chat" },
  { to: "/goals", icon: Flag, label: "Goals" },
  // #1049: Attention projection. The API requires dags.write (HITL sensitivity);
  // the setup daily user holds that grant, so the entry is not scope-gated in
  // the shell the way Schedules/Containers are.
  { to: "/attention", icon: Bell, label: "Attention" },
  // #2278: minimal approvals projection (capability inbox + HITL) — same
  // authority as API/CLI; not a parallel store.
  { to: "/approvals", icon: ClipboardCheck, label: "Approvals" },
  // #95: Design Studio is the parent creative-production surface, so it is a
  // first-class nav destination at its canonical route. Canvas is a tool it
  // consumes, not a sibling studio; the implementation-era /cli/canvas path is
  // only a compatibility redirect (App.tsx).
  { to: "/design-studio", icon: Palette, label: "Design Studio" },
  { to: "/dags", icon: Workflow, label: "DAG Builder" },
  { to: "/dag-runs", icon: PlayCircle, label: "DAG Runs" },
  // #1417: Schedules is a retained shipped surface (retirement ledger:
  // PROJECT onto the canonical ScheduleStore, #92) that no link anywhere
  // reached; it is entry-point discoverability, not a promotion decision —
  // its replacement still owns the cutover, see docs/route-inventory.md.
  // `scope` mirrors AuthMiddleware's mutation gate so the entry only shows
  // for sessions that can actually act on the page (#1417 review).
  { to: "/schedules", icon: CalendarClock, label: "Schedules", scope: "schedules.write" },
  // Missions was reachable only from `pocNav`, so retiring POC mode left a
  // live route with no entry point anywhere in the app — the page still
  // renders, `App.tsx` still registers it, and a repo-wide search finds no
  // other Link or NavLink to it (#129).
  { to: "/missions", icon: Target, label: "Missions" },
  // #99: editable backlog (board/list/detail) over the canonical service.
  { to: "/backlog", icon: ListTodo, label: "Backlog" },
  // #2273: one Capabilities surface; Agents / MCP / Skills / Topology pages
  // are deleted (old URLs redirect to /capabilities — not revived).
  { to: "/capabilities", icon: Boxes, label: "Capabilities" },
  // #1049 MERGE: Optimizer + Messages nav entries removed — both surfaces
  // project into Attention. Old /optimizer and /messages URLs redirect there.
  // #1417: Quotas, Containers, CLI and Audit were registered routes with no
  // navigation entry (audit GLO-01). Each is a retained surface per the
  // cutover plan (PROJECT rows, and CLI/Containers under contracts #292/#382),
  // so they stay discoverable; legacy pages scheduled for replacement
  // (Agents, Topology, Integrations, Skills, Work Items, Memory) stay off
  // this list — docs/route-inventory.md. Evolution: #2275 hid the route for
  // v1.0 (restore v1.2 / #51).
  { to: "/quotas", icon: Gauge, label: "Quotas" },
  { to: "/knowledge", icon: Brain, label: "Inner Temple" },
  // M0 containment for #311: Deck Builder is intentionally absent until
  // model-authored HTML/SVG has a canonical sanitizer/structured renderer.
  { to: "/rsi", icon: Repeat, label: "RSI", surface: "rsi" },
  // #1417: CLI and Containers keep their v1.0 contract lanes (#292, #382),
  // so they stay shipped and must stay reachable while those run.
  // `scope` as above: every Containers mutation requires containers.control
  // (backend/middleware/auth.py), so hide the entry without it.
  { to: "/containers", icon: Container, label: "Containers", scope: "containers.control" },
  { to: "/cli", icon: Terminal, label: "CLI" },
  { to: "/credentials", icon: KeyRound, label: "Credentials" },
  { to: "/audit", icon: ScrollText, label: "Audit" },
  { to: "/settings", icon: Settings, label: "Settings" },
];


// #1417 review: gated entries are only shown for sessions the canonical
// authorization policy lets act on them (admins pass every gate, as in the
// backend), so the nav never advertises a screen whose mutations all 403.
async function logout() {
  try {
    // frontend-typed-client: allow pre-existing banked raw fetch (was :60); line shifted by the #97 DegradedBanner import/render above.
    await fetch("/v1/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // best effort — even if it fails, redirecting lets the user log in fresh.
  }
  // Nothing of this account's stays behind for the next one (#1418).
  clearUiState();
  // Stay inside the Hive app (which auto-shows Login when no session); going
  // to "/" dumps the user at the external catalog page with no obvious way back.
  window.location.href = import.meta.env.BASE_URL || "/";
}

export function AppShell({ children }: { children?: ReactNode }) {
  const user = useUser();
  const authorization = useAuthorization();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  // Keyboard journeys (#370): opening the drawer moves focus into the menu;
  // closing it (Escape, overlay click, or nav) restores focus to the trigger
  // instead of stranding the user on <body> so the next Tab restarts the page.
  useEffect(() => {
    if (drawerOpen) {
      drawerRef.current?.querySelector<HTMLElement>("a, button")?.focus();
    } else if (isMobile) {
      menuButtonRef.current?.focus();
    }
  }, [drawerOpen, isMobile]);
  const nav = fullNav.filter((item) => {
    // One canonical filter for both gating spellings: `surface` resolves
    // through the SURFACE_POLICY contract served at /v1/auth/capabilities,
    // `scope` (#1417) names the same API-enforced permission directly. UI
    // filtering is convenience only — the API re-checks every request (#373).
    const permission = item.surface
      ? authorization.surfacePermission(item.surface)
      : item.scope;
    if (!permission) {
      // A gated entry whose permission cannot be resolved fails closed;
      // ungated entries stay for every authenticated session.
      return !item.surface && !item.scope;
    }
    // Keep a grant that only needs self-elevation reachable so the user can
    // see the explanation and elevate; hide surfaces they cannot ever use.
    return authorization.can(permission) || authorization.canElevate(permission);
  });
  const shellTitle = "Hive Conductor";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      {/* #1050/#1822: stamp last surface for recent-return landing. */}
      <LastSurfaceTracker />
      <button
        ref={menuButtonRef}
        className="hamburger"
        onClick={() => setDrawerOpen(true)}
        aria-label="Open menu"
        aria-expanded={drawerOpen}
        aria-controls="mobile-navigation"
      >
        <span /><span /><span />
      </button>

      <div
        className={`drawer-overlay${drawerOpen ? " open" : ""}`}
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />

      <nav
        ref={drawerRef}
        id="mobile-navigation"
        className={`drawer${drawerOpen ? " open" : ""}`}
        aria-label="Primary navigation"
        aria-hidden={isMobile && !drawerOpen}
        inert={isMobile && !drawerOpen ? true : undefined}
      >
        <div className="drawer-header">
          <span style={{ fontFamily: "var(--hand)", fontSize: 20, fontWeight: 700 }}>{shellTitle}</span>
          <AppearanceToggle />
          <button className="drawer-close" onClick={() => setDrawerOpen(false)} aria-label="Close menu">&#x2715;</button>
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", padding: "0 12px 8px" }}>
          Multi-agent · multi-MCP · Force Convergence sandbox
        </div>
        {user && (
          <div className="drawer-user">
            <span className="hex-badge" style={{ background: user.role === "admin" ? "var(--danger)" : "var(--accent)", color: "var(--paper)" }}>{user.role}</span>
            <NavLink to="/profile" style={{ fontFamily: "var(--mono)", fontSize: 12, color: "inherit", textDecoration: "none" }}>{user.username}</NavLink>
            {user.did && <span style={{ fontSize: 12, opacity: 0.6 }} title={user.did}>DID</span>}
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
              title={item.surface && !authorization.can(authorization.surfacePermission(item.surface)) ? "Requires elevation" : item.label}
            >
              <span className="drawer-link-icon"><item.icon size={16} strokeWidth={1.5} /></span>
              <span>{item.label}{item.surface && !authorization.can(authorization.surfacePermission(item.surface)) ? " · locked" : ""}</span>
            </NavLink>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button className="drawer-link" style={{ borderTop: "1px solid var(--rule)", marginTop: 8 }} onClick={() => void logout()}>
          <span className="drawer-link-icon">&#x2192;</span>
          <span>Sign out {user?.username}</span>
        </button>
      </nav>

      <nav className="icon-sidebar" aria-label="Primary navigation">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `nav-icon${isActive ? " active" : ""}`}
            end={item.to === "/cli"}
            title={item.surface && !authorization.can(authorization.surfacePermission(item.surface)) ? "Requires elevation" : item.label}
          >
            <span aria-hidden><item.icon size={16} strokeWidth={1.5} /></span>
            <span className="nav-icon-label">{item.label}{item.surface && !authorization.can(authorization.surfacePermission(item.surface)) ? " · locked" : ""}</span>
          </NavLink>
        ))}
        <div style={{ flex: 1 }} />
        <AppearanceToggle />
        {user && (
          <div
            className="nav-icon"
            style={{
              color: "var(--pencil)",
              fontSize: 12,
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
                fontSize: 12,
                letterSpacing: 0.5,
              }}
            >
              {(user.role || "user").toUpperCase()}
            </span>
            <div style={{ fontSize: 12, marginTop: 3, color: "var(--ink)" }}>
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
      <main id="main-content" className="main-content" tabIndex={-1}>
        {/* M3-B7 (#97): degraded mode is a user-facing operating state —
            the banner names every degraded optional capability from
            /health and disappears on its own when they recover. */}
        <DegradedBanner />
        {/* #1050: non-blocking learned-landing proposal (preference-aware). */}
        <LandingSuggestionBanner />
        <div className="workspace-toolbar">
          <WorkspaceTabs />
          <WorkspaceShare />
          <WorkspaceAgentPersonaControl />
          <WorkspaceToolBindings />
          <PersonaWizard />
        </div>
        {children ?? <Outlet />}
      </main>
    </div>
  );
}