import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ModeProvider } from "./components/ModeToggle";
import { Onboarding } from "./components/Onboarding";
import { ToastProvider } from "./components/shared";
import { PocModeProvider, usePmPoc } from "./context/PocMode";
import { WorkspaceProvider } from "./context/WorkspaceContext";
import Agents from "./pages/Agents";
import Fleet from "./pages/Fleet";
import AuditLog from "./pages/AuditLog";
import Chat from "./pages/Chat";
import CLI from "./pages/CLI";
import Containers from "./pages/Containers";
import DagBuilder from "./pages/DagBuilder";
import DagRuns from "./pages/DagRuns";
import Dashboard from "./pages/Dashboard";
import DesignStudio from "./pages/DesignStudio";
import Docs from "./pages/Docs";
import Evolution from "./pages/Evolution";
import RSI from "./pages/RSI";
import Login from "./pages/Login";
import MCP from "./pages/MCP";
import Memory from "./pages/Memory";
import MessageBoard from "./pages/MessageBoard";
import Missions from "./pages/Missions";
import OptimizationInbox from "./pages/OptimizationInbox";
import Quotas from "./pages/Quotas";
import Schedules from "./pages/Schedules";
import Settings from "./pages/Settings";
import Profile from "./pages/Profile";
import Credentials from "./pages/Credentials";
import Setup from "./pages/Setup";
import Skills from "./pages/Skills";
import Topology from "./pages/Topology";
import WorkItems from "./pages/WorkItems";
import KnowledgeBase from "./pages/KnowledgeBase";
import DeckBuilder from "./pages/DeckBuilder";
import ToolsLab from "./pages/ToolsLab";

type UserInfo = {
  id: string;
  username: string;
  role: "admin" | "user";
  permissions: string[];
  did: string | null;
  elevated: boolean;
  elevated_until: number | null;
};

const UserCtx = createContext<UserInfo | null>(null);
export const useUser = () => useContext(UserCtx);

function AuthGuard({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [setupDone, setSetupDone] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);

  async function loadSession(): Promise<UserInfo | null> {
    const whoRes = await fetch("/v1/auth/whoami", { credentials: "same-origin" });
    const whoData = await whoRes.json();
    if (whoData.authenticated && whoData.user) {
      return whoData.user as UserInfo;
    }
    return null;
  }

  useEffect(() => {
    (async () => {
      try {
        const setupRes = await fetch("/v1/setup/status", { credentials: "same-origin" });
        const setupData = await setupRes.json();
        if (!setupData.setup_complete) {
          setSetupDone(false);
          setReady(true);
          return;
        }
        setSetupDone(true);
        setUser(await loadSession());
      } catch {
        setSetupDone(false);
      }
      setReady(true);
    })();
  }, []);

  async function handleAuthenticated() {
    const next = await loadSession();
    if (next) {
      setUser(next);
    }
  }

  if (!ready) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e9e3d3", fontFamily: "var(--hand)", fontSize: 24, color: "var(--pencil)" }}>
        loading hive...
      </div>
    );
  }

  if (!setupDone) {
    return <Setup />;
  }

  if (!user) {
    return <Login onAuthenticated={handleAuthenticated} />;
  }

  return (
    <UserCtx.Provider value={user}>
      <WorkspaceProvider>
        <OnboardingGate />
        {children}
      </WorkspaceProvider>
    </UserCtx.Provider>
  );
}

// Rendered only once authenticated: on a fresh install the Setup wizard and
// Login screen must never be covered by the onboarding modal.
function OnboardingGate() {
  const [showOnboarding, setShowOnboarding] = useState(() => !localStorage.getItem("hive_onboarded"));
  if (!showOnboarding) {
    return null;
  }
  return <Onboarding onComplete={() => setShowOnboarding(false)} />;
}

function AppRoutes() {
  const pmPoc = usePmPoc();

  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route
        path="/*"
        element={
          <AuthGuard>
            <Routes>
              <Route path="/" element={<AppShell />}>
                <Route index element={<Navigate to={pmPoc ? "chat" : "dashboard"} replace />} />
                <Route path="dashboard" element={<Dashboard />} />
                <Route path="chat" element={<Chat />} />
                <Route path="missions" element={<Missions />} />
                <Route path="dags" element={<DagBuilder />} />
                <Route path="dag-runs" element={<DagRuns />} />
                <Route path="schedules" element={<Schedules />} />
                <Route path="agents" element={pmPoc ? <Fleet /> : <Agents />} />
                <Route path="work-items" element={<WorkItems />} />
                <Route path="knowledge" element={<KnowledgeBase />} />
                <Route path="decks" element={<DeckBuilder />} />
                <Route path="tools-lab" element={<ToolsLab />} />
                <Route path="skills" element={<Skills />} />
                <Route path="mcp" element={<MCP />} />
                <Route path="topology" element={<Topology />} />
                <Route path="optimizer" element={<OptimizationInbox />} />
                <Route path="optimization-inbox" element={<OptimizationInbox />} />
                <Route path="messages" element={<MessageBoard />} />
                <Route path="quotas" element={<Quotas />} />
                <Route path="audit" element={<AuditLog />} />
                <Route path="cli" element={<CLI />} />
                <Route path="cli/canvas" element={<DesignStudio />} />
                <Route path="containers" element={<Containers />} />
                <Route path="docs" element={<Docs />} />
                <Route path="evolution" element={<Evolution />} />
                <Route path="rsi" element={<RSI />} />
                <Route path="memory" element={<Memory />} />
                <Route path="settings" element={<Settings />} />
                <Route path="profile" element={<Profile />} />
                <Route path="credentials" element={<Credentials />} />
              </Route>
            </Routes>
          </AuthGuard>
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <ModeProvider>
          <PocModeProvider>
            <AppRoutes />
          </PocModeProvider>
        </ModeProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
