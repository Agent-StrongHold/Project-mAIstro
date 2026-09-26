import { useEffect, useRef, useState } from "react";
import { PageHeader } from "../components/shared";
import { apiGet, apiPost } from "../lib/api";
import DeckBuilder from "./DeckBuilder";
import FixedPageEditor from "./FixedPageEditor";

type ArtifactModeId = "deck" | "poster" | "infographic" | "flyer" | "social" | "card" | "cover" | "diagram" | "custom";
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

export default function DesignStudio() {
  const headingRef = useRef<HTMLDivElement>(null);
  const [selectedMode, setSelectedMode] = useState<ArtifactModeId>("poster");
  const selectedModeRef = useRef<ArtifactModeId>("poster");
  const [prompt, setPrompt] = useState("");
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

  const mode = ARTIFACT_MODES.find((candidate) => candidate.id === selectedMode) ?? ARTIFACT_MODES[0];
  const skill = catalog.skills.find((candidate) => candidate.slug === selectedSkillSlug);
  const systemSlug = catalog.systems.some((system) => system.slug === selectedSystemSlug) ? selectedSystemSlug : (catalog.systems[0]?.slug ?? selectedSystemSlug);
  const canOpenEditor = prompt.trim().length > 0;
  const canSaveProject = canOpenEditor && Boolean(skill && systemSlug);

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

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="artifact-types-title">
        <h2 id="artifact-types-title" style={{ fontFamily: "var(--hand)", fontSize: 16, margin: "0 0 4px" }}>What are you making?</h2>
        <p style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "0 0 12px" }}>Every format shares one project, brand, asset, and editing workspace. Presentations add deck-specific page and presentation tools.</p>
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

      <section className="card" aria-labelledby="availability-title"><h2 id="availability-title" style={{ fontFamily: "var(--hand)", fontSize: 15, margin: "0 0 10px" }}>Availability</h2><div role="list" aria-label="Design Studio availability" style={{ display: "grid", gap: 8 }}>
        {[{ label: "Design resource discovery", state: catalog.status === "ready" ? "available" : catalog.status, detail: "Skills and design systems are discovered from the connected Design service." }, { label: "Editing + preview", state: "available", detail: "Fixed-page and Deck editors expose selection, property controls, keyboard movement, and visible status." }, { label: "Presentation + export", state: selectedMode === "deck" ? "available" : "available", detail: "Deck presentation, ordered-page navigation, and HTML/print export are keyboard-operable." }].map((step) => <div key={step.label} role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "9px 10px" }}><div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}><span style={{ fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600 }}>{step.label}</span><span style={{ fontFamily: "var(--mono)", fontSize: 8, textTransform: "uppercase", color: "var(--accent)" }}>{step.state}</span></div><div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 3 }}>{step.detail}</div></div>)}
      </div></section>
    </div>

  );
}
