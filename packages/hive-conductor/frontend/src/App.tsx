import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Onboarding } from "./components/Onboarding";
import { ToastProvider } from "./components/shared";
import { claimUiState } from "./lib/uiState";
import { WorkspaceProvider } from "./context/WorkspaceContext";
import Login from "./pages/Login";
import Setup from "./pages/Setup";

// Routed pages (#1435): each is its own chunk, fetched only when its route
// is visited, instead of every page's code riding along in the one bundle
// Setup and Login (above) stay eager -- one of them is needed for the very
// first paint of every session, so splitting them would only add a round
// trip with nothing to show meanwhile.
const Agents = lazy(() => import("./pages/Agents"));
const AuditLog = lazy(() => import("./pages/AuditLog"));
const Chat = lazy(() => import("./pages/Chat"));
const CLI = lazy(() => import("./pages/CLI"));
const Containers = lazy(() => import("./pages/Containers"));
const DagBuilder = lazy(() => import("./pages/DagBuilder"));
const DagRuns = lazy(() => import("./pages/DagRuns"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const DesignStudio = lazy(() => import("./pages/DesignStudio"));
const DeckBuilder = lazy(() => import("./pages/DeckBuilder"));
const Docs = lazy(() => import("./pages/Docs"));
const Evolution = lazy(() => import("./pages/Evolution"));
const RSI = lazy(() => import("./pages/RSI"));
const MCP = lazy(() => import("./pages/MCP"));
const Memory = lazy(() => import("./pages/Memory"));
const MessageBoard = lazy(() => import("./pages/MessageBoard"));
const Missions = lazy(() => import("./pages/Missions"));
const OptimizationInbox = lazy(() => import("./pages/OptimizationInbox"));
const Quotas = lazy(() => import("./pages/Quotas"));
const Schedules = lazy(() => import("./pages/Schedules"));
const Settings = lazy(() => import("./pages/Settings"));
const Profile = lazy(() => import("./pages/Profile"));
const Credentials = lazy(() => import("./pages/Credentials"));
const Skills = lazy(() => import("./pages/Skills"));
const Topology = lazy(() => import("./pages/Topology"));
const WorkItems = lazy(() => import("./pages/WorkItems"));
const KnowledgeBase = lazy(() => import("./pages/KnowledgeBase"));

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

/** Application chrome, painted before the setup/whoami round trip resolves
 * (#1408): the same sidebar-plus-content grid the real shell uses, standing
 * in for what is about to render rather than a sentence on a blank screen.
 * Nothing here is interactive -- it carries no nav labels or real counts,
 * so it never claims to be data the fetch hasn't answered yet. */
function AppShellSkeleton() {
  return (
    <div className="app-shell" aria-busy="true" aria-label="Loading Hive Conductor">
      <div className="icon-sidebar">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="skeleton-nav-icon" />
        ))}
      </div>
      <main className="main-content">
        <div className="skeleton-block" style={{ width: "40%", height: 22, marginBottom: 18 }} />
        <div className="skeleton-block" style={{ width: "100%", height: 120, marginBottom: 12 }} />
        <div className="skeleton-block" style={{ width: "70%", height: 16 }} />
      </main>
    </div>
  );
}

function whoamiToUser(whoData: { authenticated?: boolean; user?: UserInfo }): UserInfo | null {
  if (whoData.authenticated && whoData.user) {
    const next = whoData.user;
    // Before anything under the guard mounts and reads localStorage: a
    // different account's remembered tab, scheme or tour state is cleared
    // here, not inherited (#1418, #1433).
    claimUiState(next.id);
    return next;
  }
  return null;
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [setupDone, setSetupDone] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);

  async function loadSession(): Promise<UserInfo | null> {
    const whoRes = await fetch("/v1/auth/whoami", { credentials: "same-origin" });
    return whoamiToUser(await whoRes.json());
  }

  useEffect(() => {
    (async () => {
      try {
        // Fired together, not one after another (#1408): whoami's answer
        // does not depend on setup being finished -- it reports
        // unauthenticated either way, since no session cookie exists before
        // setup runs -- so paying for the two round trips in series bought
        // nothing but the wait. But only setup's own response gates the
        // Setup wizard: on a fresh, unconfigured instance a slow or
        // never-settling whoami must not hold up detecting that setup isn't
        // done, so whoami is only awaited once setup is confirmed complete.
        const setupPromise = fetch("/v1/setup/status", { credentials: "same-origin" });
        const whoPromise = fetch("/v1/auth/whoami", { credentials: "same-origin" });
        const setupData = await (await setupPromise).json();
        if (!setupData.setup_complete) {
          setSetupDone(false);
          setReady(true);
          return;
        }
        const whoData = await (await whoPromise).json();
        setSetupDone(true);
        setUser(whoamiToUser(whoData));
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
    return <AppShellSkeleton />;
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
  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route
        path="/*"
        element={
          <AuthGuard>
            <Suspense fallback={<AppShellSkeleton />}>
              <Routes>
                <Route path="/" element={<AppShell />}>
                  <Route index element={<Navigate to="dashboard" replace />} />
                  <Route path="dashboard" element={<Dashboard />} />
                  <Route path="chat" element={<Chat />} />
                  <Route path="missions" element={<Missions />} />
                  <Route path="dags" element={<DagBuilder />} />
                  <Route path="dag-runs" element={<DagRuns />} />
                  <Route path="schedules" element={<Schedules />} />
                  <Route path="agents" element={<Agents />} />
                  <Route path="work-items" element={<WorkItems />} />
                  <Route path="knowledge" element={<KnowledgeBase />} />
                  {/* #311 M0 containment lifted: the M2 Deck sanitizer
                      (lib/deckSanitizer.ts, #752/#873) now sanitizes every
                      render sink, so the keyboard-complete Deck editor (#769)
                      is reachable at /decks and from Design Studio. */}
                  <Route path="decks" element={<DeckBuilder />} />
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
            </Suspense>
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
        <AppRoutes />
      </ToastProvider>
    </ErrorBoundary>
  );
}