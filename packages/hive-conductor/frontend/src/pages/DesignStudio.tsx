// Merged Design Studio surface (#768 × keyboard-complete Design Studio):
// - The brief/catalog shell and the structured FixedPageEditor/DeckBuilder
//   editor transitions come from the keyboard-complete rework (#370/#769).
// - The shared visual-artifact trust boundary (#768) owns every place raw
//   model/persisted markup could reach the browser: the inline
//   FixedPageArtifactEditor below sanitizes loaded, edited, persisted, and
//   exported markup through lib/visualArtifactRenderer, and persists the
//   pre-scan verdict alongside the sanitized markup so a hostile artifact can
//   never be re-read as trusted content.
import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader } from "../components/shared";
import { ApiError, apiGet, apiPost } from "../lib/api";
import DeckBuilder from "./DeckBuilder";
import FixedPageEditor from "./FixedPageEditor";
import FixedPageArtifactEditor, { type FixedPageMode } from "./FixedPageArtifactEditor";
import {
  recommendVisualArtifactTrust,
  sanitizeVisualArtifactMarkup,
  type VisualArtifactTrustRecommendation,
} from "../lib/visualArtifactRenderer";

type ArtifactModeId = "deck" | FixedPageMode;

const FIXED_PAGE_MODES: FixedPageMode[] = [
  "poster",
  "infographic",
  "flyer",
  "social",
  "card",
  "cover",
  "diagram",
  "custom",
];

type ArtifactMode = { id: ArtifactModeId; name: string; description: string };
type DiscoveryField = { key: string; label: string; description: string; field_type?: string; options?: string[]; required?: boolean; default?: string | null };
type DesignSkill = { slug: string; name: string; mode: string; description: string; render_slot: string | null; discovery_form?: DiscoveryField[] };
type DesignSystem = { slug: string; name: string };
type DesignSystemsResponse = { systems: DesignSystem[]; catalog: { available: boolean; cause: string | null; count: number }; ready: boolean; cause: string | null };
type CatalogState = { status: "loading" | "ready" | "degraded" | "unavailable"; skills: DesignSkill[]; systems: DesignSystem[]; message: string };
type DesignProject = {
  id: string;
  name: string;
  skill_slug: string;
  design_system_slug: string;
  output_count: number;
};

type ProjectState = {
  status: "loading" | "ready" | "unavailable";
  projects: DesignProject[];
  message: string;
};

// M7-A12 (#988): opening work in Design Studio mints canonical objects — a
// Project-scoped Goal revision (#458, `maistro.goals` identity `goal_id` with
// exact `goal_revision`), a CreativeBrief revision projected onto that exact
// revision (#774), and one canonical Graph/Run carrying the pack binding and
// the exploration params (#793/#984, ADR-092926-7a01: the loop is one Run).
// There is no DesignRun: these types are client *projections* of the canonical
// records returned by their owning surfaces, never a product-local kind.
type PackSummary = {
  pack_id: string;
  name: string;
  summary: string;
  execute_backends: string[];
  artifact_kinds: string[];
};
type GoalRecord = { goal_id: string; goal_revision: string | number; title: string };
type BriefRecord = { brief_id: string; brief_revision: string | number; goal_id: string };
type LoopRunRecord = { run_id: string; goal_id: string; pack_id: string; width: number; policy: string };
type OpenLoop = { goal: GoalRecord; brief: BriefRecord; run: LoopRunRecord };
type SurfaceStatus = "probing" | "ready" | "unavailable";
type LoopSurface = { status: SurfaceStatus; cause: string | null };
type LoopSurfaces = { packs: LoopSurface; goals: LoopSurface; briefs: LoopSurface; runs: LoopSurface };

// The one closed pack set (#793). Presented as the selector listing the pack
// registry serves; a pack is a bundle of defaults for the one loop, never a
// route, a product, or a Goal identity.
const PACK_IDS = ["product", "game", "book"] as const;
const EXPLORATION_POLICIES = ["focused", "balanced", "wide"] as const;
type ExplorationPolicy = (typeof EXPLORATION_POLICIES)[number];
const DEFAULT_WIDTH = 3;
const WIDTH_MIN = 1;
const WIDTH_MAX = 8;

const LOOP_SURFACE_LABELS: Record<keyof LoopSurfaces, string> = {
  packs: "Pack listing (/v1/design/packs, #793)",
  goals: "Goal revisions (/v1/goals, #458)",
  briefs: "CreativeBrief revisions (/v1/creative-briefs, #774)",
  runs: "Run mint (/v1/runs, ADR-092926-7a01)",
};

function loopSurfaceCause(err: unknown): string {
  if (err instanceof ApiError) return `HTTP ${err.status} from ${err.path}`;
  return err instanceof Error ? err.message : String(err);
}

function unavailableSurface(err: unknown): LoopSurface {
  return { status: "unavailable", cause: loopSurfaceCause(err) };
}

function readySurface(): LoopSurface {
  return { status: "ready", cause: null };
}

const LOOP_SURFACES_PROBING: LoopSurfaces = {
  packs: { status: "probing", cause: null },
  goals: { status: "probing", cause: null },
  briefs: { status: "probing", cause: null },
  runs: { status: "probing", cause: null },
};

const ARTIFACT_MODES: ArtifactMode[] = [
  { id: "deck", name: "Presentation / Deck", description: "Multi-page presentations with slide navigation, presentation mode, and deck export." },
  { id: "poster", name: "Poster", description: "Single fixed-page visual for print, signage, or display." },
  { id: "infographic", name: "Infographic", description: "Structured visual explanation combining data, text, and graphics." },
  { id: "flyer", name: "Flyer", description: "Compact promotional or informational one-page layout." },
  { id: "social", name: "Social graphic", description: "Fixed-size visual content for social channels and campaigns." },
  { id: "card", name: "Card", description: "Small-format announcement, invitation, or branded card." },
  { id: "cover", name: "Cover", description: "Cover art and title-page compositions for documents or media." },
  { id: "diagram", name: "Diagram / visual", description: "Explanatory diagrams, process visuals, and composed illustrations." },
  { id: "custom", name: "Custom canvas", description: "A custom fixed-size composition using the shared Design Studio workspace." },
];

function failureMessage(result: PromiseSettledResult<unknown>): string | null {
  if (result.status !== "rejected") return null;
  return result.reason instanceof Error ? result.reason.message : String(result.reason);
}

function resourceSummary(skillCount: number, systemCount: number): string {
  return `${skillCount} design skill${skillCount === 1 ? "" : "s"} and ${systemCount} design system${systemCount === 1 ? "" : "s"} available.`;
}

function fieldValue(field: DiscoveryField): string {
  return field.default ?? field.options?.[0] ?? "";
}

const FIXED_PAGE_STORAGE_KEY = "hive_design_studio_fixed_page_artifacts";

type PersistedFixedPageArtifact = {
  markup: string;
  trustRecommendation: VisualArtifactTrustRecommendation;
};

function isPersistedArtifact(value: unknown): value is PersistedFixedPageArtifact {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as PersistedFixedPageArtifact).markup === "string" &&
    ((value as PersistedFixedPageArtifact).trustRecommendation === "upgrade" ||
      (value as PersistedFixedPageArtifact).trustRecommendation === "review")
  );
}

function loadPersistedArtifacts(): Partial<Record<FixedPageMode, PersistedFixedPageArtifact>> {
  if (typeof window === "undefined") return {};

  try {
    const raw = window.localStorage.getItem(FIXED_PAGE_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};

    const stored = parsed as Record<string, unknown>;
    let changed = false;
    const migrated: Record<string, PersistedFixedPageArtifact> = {};
    const restored: Partial<Record<FixedPageMode, PersistedFixedPageArtifact>> = {};
    for (const mode of FIXED_PAGE_MODES) {
      const value = stored[mode];
      if (typeof value !== "string" && !isPersistedArtifact(value)) continue;
      if (isPersistedArtifact(value)) {
        restored[mode] = value;
        migrated[mode] = value;
        continue;
      }
      // Legacy string payloads (and any raw markup) keep the verdict the
      // pre-scan produced for their ORIGINAL content alongside the sanitized
      // markup. The recommendation must survive the storage migration: this
      // component can mount more than once per page load, and later mounts
      // would otherwise read the already-sanitized string and wrongly report
      // "upgrade" for content the boundary blocked.
      const artifact: PersistedFixedPageArtifact = {
        markup: sanitizeVisualArtifactMarkup(value),
        trustRecommendation: recommendVisualArtifactTrust(value),
      };
      restored[mode] = artifact;
      migrated[mode] = artifact;
      changed = true;
    }
    // Migrate old persisted content so later readers never receive raw markup.
    if (changed) window.localStorage.setItem(FIXED_PAGE_STORAGE_KEY, JSON.stringify(migrated));
    return restored;
  } catch {
    return {};
  }
}

export default function DesignStudio() {
  const headingRef = useRef<HTMLDivElement>(null);
  const [selectedMode, setSelectedMode] = useState<ArtifactModeId>("poster");
  const selectedModeRef = useRef<ArtifactModeId>("poster");
  const [prompt, setPrompt] = useState("");
  const [artifactMarkup, setArtifactMarkup] = useState<Partial<Record<FixedPageMode, PersistedFixedPageArtifact>>>(loadPersistedArtifacts);
  const [selectedSkillSlug, setSelectedSkillSlug] = useState("");
  const [selectedSystemSlug, setSelectedSystemSlug] = useState("default");
  const [responses, setResponses] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState<"fixed" | "deck" | null>(null);
  const [status, setStatus] = useState("Choose an artifact type, describe the brief, and open its editor.");
  const [catalog, setCatalog] = useState<CatalogState>({ status: "loading", skills: [], systems: [], message: "Checking design resources..." });
  const [projectState, setProjectState] = useState<ProjectState>({
    status: "loading",
    projects: [],
    message: "Loading persisted Design projects…",
  });
  const [loopSurfaces, setLoopSurfaces] = useState<LoopSurfaces>(LOOP_SURFACES_PROBING);
  const [selectedPackId, setSelectedPackId] = useState<string>("");
  const [packs, setPacks] = useState<PackSummary[]>([]);
  const [goalTitle, setGoalTitle] = useState("");
  const [desiredOutcome, setDesiredOutcome] = useState("");
  const [stopConditions, setStopConditions] = useState("");
  const [briefAudience, setBriefAudience] = useState("");
  const [briefConstraints, setBriefConstraints] = useState("");
  const [briefGuidance, setBriefGuidance] = useState("");
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [policy, setPolicy] = useState<ExplorationPolicy>("balanced");
  const [openingLoop, setOpeningLoop] = useState(false);
  const [openLoop, setOpenLoop] = useState<OpenLoop | null>(null);
  const [loopMessage, setLoopMessage] = useState("Checking the canonical loop surfaces (Goal, CreativeBrief, pack, Run)…");

  useEffect(() => {
    let cancelled = false;
    async function loadCatalog() {
      const [skillsResult, systemsResult, projectsResult] = await Promise.allSettled([
        apiGet<DesignSkill[]>("/v1/design/skills"),
        apiGet<DesignSystemsResponse>("/v1/design/systems"),
        apiGet<DesignProject[]>("/v1/design/projects"),
      ]);
      if (cancelled) return;
      const skills = skillsResult.status === "fulfilled" ? skillsResult.value : [];
      const systems = systemsResult.status === "fulfilled" ? systemsResult.value.systems : [];
      const failures = [failureMessage(skillsResult), failureMessage(systemsResult)].filter((message): message is string => message !== null);
      if (skills.length > 0) {
        const next = skills.find((candidate) => selectedModeRef.current === "deck" ? candidate.mode === "deck" : candidate.render_slot === "renderer.fixed-page") ?? skills[0];
        setSelectedSkillSlug((current) => current || next.slug);
        setResponses((current) => Object.keys(current).length > 0 ? current : Object.fromEntries((next.discovery_form ?? []).map((field) => [field.key, fieldValue(field)])));
      }
      const projectsFailure = failureMessage(projectsResult);
      if (projectsResult.status === "fulfilled") {
        const projects = projectsResult.value;
        setProjectState({
          status: "ready",
          projects,
          message: projects.length === 0
            ? "No persisted Design projects in this scope."
            : `${projects.length} persisted Design project${projects.length === 1 ? "" : "s"} in this scope.`,
        });
      } else {
        setProjectState({
          status: "unavailable",
          projects: [],
          message: `Persisted Design projects are unavailable: ${projectsFailure ?? "the Design service did not respond."}`,
        });
      }

      if (failures.length > 0) {
        setCatalog({ status: "unavailable", skills, systems, message: `Some design resources are unavailable: ${failures.join("; ")}` });
        return;
      }
      const response = systemsResult.status === "fulfilled" ? systemsResult.value : null;
      if (response && !response.catalog.available) {
        setCatalog({ status: "degraded", skills, systems, message: `${resourceSummary(skills.length, systems.length)} Additional design systems are unavailable: ${response.catalog.cause ?? "catalog unavailable"}` });
        return;
      }
      setCatalog({ status: "ready", skills, systems, message: resourceSummary(skills.length, systems.length) });
    }
    void loadCatalog();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    headingRef.current?.focus();
  }, [editor]);

  // M7-A12 (#988): discover whether the canonical loop surfaces exist before
  // offering the loop start. Every surface is probed for real; a missing one
  // leaves the control disabled with its actual cause (#286). Nothing is
  // simulated and no timer fakes readiness. The Goal read doubles as the
  // refresh restore: ids only ever come back from the APIs, never from
  // client-side storage.
  useEffect(() => {
    let cancelled = false;
    async function probeLoopSurfaces() {
      // frontend-api-routes: allow /v1/design/packs is the #793 pack-selector listing; not mounted at this base — its absence is the honest disabled cause (#988/#286).
      const packsProbe = apiGet<PackSummary[]>("/v1/design/packs");
      // frontend-api-routes: allow /v1/goals is the #458 Goal revisions surface; not mounted at this base — its absence is the honest disabled cause (#988/#286).
      const goalsProbe = apiGet<GoalRecord[]>("/v1/goals");
      // frontend-api-routes: allow /v1/creative-briefs is the #774 CreativeBrief revision surface; not mounted at this base — its absence is the honest disabled cause (#988/#286).
      const briefsProbe = apiGet<BriefRecord[]>("/v1/creative-briefs");
      // frontend-api-routes: allow /v1/runs is the canonical Run listing (loop mint, ADR-092926-7a01); not mounted at this base — its absence is the honest disabled cause (#988/#286).
      const runsProbe = apiGet<LoopRunRecord[]>("/v1/runs");
      const [packsResult, goalsResult, briefsResult, runsResult] = await Promise.allSettled([
        packsProbe,
        goalsProbe,
        briefsProbe,
        runsProbe,
      ]);
      if (cancelled) return;
      const nextSurfaces: LoopSurfaces = {
        packs: packsResult.status === "fulfilled" ? readySurface() : unavailableSurface(packsResult.reason),
        goals: goalsResult.status === "fulfilled" ? readySurface() : unavailableSurface(goalsResult.reason),
        briefs: briefsResult.status === "fulfilled" ? readySurface() : unavailableSurface(briefsResult.reason),
        runs: runsResult.status === "fulfilled" ? readySurface() : unavailableSurface(runsResult.reason),
      };
      if (packsResult.status === "fulfilled") {
        const listed = packsResult.value.filter((pack) => (PACK_IDS as readonly string[]).includes(pack.pack_id));
        setPacks(listed);
      }
      setLoopSurfaces(nextSurfaces);

      // Refresh restore: if a Goal already exists for this scope, adopt the
      // newest revision and its brief + run from the APIs. A missing record
      // simply means no loop is open; nothing is fabricated.
      if (goalsResult.status !== "fulfilled" || goalsResult.value.length === 0) {
        setLoopMessage(
          Object.values(nextSurfaces).every((surface) => surface.status === "ready")
            ? "Choose a pack and describe the Goal to open a loop."
            : "Opening a loop is disabled until the canonical surfaces above are available. Nothing is simulated in the meantime.",
        );
        return;
      }
      const goal = goalsResult.value[0];
      const [briefsForGoal, runsForGoal] = await Promise.allSettled([
        // frontend-api-routes: allow /v1/creative-briefs is the #774 CreativeBrief revision surface; not mounted at this base — its absence is the honest disabled cause (#988/#286).
        apiGet<BriefRecord[]>(`/v1/creative-briefs?goal_id=${encodeURIComponent(goal.goal_id)}`),
        // frontend-api-routes: allow /v1/runs is the canonical Run listing (loop mint, ADR-092926-7a01); not mounted at this base — its absence is the honest disabled cause (#988/#286).
        apiGet<LoopRunRecord[]>(`/v1/runs?goal_id=${encodeURIComponent(goal.goal_id)}`),
      ]);
      if (cancelled) return;
      const brief = briefsForGoal.status === "fulfilled" ? briefsForGoal.value.find((candidate) => candidate.goal_id === goal.goal_id) : undefined;
      const run = runsForGoal.status === "fulfilled" ? runsForGoal.value.find((candidate) => candidate.goal_id === goal.goal_id) : undefined;
      if (goal && brief && run) {
        setOpenLoop({ goal, brief, run });
        setSelectedPackId((current) => current || run.pack_id);
        setLoopMessage("Loop restored from the canonical records.");
      } else {
        setLoopMessage("Choose a pack and describe the Goal to open a loop.");
      }
    }
    void probeLoopSurfaces();
    return () => { cancelled = true; };
  }, []);

  const mode = ARTIFACT_MODES.find((candidate) => candidate.id === selectedMode) ?? ARTIFACT_MODES[0];
  const skill = catalog.skills.find((candidate) => candidate.slug === selectedSkillSlug);
  const systemSlug = catalog.systems.some((system) => system.slug === selectedSystemSlug) ? selectedSystemSlug : (catalog.systems[0]?.slug ?? selectedSystemSlug);
  const canOpenEditor = prompt.trim().length > 0;
  const canSaveProject = canOpenEditor && Boolean(skill && systemSlug);

  // M7-A12 (#988): the loop start is gated on the REAL availability of every
  // canonical surface it must mint, and on the Goal fields being present.
  const missingSurfaces = (Object.keys(LOOP_SURFACE_LABELS) as (keyof LoopSurfaces)[]).filter(
    (key) => loopSurfaces[key].status !== "ready",
  );
  const loopFieldsReady = Boolean(selectedPackId) && goalTitle.trim().length > 0 && desiredOutcome.trim().length > 0 && stopConditions.trim().length > 0;
  const loopDisabledCause = openLoop
    ? "Loop already open. Refresh restores its ids from the canonical records."
    : missingSurfaces.length > 0
      ? `Cannot open a loop: ${missingSurfaces.map((key) => `${LOOP_SURFACE_LABELS[key]} is ${loopSurfaces[key].status === "probing" ? "still being checked" : `unavailable (${loopSurfaces[key].cause})`}`).join("; ")}. Nothing is simulated while a surface is missing.`
      : !loopFieldsReady
        ? "Choose a pack, then give the Goal its title, desired outcome, and stop conditions."
        : null;
  const canOpenLoop = loopFieldsReady && missingSurfaces.length === 0 && !openingLoop && !openLoop;

  async function openDesignLoop(): Promise<void> {
    if (!canOpenLoop) {
      setLoopMessage(loopDisabledCause ?? "Opening a loop is not available right now.");
      return;
    }
    setOpeningLoop(true);
    setLoopMessage("Minting the Goal revision…");
    try {
      // Mint order is the canonical dependency order: Goal revision first
      // (#458), then the CreativeBrief projected onto that exact revision
      // (#774), then one canonical Run carrying the pack binding and the
      // exploration params (#793/#984). Width/policy ride on the Run — they
      // are never part of the Goal payload, so tuning exploration can never
      // rewrite Goal identity.
      // frontend-api-routes: allow /v1/goals is the #458 Goal revisions surface; not mounted at this base — the probe above has already proven it ready before this call runs (#988/#286).
      const goal = await apiPost<GoalRecord>("/v1/goals", {
        title: goalTitle.trim(),
        desired_outcome: desiredOutcome.trim(),
        stop_conditions: stopConditions.trim(),
      });
      setLoopMessage("Minting the CreativeBrief revision…");
      // frontend-api-routes: allow /v1/creative-briefs is the #774 CreativeBrief revision surface; not mounted at this base — the probe above has already proven it ready before this call runs (#988/#286).
      const brief = await apiPost<BriefRecord>("/v1/creative-briefs", {
        goal_id: goal.goal_id,
        goal_revision: goal.goal_revision,
        audience: briefAudience.trim(),
        constraints: briefConstraints.trim(),
        guidance: briefGuidance.trim(),
      });
      setLoopMessage("Starting the loop Run…");
      // frontend-api-routes: allow /v1/runs is the canonical Run mint (loop Graph/Run per ADR-092926-7a01); not mounted at this base — the probe above has already proven it ready before this call runs (#988/#286).
      const run = await apiPost<LoopRunRecord>("/v1/runs", {
        goal_id: goal.goal_id,
        goal_revision: goal.goal_revision,
        brief_id: brief.brief_id,
        brief_revision: brief.brief_revision,
        pack_id: selectedPackId,
        width,
        policy,
      });
      setOpenLoop({ goal, brief, run });
      setLoopMessage("Loop open. These ids are the canonical records; refresh restores them from the APIs.");
    } catch (err) {
      // A failed mint is reported as what it is. No partial loop is claimed:
      // whatever minted stays queryable server-side; the surface shows the
      // actual failure instead of a fabricated open loop.
      setLoopMessage(err instanceof ApiError ? `Opening the loop failed: ${err.message} (HTTP ${err.status} from ${err.path})` : `Opening the loop failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setOpeningLoop(false);
    }
  }

  const persistArtifactMarkup = useCallback((fixedMode: FixedPageMode, markup: string, trustRecommendation: VisualArtifactTrustRecommendation) => {
    const safeMarkup = sanitizeVisualArtifactMarkup(markup);
    const artifact: PersistedFixedPageArtifact = { markup: safeMarkup, trustRecommendation };
    setArtifactMarkup((current) => ({ ...current, [fixedMode]: artifact }));
    try {
      const stored: unknown = JSON.parse(window.localStorage.getItem(FIXED_PAGE_STORAGE_KEY) ?? "{}");
      window.localStorage.setItem(
        FIXED_PAGE_STORAGE_KEY,
        JSON.stringify({ ...(typeof stored === "object" && stored !== null ? stored : {}), [fixedMode]: artifact }),
      );
    } catch {
      // Browser storage can be unavailable; the in-memory editor remains usable.
    }
  }, []);

  function selectMode(id: ArtifactModeId): void {
    selectedModeRef.current = id;
    setSelectedMode(id);
    const next = catalog.skills.find((candidate) => id === "deck" ? candidate.mode === "deck" : candidate.render_slot === "renderer.fixed-page") ?? catalog.skills[0];
    if (next) {
      setSelectedSkillSlug(next.slug);
      setResponses(Object.fromEntries((next.discovery_form ?? []).map((field) => [field.key, fieldValue(field)])));
    }
    setEditor(null);
    setStatus(`${ARTIFACT_MODES.find((candidate) => candidate.id === id)?.name ?? id} selected.`);
  }

  function selectSkill(slug: string): void {
    const next = catalog.skills.find((candidate) => candidate.slug === slug);
    setSelectedSkillSlug(slug);
    setResponses(Object.fromEntries((next?.discovery_form ?? []).map((field) => [field.key, fieldValue(field)])));
  }

  async function saveProject(): Promise<void> {
    if (!canSaveProject || !skill) throw new Error("Choose a design skill and system before saving.");
    await apiPost("/v1/design/projects", {
      skill_slug: skill.slug,
      responses: { ...responses, brief: prompt },
      design_system_slug: systemSlug,
      trust_tier: "t3",
    });
  }

  function openEditor(): void {
    if (!canOpenEditor) {
      setStatus("Enter a brief before opening the editor.");
      return;
    }
    setEditor(selectedMode === "deck" ? "deck" : "fixed");
    setStatus(`${mode.name} editor opened. This is an unsaved local draft until a project is saved.`);
  }

  if (editor === "deck") return <DeckBuilder initialPrompt={prompt} onSave={canSaveProject ? saveProject : undefined} onExit={() => { setEditor(null); setStatus("Returned to the Design Studio brief."); }} />;
  if (editor === "fixed") return <FixedPageEditor artifactName={mode.name} initialPrompt={prompt} onSave={canSaveProject ? saveProject : undefined} onExit={() => { setEditor(null); setStatus("Returned to the Design Studio brief."); }} />;

  return (
    <div aria-label="Design Studio">
      <PageHeader title="Design Studio" subtitle="Create presentations, posters, infographics, and other visual artifacts" />
      {/* Focus anchor for editor transitions. The visible page heading comes
          from PageHeader, so this textless target avoids rendering a second
          h1 while still giving keyboard users a deterministic focus
          destination when an editor opens or closes. */}
      <div ref={headingRef} tabIndex={-1} style={{ position: "absolute", width: 1, height: 1, overflow: "hidden" }} />

      {/* M7-A12 (#988): the loop start is the FIRST committed choice — pack,
          Goal revision, CreativeBrief revision, exploration params — and it
          mints canonical objects only. There is no DesignRun, no intake phase
          enum, and no client-side system of record: every id shown here came
          from an API. The visual-mode picker below stays as the
          execute-backend choice for a loop that already exists. */}
      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="loop-start-title">
        <h2 id="loop-start-title" style={{ fontFamily: "var(--hand)", fontSize: 16, margin: "0 0 4px" }}>Open a design loop</h2>
        <p style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "0 0 12px" }}>A loop starts from canonical objects: one domain pack, one Goal revision, one CreativeBrief on that revision, one Run carrying the pack binding and exploration params. Visual artifact modes are chosen after the loop exists, as the execute backend.</p>

        <div role="list" aria-label="Loop surface availability" style={{ display: "grid", gap: 6, marginBottom: 12 }}>
          {(Object.keys(LOOP_SURFACE_LABELS) as (keyof LoopSurfaces)[]).map((key) => (
            <div key={key} role="listitem" style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", borderBottom: "1px solid var(--rule)", paddingBottom: 4 }}>
              <span style={{ fontFamily: "var(--hand)", fontSize: 12 }}>{LOOP_SURFACE_LABELS[key]}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, textTransform: "uppercase", color: loopSurfaces[key].status === "ready" ? "var(--accent)" : "var(--pencil)" }}>{loopSurfaces[key].status}</span>
              {loopSurfaces[key].cause && <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", width: "100%" }}>{loopSurfaces[key].cause}</span>}
            </div>
          ))}
        </div>

        <div role="group" aria-label="Domain pack" aria-describedby="loop-pack-help" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, marginBottom: 12 }}>
          {packs.map((pack) => {
            const selected = pack.pack_id === selectedPackId;
            return <button key={pack.pack_id} type="button" aria-pressed={selected} disabled={openingLoop} onClick={() => { setSelectedPackId(pack.pack_id); setLoopMessage(`Pack ${pack.name} selected.`); }} className="card" style={{ cursor: "pointer", textAlign: "left", border: selected ? "2px solid var(--accent)" : "1.3px solid var(--rule)", background: selected ? "var(--paper)" : undefined, padding: 12 }}>
              <span style={{ fontFamily: "var(--hand)", fontSize: 14, fontWeight: 600 }}>{pack.name}</span>
              <span style={{ display: "block", fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 4 }}>{pack.summary}</span>
            </button>;
          })}
        </div>
        <p id="loop-pack-help" style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", margin: "-6px 0 12px" }}>{loopSurfaces.packs.status === "ready" ? "A pack is a bundle of defaults for the one loop — never a product or a route." : "Pack listing unavailable; the pack choice stays disabled with its cause."}</p>

        <label htmlFor="loop-goal-title" style={{ display: "block", fontSize: 12, marginBottom: 4 }}>Goal title</label>
        <input id="loop-goal-title" value={goalTitle} disabled={(missingSurfaces.length > 0 && loopSurfaces.goals.status !== "ready") || openingLoop || Boolean(openLoop)} onChange={(event) => setGoalTitle(event.target.value)} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginBottom: 8 }} />
        <label htmlFor="loop-goal-outcome" style={{ display: "block", fontSize: 12, marginBottom: 4 }}>Desired outcome</label>
        <textarea id="loop-goal-outcome" value={desiredOutcome} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => setDesiredOutcome(event.target.value)} rows={2} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginBottom: 8, resize: "vertical" }} />
        <label htmlFor="loop-goal-stop" style={{ display: "block", fontSize: 12, marginBottom: 4 }}>Stop conditions</label>
        <textarea id="loop-goal-stop" value={stopConditions} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => setStopConditions(event.target.value)} rows={2} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginBottom: 12, resize: "vertical" }} />

        <p style={{ fontFamily: "var(--hand)", fontSize: 13, margin: "0 0 8px" }}>CreativeBrief</p>
        <label htmlFor="loop-brief-audience" style={{ display: "block", fontSize: 12, marginBottom: 4 }}>Audience</label>
        <input id="loop-brief-audience" value={briefAudience} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => setBriefAudience(event.target.value)} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginBottom: 8 }} />
        <label htmlFor="loop-brief-constraints" style={{ display: "block", fontSize: 12, marginBottom: 4 }}>Constraints</label>
        <textarea id="loop-brief-constraints" value={briefConstraints} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => setBriefConstraints(event.target.value)} rows={2} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginBottom: 8, resize: "vertical" }} />
        <label htmlFor="loop-brief-guidance" style={{ display: "block", fontSize: 12, marginBottom: 4 }}>Creative guidance</label>
        <textarea id="loop-brief-guidance" value={briefGuidance} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => setBriefGuidance(event.target.value)} rows={2} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginBottom: 12, resize: "vertical" }} />

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
          <label htmlFor="loop-width" style={{ fontSize: 12 }}>Exploration width
            <input id="loop-width" type="number" min={WIDTH_MIN} max={WIDTH_MAX} value={width} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => { const parsed = Number.parseInt(event.target.value, 10); if (Number.isNaN(parsed)) { setWidth(DEFAULT_WIDTH); return; } setWidth(Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, parsed))); }} style={{ display: "block", width: 90, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginTop: 4 }} />
          </label>
          <label htmlFor="loop-policy" style={{ fontSize: 12 }}>Exploration policy
            <select id="loop-policy" value={policy} disabled={openingLoop || Boolean(openLoop)} onChange={(event) => setPolicy(event.target.value as ExplorationPolicy)} style={{ display: "block", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 13, marginTop: 4 }}>
              {EXPLORATION_POLICIES.map((candidate) => <option key={candidate} value={candidate}>{candidate}</option>)}
            </select>
          </label>
        </div>
        <p style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", margin: "0 0 12px" }}>Width and policy are Run exploration params (#984) — changing them is not a Goal revision. The pack's Rubric catalog is instantiated onto the Goal (#791) and stays unlocked until the first fence lock.</p>

        {openLoop && (
          <div role="list" aria-label="Open loop records" style={{ display: "grid", gap: 6, marginBottom: 12 }}>
            <div role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "8px 10px", fontFamily: "var(--mono)", fontSize: 10 }}>
              Goal {openLoop.goal.goal_id} · revision {openLoop.goal.goal_revision} · {openLoop.goal.title}
            </div>
            <div role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "8px 10px", fontFamily: "var(--mono)", fontSize: 10 }}>
              CreativeBrief {openLoop.brief.brief_id} · revision {openLoop.brief.brief_revision}
            </div>
            <div role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "8px 10px", fontFamily: "var(--mono)", fontSize: 10 }} data-loop-run-record>
              Run {openLoop.run.run_id} · pack {openLoop.run.pack_id} · width {openLoop.run.width} · policy {openLoop.run.policy}
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn-primary" disabled={!canOpenLoop} onClick={openDesignLoop} aria-describedby="loop-start-state" style={{ padding: "9px 16px", borderRadius: 8 }}>{openingLoop ? "Opening the loop…" : "Open the loop"}</button>
          <span id="loop-start-state" role="status" aria-live="polite" style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)" }}>{loopDisabledCause ? `${loopDisabledCause} — ${loopMessage}` : loopMessage}</span>
        </div>
      </section>

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="artifact-types-title">
        <h2 id="artifact-types-title" style={{ fontFamily: "var(--hand)", fontSize: 16, margin: "0 0 4px" }}>What are you making?</h2>
        <p style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "0 0 12px" }}>Every format shares one project, brand, asset, and editing workspace. Presentations add deck-specific page and presentation tools. This picker is the execute-backend choice inside a loop that already exists — it is not how a loop starts, and no Goal is required to browse it.</p>
        <div role="group" aria-label="Design artifact types" aria-describedby="design-artifact-types-help" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          {ARTIFACT_MODES.map((artifact) => {
            const selected = artifact.id === selectedMode;
            return <button key={artifact.id} type="button" aria-pressed={selected} onClick={() => selectMode(artifact.id)} className="card" style={{ cursor: "pointer", textAlign: "left", border: selected ? "2px solid var(--accent)" : "1.3px solid var(--rule)", background: selected ? "var(--paper)" : undefined, padding: 12 }}>
              <span style={{ fontFamily: "var(--hand)", fontSize: 14, fontWeight: 600 }}>{artifact.name}</span>
              <span style={{ display: "block", fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 4 }}>{artifact.description}</span>
            </button>;

          })}
        </div>
        <p id="design-artifact-types-help" style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", margin: "10px 0 0" }}>Keyboard: Tab moves between artifact types; Enter or Space selects one. The selected type is announced as pressed.</p>
      </section>

      <section className="card" style={{ marginBottom: 16, borderColor: catalog.status === "ready" ? "var(--ok, #5a9a4a)" : "var(--rule)" }} aria-live="polite" aria-labelledby="design-resources-title">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}><h2 id="design-resources-title" style={{ fontFamily: "var(--hand)", fontSize: 15, margin: 0 }}>Design resources</h2><span style={{ fontFamily: "var(--mono)", fontSize: 9, textTransform: "uppercase" }}>{catalog.status}</span></div>
        <p style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "6px 0 0" }}>{catalog.message}</p>
        {catalog.skills.length > 0 && <label style={{ display: "block", marginTop: 10, fontSize: 12 }}>Design skill
          <select value={selectedSkillSlug} onChange={(event) => selectSkill(event.target.value)} aria-describedby="design-skill-help">
            {catalog.skills.map((candidate) => <option key={candidate.slug} value={candidate.slug}>{candidate.name}</option>)}
          </select>
        </label>}
        {catalog.skills.length > 0 && <div aria-label="Available design skills" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>{catalog.skills.map((candidate) => <span key={candidate.slug} style={{ fontSize: 11, color: "var(--pencil)" }}>{candidate.name}</span>)}</div>}
        {catalog.systems.length > 0 && <label style={{ display: "block", marginTop: 8, fontSize: 12 }}>Design system
          <select value={systemSlug} onChange={(event) => setSelectedSystemSlug(event.target.value)}><option value="">Choose a design system</option>{catalog.systems.map((system) => <option key={system.slug} value={system.slug}>{system.name}</option>)}</select>
        </label>}
        {skill && <p id="design-skill-help" style={{ color: "var(--pencil)", fontSize: 11, marginBottom: 0 }}>{skill.description}</p>}
      </section>

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="persisted-projects-title">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}><h2 id="persisted-projects-title" style={{ fontFamily: "var(--hand)", fontSize: 15, margin: 0 }}>Persisted Design projects</h2><span style={{ fontFamily: "var(--mono)", fontSize: 9, textTransform: "uppercase" }}>{projectState.status}</span></div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 6 }}>
          {projectState.message} These are read-only facts from the Design service; they do not claim that visual generation occurred.
        </div>
        {projectState.projects.length > 0 && (
          <div role="list" style={{ display: "grid", gap: 8, marginTop: 10 }} aria-label="Persisted Design projects">
            {projectState.projects.map((project) => (
              <div key={project.id} role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "9px 10px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600 }}>{project.name}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 8, textTransform: "uppercase", color: "var(--accent)" }}>
                    {project.output_count} stored output{project.output_count === 1 ? "" : "s"}
                  </span>
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 3 }}>
                  {project.skill_slug} · {project.design_system_slug}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="artifact-brief-title">
        <h2 id="artifact-brief-title" style={{ fontFamily: "var(--hand)", fontSize: 16, margin: "0 0 4px" }}>{mode.name}</h2>
        <p style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "0 0 12px" }}>{mode.description}</p>
        {skill?.discovery_form?.map((field) => <label key={field.key} style={{ display: "block", marginBottom: 10, fontSize: 12 }}>{field.label}{field.required === false ? " (optional)" : ""}
          {field.field_type === "select" ? <select value={responses[field.key] ?? ""} onChange={(event) => setResponses((current) => ({ ...current, [field.key]: event.target.value }))}>{field.options?.map((option) => <option key={option} value={option}>{option}</option>)}</select> : field.field_type === "color" ? <input type="color" value={responses[field.key] || "#6366f1"} onChange={(event) => setResponses((current) => ({ ...current, [field.key]: event.target.value }))} /> : <input value={responses[field.key] ?? ""} onChange={(event) => setResponses((current) => ({ ...current, [field.key]: event.target.value }))} />}
          <span style={{ display: "block", color: "var(--pencil)", fontSize: 11 }}>{field.description}</span>
        </label>)}
        <label htmlFor="design-prompt" style={{ fontFamily: "var(--hand)", fontSize: 13, display: "block", marginBottom: 6 }}>Describe the artifact</label>
        <p id="design-prompt-help" style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", margin: "0 0 6px" }}>Enter a brief, then open the keyboard-complete editor. The draft stays local until a durable project save is connected.</p>
        <textarea id="design-prompt" aria-describedby="design-prompt-help" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={`Describe the ${mode.name.toLowerCase()} you want to create…`} rows={4} style={{ width: "100%", boxSizing: "border-box", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 14, resize: "vertical" }} />
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
          <button type="button" className="btn-primary" disabled={!canOpenEditor} onClick={openEditor} aria-describedby="design-execution-state" style={{ padding: "9px 16px", borderRadius: 8 }}>{selectedMode === "deck" ? "Open Deck editor" : "Open editor"}</button>
          <span id="design-execution-state" role="status" aria-live="polite" style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)" }}>{status}</span>

        </div>
      </section>

      {/* #768: the selected fixed-page artifact is previewed and edited only
          through the shared visual boundary. Markup loaded from storage or
          pasted/dropped by the user is sanitized here, and the pre-scan
          verdict travels with the artifact so blocked content is never
          recommended for a trust upgrade. */}
      {selectedMode !== "deck" && (
        <section className="card" style={{ marginBottom: 16 }} aria-label={`${mode.name} visual artifact`}>
          <FixedPageArtifactEditor
            key={selectedMode}
            mode={selectedMode}
            initialMarkup={artifactMarkup[selectedMode]?.markup}
            initialTrustRecommendation={artifactMarkup[selectedMode]?.trustRecommendation}
            onMarkupChange={(markup, trustRecommendation) => persistArtifactMarkup(selectedMode, markup, trustRecommendation)}
          />
        </section>
      )}

      <section className="card" aria-labelledby="availability-title"><h2 id="availability-title" style={{ fontFamily: "var(--hand)", fontSize: 15, margin: "0 0 10px" }}>Availability</h2><div role="list" aria-label="Design Studio availability" style={{ display: "grid", gap: 8 }}>
        {[{ label: "Loop start (Goal + CreativeBrief + pack + Run)", state: missingSurfaces.length === 0 ? "available" : loopSurfaces.packs.status === "probing" || loopSurfaces.goals.status === "probing" ? "checking" : "unavailable", detail: "Opening a loop mints a Goal revision, a CreativeBrief revision, a pack binding, and one canonical Run; missing surfaces leave it disabled with their cause." }, { label: "Design resource discovery", state: catalog.status === "ready" ? "available" : catalog.status, detail: "Skills and design systems are discovered from the connected Design service." }, { label: "Editing + preview", state: "available", detail: "Fixed-page and Deck editors expose selection, property controls, keyboard movement, and visible status." }, { label: "Presentation + export", state: "available", detail: "Deck presentation, ordered-page navigation, and HTML/print export are keyboard-operable." }].map((step) => <div key={step.label} role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "9px 10px" }}><div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}><span style={{ fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600 }}>{step.label}</span><span style={{ fontFamily: "var(--mono)", fontSize: 8, textTransform: "uppercase", color: "var(--accent)" }}>{step.state}</span></div><div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 3 }}>{step.detail}</div></div>)}
      </div></section>
    </div>

  );
}
