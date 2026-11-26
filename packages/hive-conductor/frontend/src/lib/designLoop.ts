// M7-A12 (#988): shared client *projections* of the canonical design-loop
// records — a Project-scoped Goal revision (#458, `maistro.goals` identity
// `goal_id` with exact `goal_revision`), a CreativeBrief revision projected
// onto that exact revision (#774), and one canonical Graph/Run carrying the
// pack binding and the exploration params (#793/#984, ADR-092926-7a01: the
// loop is one Run). These are the shapes the owning surfaces return; the
// Design Studio page projects them through lib/api and never mints a
// product-local loop kind, and browser storage is never the system of record
// for loop state (#990: the one execution identity is Run/NodeRun/Attempt).

export type SurfaceStatus = "probing" | "ready" | "unavailable";
export type LoopSurface = { status: SurfaceStatus; cause: string | null };
export type LoopSurfaces = { packs: LoopSurface; goals: LoopSurface; briefs: LoopSurface; runs: LoopSurface };

export type PackSummary = {
  pack_id: string;
  name: string;
  summary: string;
  execute_backends: string[];
  artifact_kinds: string[];
};
export type GoalRecord = { goal_id: string; goal_revision: string | number; title: string };
export type BriefRecord = { brief_id: string; brief_revision: string | number; goal_id: string };
export type LoopRunRecord = { run_id: string; goal_id: string; pack_id: string; width: number; policy: string };
export type OpenLoop = { goal: GoalRecord; brief: BriefRecord; run: LoopRunRecord };

// The one closed pack set (#793). Presented as the selector listing the pack
// registry serves; a pack is a bundle of defaults for the one loop, never a
// route, a product, or a Goal identity.
export const PACK_IDS = ["product", "game", "book"] as const;
export const EXPLORATION_POLICIES = ["focused", "balanced", "wide"] as const;
export type ExplorationPolicy = (typeof EXPLORATION_POLICIES)[number];
export const DEFAULT_WIDTH = 3;
export const WIDTH_MIN = 1;
export const WIDTH_MAX = 8;
