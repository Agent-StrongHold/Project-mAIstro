import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../lib/api";
import { applyAppearance } from "../lib/appearance";

export type WorkspaceRole = "owner" | "editor" | "viewer";

export type WorkspaceMember = {
  user_id: string;
  role: WorkspaceRole;
};

export type AgentToolBinding = {
  agent_id: string;
  tools: string[];
  prompt_fragment: string;
};

export type Workspace = {
  id: string;
  persona_template_id: string;
  name: string;
  theme_id: string;
  voice_tone_override: string | null;
  members: WorkspaceMember[];
  tool_bindings: AgentToolBinding[];
  active: boolean;
};

type CreateWorkspaceInput = {
  name: string;
  persona_template_id: string;
};

type WorkspaceCtxValue = {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  activeWorkspace: Workspace | null;
  ready: boolean;
  selectWorkspace: (id: string) => void;
  createWorkspace: (input: CreateWorkspaceInput) => Promise<Workspace>;
  archiveWorkspace: (id: string, active: boolean) => Promise<void>;
  deleteWorkspace: (id: string) => Promise<void>;
  refresh: () => Promise<void>;
};

const noop = () => {};

const WorkspaceCtx = createContext<WorkspaceCtxValue>({
  workspaces: [],
  activeWorkspaceId: null,
  activeWorkspace: null,
  ready: false,
  selectWorkspace: noop,
  createWorkspace: () => Promise.reject(new Error("WorkspaceProvider not mounted")),
  archiveWorkspace: () => Promise.reject(new Error("WorkspaceProvider not mounted")),
  deleteWorkspace: () => Promise.reject(new Error("WorkspaceProvider not mounted")),
  refresh: () => Promise.resolve(),
});

const ACTIVE_WORKSPACE_KEY = "hive_active_workspace_id";

/** Keep the current selection if it's still present and not archived;
 * otherwise fall back to the first non-archived workspace. Archiving the
 * currently-active workspace must not leave the tab bar pointing at a tab
 * that no longer renders. */
function nextActiveId(current: string | null, list: Workspace[]): string | null {
  if (current && list.some((w) => w.id === current && w.active !== false)) {
    return current;
  }
  return list.find((w) => w.active !== false)?.id ?? null;
}

/** A user's live Workspace tabs (Persona/Workspace system). Mount this only
 * once authenticated -- GET /v1/workspaces requires a session. */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(() =>
    localStorage.getItem(ACTIVE_WORKSPACE_KEY),
  );
  const [ready, setReady] = useState(false);

  async function refresh() {
    try {
      const list = await apiGet<Workspace[]>("/v1/workspaces");
      setWorkspaces(list);
      setActiveWorkspaceId((current) => nextActiveId(current, list));
    } catch {
      // No workspaces yet, or the account can't reach the route -- the tab
      // bar degrades to "no tabs" rather than breaking the app shell.
      setWorkspaces([]);
    } finally {
      setReady(true);
    }
  }

  useEffect(() => {
    // Inline IIFE: async work in an effect, cancelled on unmount.
    // rather than calling the named `refresh` function directly, which
    // avoids react-hooks/set-state-in-effect flagging a top-level effect
    // call that eventually setStates.
    let cancelled = false;
    (async () => {
      try {
        const list = await apiGet<Workspace[]>("/v1/workspaces");
        if (cancelled) return;
        setWorkspaces(list);
        setActiveWorkspaceId((current) => nextActiveId(current, list));
      } catch {
        if (!cancelled) setWorkspaces([]);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (activeWorkspaceId) {
      localStorage.setItem(ACTIVE_WORKSPACE_KEY, activeWorkspaceId);
    } else {
      localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
    }
  }, [activeWorkspaceId]);

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) ?? null;

  useEffect(() => {
    const themeId = activeWorkspace?.theme_id;
    if (themeId && themeId !== "default") {
      document.documentElement.dataset.theme = themeId;
    } else {
      // No workspace theme override -- fall back to the user's app-level
      // light/dark appearance rather than always forcing light.
      delete document.documentElement.dataset.theme;
      applyAppearance();
    }
  }, [activeWorkspace?.theme_id]);

  async function createWorkspace(input: CreateWorkspaceInput): Promise<Workspace> {
    const created = await apiPost<Workspace>("/v1/workspaces", input);
    setWorkspaces((prev) => [...prev, created]);
    setActiveWorkspaceId(created.id);
    return created;
  }

  function selectWorkspace(id: string) {
    setActiveWorkspaceId(id);
  }

  async function archiveWorkspace(id: string, active: boolean): Promise<void> {
    await apiPatch<Workspace>(`/v1/workspaces/${id}`, { active });
    await refresh();
  }

  async function deleteWorkspace(id: string): Promise<void> {
    await apiDelete(`/v1/workspaces/${id}`);
    await refresh();
  }

  return (
    <WorkspaceCtx.Provider
      value={{
        workspaces,
        activeWorkspaceId,
        activeWorkspace,
        ready,
        selectWorkspace,
        createWorkspace,
        archiveWorkspace,
        deleteWorkspace,
        refresh,
      }}
    >
      {children}
    </WorkspaceCtx.Provider>
  );
}

// Provider and hook in one file, the established shape for this app's contexts.
// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspaces(): WorkspaceCtxValue {
  return useContext(WorkspaceCtx);
}
