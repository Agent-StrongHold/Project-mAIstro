// Workspace Home (#1048) — Mission-Control composition over canonical services.
//
// This page is a projection layer only: layout and pin state come from
// `/v1/workspaces/{id}/home/layout` (+ pin), compact sections from
// `/…/home/projections`. It does not own Goals, chat, backlog, runs, or
// adaptive authority. Selecting a compact item navigates to that resource's
// full surface via the projection's own `href` — the same resource id the
// backend returned.
//
// Adaptive Agent composition UI and quick-chat (#1822) are later slices;
// this shell proves default landing, durable layout read, pin round-trip,
// and honest empty/unavailable section states.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiPost } from "../lib/api";
import type {
  HomeLayout,
  HomeProjectionSection,
  HomeProjections,
  HomeRegion,
} from "../lib/home";
import { homeKindLabel, layoutPath, pinPath, projectionsPath } from "../lib/home";
import { useWorkspaces } from "../context/WorkspaceContext";
import { Card, EmptyState, Hex, LoadingSpinner, PageHeader, useToast } from "../components/shared";

function sectionFor(sections: HomeProjectionSection[], kind: string): HomeProjectionSection | null {
  return sections.find((s) => s.kind === kind) ?? null;
}

function RegionCard({
  region,
  section,
  pinBusy,
  onTogglePin,
  onOpen,
}: {
  region: HomeRegion;
  section: HomeProjectionSection | null;
  pinBusy: boolean;
  onTogglePin: (region: HomeRegion) => void;
  onOpen: (href: string) => void;
}) {
  const status = section?.status ?? "empty";
  const reason = section?.reason ?? null;
  const items = section?.items ?? [];

  return (
    <Card>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>{homeKindLabel(region.kind)}</h2>
          {region.pinned ? <Hex variant="accent">Pinned</Hex> : <Hex variant="muted">Adaptive</Hex>}
        </div>
        <button
          type="button"
          disabled={pinBusy}
          aria-pressed={region.pinned}
          aria-label={region.pinned ? `Unpin ${homeKindLabel(region.kind)}` : `Pin ${homeKindLabel(region.kind)}`}
          onClick={() => onTogglePin(region)}
          style={{ fontFamily: "var(--mono)", fontSize: 12 }}
        >
          {region.pinned ? "Unpin" : "Pin"}
        </button>
      </div>

      {status === "unavailable" && (
        <p style={{ margin: 0, color: "var(--pencil)", fontSize: 13 }} data-testid={`home-section-${region.kind}-unavailable`}>
          {reason || "This projection is not available."}
        </p>
      )}
      {status === "empty" && (
        <p style={{ margin: 0, color: "var(--pencil)", fontSize: 13 }} data-testid={`home-section-${region.kind}-empty`}>
          Nothing here yet.
        </p>
      )}
      {status === "ok" && items.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
          {items.map((item) => (
            <li key={`${item.resource_type}:${item.resource_id}`}>
              <button
                type="button"
                onClick={() => onOpen(item.href)}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "6px 8px",
                  border: "1px solid var(--line)",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                {item.title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Home() {
  const { activeWorkspaceId, ready: workspacesReady } = useWorkspaces();
  const toast = useToast();
  const navigate = useNavigate();
  const [layout, setLayout] = useState<HomeLayout | null>(null);
  const [projections, setProjections] = useState<HomeProjections | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pinBusyId, setPinBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!activeWorkspaceId) {
      setLayout(null);
      setProjections(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [nextLayout, nextProjections] = await Promise.all([
        apiGet<HomeLayout>(layoutPath(activeWorkspaceId)),
        apiGet<HomeProjections>(projectionsPath(activeWorkspaceId)),
      ]);
      setLayout(nextLayout);
      setProjections(nextProjections);
      setError(null);
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Couldn't load Workspace Home.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    // Defer the first fetch to a timer tick (same pattern as Goals.tsx): a
    // synchronous load in the effect body cascades a render on mount.
    if (!workspacesReady) return;
    const first = setTimeout(() => void load(), 0);
    return () => clearTimeout(first);
  }, [load, workspacesReady]);

  const regions = useMemo(() => {
    const list = layout?.regions ?? [];
    return [...list].sort((a, b) => a.position - b.position || a.id.localeCompare(b.id));
  }, [layout]);

  const onTogglePin = async (region: HomeRegion) => {
    if (!activeWorkspaceId || layout == null) return;
    setPinBusyId(region.id);
    try {
      const result = await apiPost<{ ok: boolean; revision: number; region: HomeRegion | null }>(
        pinPath(activeWorkspaceId, region.id),
        { pinned: !region.pinned, expectedRevision: layout.revision },
      );
      setLayout((prev) => {
        if (!prev) return prev;
        const nextRegions = prev.regions.map((r) =>
          r.id === region.id && result.region
            ? { ...r, ...result.region }
            : r.id === region.id
              ? { ...r, pinned: !region.pinned }
              : r,
        );
        return { ...prev, revision: result.revision, regions: nextRegions };
      });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't update pin.", "error");
      await load();
    } finally {
      setPinBusyId(null);
    }
  };

  const onOpen = (href: string) => {
    if (href.startsWith("/")) navigate(href);
    else window.location.assign(href);
  };

  return (
    <div style={{ padding: 16 }} data-testid="workspace-home">
      <PageHeader
        title="Home"
        subtitle="Mission Control for this Workspace — compact projections over the same services the Agent and API use."
        helpHref="/docs#workspaces"
      />

      {!workspacesReady || loading ? (
        <div data-testid="home-loading" aria-busy="true" aria-label="Loading Workspace Home">
          <LoadingSpinner />
        </div>
      ) : !activeWorkspaceId ? (
        <EmptyState
          title="No Workspace selected"
          action="Open a Workspace tab to load Home"
        />
      ) : error ? (
        <Card>
          <p style={{ margin: 0, color: "#c4452a" }} data-testid="home-error">
            {error}
          </p>
          <button type="button" onClick={() => void load()} style={{ marginTop: 8 }}>
            Retry
          </button>
        </Card>
      ) : (
        <>
          <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--pencil)" }}>
            Pinning changes presentation only.{" "}
            <Link to="/dashboard" style={{ color: "var(--accent)" }}>
              Legacy Dashboard
            </Link>{" "}
            remains until cutover deletes it.
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 12,
            }}
            data-testid="home-regions"
          >
            {regions.map((region) => (
              <RegionCard
                key={region.id}
                region={region}
                section={sectionFor(projections?.sections ?? [], region.kind)}
                pinBusy={pinBusyId === region.id}
                onTogglePin={(r) => void onTogglePin(r)}
                onOpen={onOpen}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
