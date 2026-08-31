import { useEffect, useState } from "react";
import { PageHeader } from "../components/shared";
import { apiGet } from "../lib/api";

type ArtifactModeId =
  | "deck"
  | "poster"
  | "infographic"
  | "flyer"
  | "social"
  | "card"
  | "cover"
  | "diagram"
  | "custom";

type ArtifactMode = {
  id: ArtifactModeId;
  name: string;
  description: string;
  renderer: "renderer.deck" | "renderer.fixed-page";
  note?: string;
};

type DesignSkill = {
  slug: string;
  name: string;
  mode: string;
  description: string;
  render_slot: string | null;
};

type DesignSystemsResponse = {
  systems: Array<{ slug: string; name: string }>;
  ready: boolean;
  cause: string | null;
};

type CatalogState = {
  status: "loading" | "ready" | "unavailable";
  skills: DesignSkill[];
  systemCount: number;
  message: string;
};

const ARTIFACT_MODES: ArtifactMode[] = [
  {
    id: "deck",
    name: "Presentation / Deck",
    description: "Multi-page presentations with slide navigation, presentation mode, and deck export.",
    renderer: "renderer.deck",
    note: "Deck editing remains security-contained until #752 lands.",
  },
  {
    id: "poster",
    name: "Poster",
    description: "Single fixed-page visual for print, signage, or display.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "infographic",
    name: "Infographic",
    description: "Structured visual explanation combining data, text, and graphics.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "flyer",
    name: "Flyer",
    description: "Compact promotional or informational one-page layout.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "social",
    name: "Social graphic",
    description: "Fixed-size visual content for social channels and campaigns.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "card",
    name: "Card",
    description: "Small-format announcement, invitation, or branded card.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "cover",
    name: "Cover",
    description: "Cover art and title-page compositions for documents or media.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "diagram",
    name: "Diagram / visual",
    description: "Explanatory diagrams, process visuals, and composed illustrations.",
    renderer: "renderer.fixed-page",
  },
  {
    id: "custom",
    name: "Custom canvas",
    description: "A custom fixed-size composition using the shared Design/Canvas foundation.",
    renderer: "renderer.fixed-page",
  },
];

function failureMessage(result: PromiseSettledResult<unknown>): string | null {
  if (result.status !== "rejected") return null;
  return result.reason instanceof Error ? result.reason.message : String(result.reason);
}

export default function DesignStudio() {
  const [selectedMode, setSelectedMode] = useState<ArtifactModeId>("poster");
  const [prompt, setPrompt] = useState("");
  const [catalog, setCatalog] = useState<CatalogState>({
    status: "loading",
    skills: [],
    systemCount: 0,
    message: "Checking the real Design service…",
  });

  useEffect(() => {
    let cancelled = false;

    async function loadCatalog() {
      const [skillsResult, systemsResult] = await Promise.allSettled([
        apiGet<DesignSkill[]>("/v1/design/skills"),
        apiGet<DesignSystemsResponse>("/v1/design/systems"),
      ]);
      if (cancelled) return;

      const skills = skillsResult.status === "fulfilled" ? skillsResult.value : [];
      const systems = systemsResult.status === "fulfilled" ? systemsResult.value.systems : [];
      const failures = [failureMessage(skillsResult), failureMessage(systemsResult)].filter(
        (message): message is string => message !== null,
      );

      if (failures.length > 0) {
        setCatalog({
          status: "unavailable",
          skills,
          systemCount: systems.length,
          message: `Design foundation is degraded: ${failures.join("; ")}`,
        });
        return;
      }

      setCatalog({
        status: "ready",
        skills,
        systemCount: systems.length,
        message: `${skills.length} design skill${skills.length === 1 ? "" : "s"} and ${systems.length} design system${systems.length === 1 ? "" : "s"} available.`,
      });
    }

    void loadCatalog();
    return () => {
      cancelled = true;
    };
  }, []);

  const mode = ARTIFACT_MODES.find((candidate) => candidate.id === selectedMode) ?? ARTIFACT_MODES[0];
  const catalogBorder = catalog.status === "ready" ? "var(--ok, #5a9a4a)" : catalog.status === "unavailable" ? "var(--danger, #c4452a)" : "var(--rule)";

  return (
    <div>
      <PageHeader
        title="Design Studio"
        subtitle="Create visual artifacts from one shared Design/Canvas foundation"
      />

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
          What are you making?
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginBottom: 12 }}>
          Decks are a specialized Design Studio mode; fixed-page artifacts share the same project, rendering, security, and provenance foundation.
        </div>
        <div
          role="group"
          aria-label="Design artifact types"
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}
        >
          {ARTIFACT_MODES.map((artifact) => {
            const selected = artifact.id === selectedMode;
            return (
              <button
                key={artifact.id}
                type="button"
                aria-pressed={selected}
                onClick={() => setSelectedMode(artifact.id)}
                className="card"
                style={{
                  cursor: "pointer",
                  textAlign: "left",
                  border: selected ? "2px solid var(--accent)" : "1.3px solid var(--rule)",
                  background: selected ? "var(--paper)" : undefined,
                  padding: 12,
                }}
              >
                <div style={{ fontFamily: "var(--hand)", fontSize: 14, fontWeight: 600 }}>{artifact.name}</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 4 }}>
                  {artifact.description}
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--accent)", marginTop: 8 }}>
                  {artifact.renderer}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16, borderColor: catalogBorder }} aria-live="polite">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
          <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>Design foundation</div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, textTransform: "uppercase" }}>
            {catalog.status}
          </div>
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 6 }}>
          {catalog.message}
        </div>
        {catalog.status === "ready" && catalog.skills.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }} aria-label="Available design skills">
            {catalog.skills.slice(0, 8).map((skill) => (
              <span key={skill.slug} className="btn" style={{ fontSize: 9, padding: "2px 7px", cursor: "default" }}>
                {skill.name}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
          {mode.name}
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginBottom: 12 }}>
          {mode.description}
        </div>
        {mode.note && (
          <div role="status" style={{ fontFamily: "var(--mono)", fontSize: 9, marginBottom: 10 }}>
            {mode.note}
          </div>
        )}
        <label htmlFor="design-prompt" style={{ fontFamily: "var(--hand)", fontSize: 13, display: "block", marginBottom: 6 }}>
          Describe the artifact
        </label>
        <textarea
          id="design-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder={`Describe the ${mode.name.toLowerCase()} you want to create…`}
          rows={4}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "10px 12px",
            borderRadius: 8,
            border: "1px solid var(--rule)",
            fontFamily: "var(--hand)",
            fontSize: 14,
            resize: "vertical",
          }}
        />
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
          <button
            type="button"
            className="btn-primary"
            disabled
            aria-describedby="design-execution-state"
            style={{ padding: "9px 16px", borderRadius: 8, cursor: "not-allowed", opacity: 0.55 }}
          >
            {selectedMode === "deck" ? "Open Deck editor" : "Generate visual"}
          </button>
          <span id="design-execution-state" style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)" }}>
            Canonical visual execution is not mounted in Conductor yet. Design Studio will not simulate completion while #735 is landing.
          </span>
        </div>
      </div>

      <div className="card">
        <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
          Execution contract
        </div>
        <div style={{ display: "grid", gap: 8 }} role="list" aria-label="Design Studio execution contract">
          {[
            {
              label: "Brief + design system",
              state: catalog.status === "ready" ? "available" : catalog.status,
              detail: "Backed by the real /v1/design skills, systems, discovery, and DesignProject APIs.",
            },
            {
              label: "Visual generation",
              state: "dependency",
              detail: "Will consume the canonical Canvas Run/NodeRun/Attempt seam from #735; no local lifecycle is allowed.",
            },
            {
              label: "Edit + preview",
              state: selectedMode === "deck" ? "security-contained" : "product integration",
              detail: selectedMode === "deck"
                ? "Deck is a Design Studio mode, but its editor remains contained until #752 closes the browser-rendering boundary."
                : "The selected fixed-page mode will use shared Design/Canvas artifact and rendering state.",
            },
            {
              label: "Publish + export",
              state: "M3",
              detail: "PDF/SVG/PNG and product API cutover remain owned by #94/#95 after canonical execution lands.",
            },
          ].map((step) => (
            <div key={step.label} role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "9px 10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600 }}>{step.label}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 8, textTransform: "uppercase", color: "var(--accent)" }}>
                  {step.state}
                </span>
              </div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 11, color: "var(--pencil)", marginTop: 3 }}>
                {step.detail}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
