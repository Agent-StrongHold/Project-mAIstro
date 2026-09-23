import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "../components/shared";
import { apiGet } from "../lib/api";
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

type ArtifactMode = {
  id: ArtifactModeId;
  name: string;
  description: string;
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
  catalog: {
    available: boolean;
    cause: string | null;
    count: number;
  };
  ready: boolean;
  cause: string | null;
};

type CatalogState = {
  status: "loading" | "ready" | "degraded" | "unavailable";
  skills: DesignSkill[];
  systemCount: number;
  message: string;
};

const ARTIFACT_MODES: ArtifactMode[] = [
  {
    id: "deck",
    name: "Presentation / Deck",
    description: "Multi-page presentations with slide navigation, presentation mode, and deck export.",
    note: "Deck editing is temporarily unavailable while secure rendering is enabled.",
  },
  {
    id: "poster",
    name: "Poster",
    description: "Single fixed-page visual for print, signage, or display.",
  },
  {
    id: "infographic",
    name: "Infographic",
    description: "Structured visual explanation combining data, text, and graphics.",
  },
  {
    id: "flyer",
    name: "Flyer",
    description: "Compact promotional or informational one-page layout.",
  },
  {
    id: "social",
    name: "Social graphic",
    description: "Fixed-size visual content for social channels and campaigns.",
  },
  {
    id: "card",
    name: "Card",
    description: "Small-format announcement, invitation, or branded card.",
  },
  {
    id: "cover",
    name: "Cover",
    description: "Cover art and title-page compositions for documents or media.",
  },
  {
    id: "diagram",
    name: "Diagram / visual",
    description: "Explanatory diagrams, process visuals, and composed illustrations.",
  },
  {
    id: "custom",
    name: "Custom canvas",
    description: "A custom fixed-size composition using the shared Design Studio workspace.",
  },
];

function failureMessage(result: PromiseSettledResult<unknown>): string | null {
  if (result.status !== "rejected") return null;
  return result.reason instanceof Error ? result.reason.message : String(result.reason);
}

function resourceSummary(skillCount: number, systemCount: number): string {
  return `${skillCount} design skill${skillCount === 1 ? "" : "s"} and ${systemCount} design system${systemCount === 1 ? "" : "s"} available.`;
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
  const [selectedMode, setSelectedMode] = useState<ArtifactModeId>("poster");
  const [prompt, setPrompt] = useState("");
  const [artifactMarkup, setArtifactMarkup] = useState<Partial<Record<FixedPageMode, PersistedFixedPageArtifact>>>(loadPersistedArtifacts);
  const [catalog, setCatalog] = useState<CatalogState>({
    status: "loading",
    skills: [],
    systemCount: 0,
    message: "Checking design resources…",
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
          message: `Some design resources are unavailable: ${failures.join("; ")}`,
        });
        return;
      }

      const optionalCatalog = systemsResult.status === "fulfilled" ? systemsResult.value.catalog : null;
      if (optionalCatalog && !optionalCatalog.available) {
        const cause = optionalCatalog.cause ?? "Additional design-system catalog is unavailable.";
        setCatalog({
          status: "degraded",
          skills,
          systemCount: systems.length,
          message: `${resourceSummary(skills.length, systems.length)} Additional design systems are unavailable: ${cause}`,
        });
        return;
      }

      setCatalog({
        status: "ready",
        skills,
        systemCount: systems.length,
        message: resourceSummary(skills.length, systems.length),
      });
    }

    void loadCatalog();
    return () => {
      cancelled = true;
    };
  }, []);

  const mode = ARTIFACT_MODES.find((candidate) => candidate.id === selectedMode) ?? ARTIFACT_MODES[0];
  const catalogBorder = catalog.status === "ready" ? "var(--ok, #5a9a4a)" : catalog.status === "loading" ? "var(--rule)" : "var(--danger, #c4452a)";
  const persistArtifactMarkup = useCallback((fixedMode: FixedPageMode, markup: string, trustRecommendation: VisualArtifactTrustRecommendation) => {
    const safeMarkup = sanitizeVisualArtifactMarkup(markup);
    const artifact: PersistedFixedPageArtifact = { markup: safeMarkup, trustRecommendation };
    setArtifactMarkup((current) => ({ ...current, [fixedMode]: artifact }));
    try {
      const stored = JSON.parse(window.localStorage.getItem(FIXED_PAGE_STORAGE_KEY) ?? "{}");
      window.localStorage.setItem(FIXED_PAGE_STORAGE_KEY, JSON.stringify({ ...stored, [fixedMode]: artifact }));
    } catch {
      // Browser storage can be unavailable; the in-memory editor remains usable.
    }
  }, []);

  return (
    <div>
      <PageHeader
        title="Design Studio"
        subtitle="Create presentations, posters, infographics, and other visual artifacts"
      />

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
          What are you making?
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginBottom: 12 }}>
          Every format shares one project, brand, asset, and editing workspace. Presentations add deck-specific page and presentation tools.
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
                <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 4 }}>
                  {artifact.description}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16, borderColor: catalogBorder }} aria-live="polite">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
          <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600 }}>Design resources</div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 12, textTransform: "uppercase" }}>
            {catalog.status}
          </div>
        </div>
        <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 6 }}>
          {catalog.message}
        </div>
        {catalog.skills.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }} aria-label="Available design skills">
            {catalog.skills.map((skill) => (
              <span key={skill.slug} className="btn" style={{ fontSize: 12, padding: "2px 7px", cursor: "default" }}>
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
          <div role="status" style={{ fontFamily: "var(--mono)", fontSize: 12, marginBottom: 10 }}>
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
        {selectedMode !== "deck" && (
          <div style={{ marginTop: 16 }}>
            <FixedPageArtifactEditor
              key={selectedMode}
              mode={selectedMode}
              initialMarkup={artifactMarkup[selectedMode]?.markup}
              initialTrustRecommendation={artifactMarkup[selectedMode]?.trustRecommendation}
              onMarkupChange={(markup, trustRecommendation) => persistArtifactMarkup(selectedMode, markup, trustRecommendation)}
            />
          </div>
        )}
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
          <span id="design-execution-state" style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)" }}>
            Visual generation is not available yet. Nothing is submitted or simulated while this control is disabled.
          </span>
        </div>
      </div>

      <div className="card">
        <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
          Availability
        </div>
        <div style={{ display: "grid", gap: 8 }} role="list" aria-label="Design Studio availability">
          {[
            {
              label: "Design resource discovery",
              state: catalog.status === "ready" ? "available" : catalog.status,
              detail: "Available design skills and design systems are discovered from the connected Design service. Brief creation is not connected yet.",
            },
            {
              label: "Visual generation",
              state: "not yet available",
              detail: "Generation stays disabled until durable execution is connected. The Studio never substitutes a local animation or placeholder result.",
            },
            {
              label: "Edit + preview",
              state: selectedMode === "deck" ? "temporarily unavailable" : "available",
              detail: selectedMode === "deck"
                ? "Deck editing stays closed until its secure rendering path is enabled."
                : "Loaded and edited fixed-page content is sanitized before preview and retained in this browser.",
            },
            {
              label: "Publish + export",
              state: selectedMode === "deck" ? "temporarily unavailable" : "partially available",
              detail: selectedMode === "deck"
                ? "Deck export stays closed until its secure rendering path is enabled."
                : "HTML export is available for fixed pages; publishing to a shared project is not connected yet.",
            },
          ].map((step) => (
            <div key={step.label} role="listitem" style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "9px 10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600 }}>{step.label}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12, textTransform: "uppercase", color: "var(--accent)" }}>
                  {step.state}
                </span>
              </div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 3 }}>
                {step.detail}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
