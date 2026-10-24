/** Workspace Home wire shapes (#1048). Kept under `lib/` so pages consume
 * shared types instead of minting hand-typed contracts in `pages/` (typed-client
 * ratchet). Mirrors the JSON returned by `routes/home.py` /
 * `services.home_layouts` / `services.home_projections`. */

export type HomeRegion = {
  id: string;
  kind: string;
  pinned: boolean;
  position: number;
  size: string;
  resource_type: string;
  resource_id: string | null;
  reason: string | null;
};

export type HomeLayout = {
  revision: number;
  updatedAt: string;
  regions: HomeRegion[];
};

export type HomeProjectionItem = {
  resource_type: string;
  resource_id: string;
  title: string;
  href: string;
  updated_at: string | null;
};

export type HomeProjectionSection = {
  kind: string;
  status: "ok" | "empty" | "unavailable";
  items: HomeProjectionItem[];
  reason?: string | null;
};

export type HomeProjections = {
  workspace_id: string;
  generated_at: string;
  sections: HomeProjectionSection[];
  dismissed: Record<string, number>;
};

export type HomePinResult = {
  ok: boolean;
  revision: number;
  region: HomeRegion | null;
};

const KIND_LABELS: Record<string, string> = {
  goals: "Goals",
  backlog: "Backlog",
  runs: "Runs",
  chat: "Chat",
  design: "Design",
  attention: "Attention",
};

export function homeKindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export function layoutPath(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/home/layout`;
}

export function projectionsPath(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/home/projections`;
}

export function pinPath(workspaceId: string, regionId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/home/regions/${encodeURIComponent(regionId)}/pin`;
}
