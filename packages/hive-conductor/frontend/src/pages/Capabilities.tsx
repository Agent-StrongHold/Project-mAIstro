import { useCallback, useEffect, useState } from "react";
import { ApiError, apiGet, apiPatch, apiPost } from "../lib/api";
import type {
  CapabilitiesDiscoverResponse,
  CapabilitiesListResponse,
  CapabilitySlot,
} from "../lib/capabilities";
import {
  CAPABILITIES_DISCOVER_PATH,
  CAPABILITIES_PATH,
  capabilitySlotPath,
} from "../lib/capabilities";
import { EmptyState, LoadingSpinner, PageHeader, useToast } from "../components/shared";

/**
 * Unified Capabilities surface (#2273 / conductor-407).
 *
 * Reads/writes only the public capabilities router (list / discover / slot
 * enable) — the same authority the CLI and any TUI use. Legacy Agents / MCP /
 * Skills / Topology page modules are deleted (#2273); old URLs redirect here.
 */
export default function CapabilitiesPage() {
  const toast = useToast();
  const [slots, setSlots] = useState<CapabilitySlot[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busySlot, setBusySlot] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const body = await apiGet<CapabilitiesListResponse>(CAPABILITIES_PATH);
      setSlots(body.slots ?? []);
    } catch (e) {
      setSlots(null);
      setLoadError(e instanceof ApiError ? e.message : "Couldn't load capabilities.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function discover() {
    setDiscovering(true);
    setLoadError(null);
    try {
      const body = await apiPost<CapabilitiesDiscoverResponse>(CAPABILITIES_DISCOVER_PATH, {});
      setSlots(body.slots ?? []);
      toast(
        body.registered ? `Discovered ${body.registered} provider(s)` : "Discovery complete",
        "ok",
      );
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Discovery failed.");
    } finally {
      setDiscovering(false);
    }
  }

  async function toggleEnabled(slot: CapabilitySlot) {
    setBusySlot(slot.slot);
    setLoadError(null);
    try {
      const updated = await apiPatch<CapabilitySlot>(capabilitySlotPath(slot.slot), {
        enabled: !slot.enabled,
      });
      setSlots((prev) =>
        (prev ?? []).map((s) => (s.slot === slot.slot ? { ...s, ...updated } : s)),
      );
      toast(`${slot.slot} ${updated.enabled ? "enabled" : "disabled"}`, "ok");
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : `Couldn't update ${slot.slot}.`);
    } finally {
      setBusySlot(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Capabilities"
        subtitle="Slots, providers, and host-owned trust — one surface over the public capability APIs"
        actions={
          <button
            type="button"
            className="btn-primary"
            onClick={() => void discover()}
            disabled={discovering}
          >
            {discovering ? "Discovering…" : "Re-discover providers"}
          </button>
        }
      />

      {loadError && (
        <p role="alert" style={{ color: "var(--danger, #c4452a)", marginBottom: 12 }}>
          {loadError}
        </p>
      )}

      {slots === null && !loadError ? (
        <LoadingSpinner />
      ) : slots !== null && slots.length === 0 ? (
        <EmptyState
          icon="◇"
          title="No capability slots registered"
          action="Re-discover providers"
          onAction={() => void discover()}
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {(slots ?? []).map((slot) => (
            <section
              key={slot.slot}
              className="card"
              style={{ padding: 16 }}
              aria-label={`Capability slot ${slot.slot}`}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 16, fontFamily: "var(--hand)" }}>{slot.slot}</h2>
                  <p style={{ margin: "4px 0 0", fontSize: 13, opacity: 0.75 }}>
                    {slot.enabled ? "Enabled" : "Disabled"}
                    {slot.active_provider ? ` · active: ${slot.active_provider}` : " · no active provider"}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn"
                  disabled={busySlot === slot.slot}
                  onClick={() => void toggleEnabled(slot)}
                  aria-pressed={slot.enabled}
                >
                  {busySlot === slot.slot ? "Saving…" : slot.enabled ? "Disable" : "Enable"}
                </button>
              </div>
              {slot.providers.length > 0 ? (
                <ul style={{ margin: "12px 0 0", paddingLeft: 18, fontSize: 13 }}>
                  {slot.providers.map((p) => (
                    <li key={p.name} style={{ marginBottom: 4 }}>
                      <strong>{p.name}</strong>
                      {" — "}
                      trust {p.trust_tier}, {p.provenance}
                      {p.healthy === null ? "" : p.healthy ? ", healthy" : ", unhealthy"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p style={{ margin: "12px 0 0", fontSize: 13, opacity: 0.7 }}>No providers installed.</p>
              )}
            </section>
          ))}
        </div>
      )}

      <p style={{ marginTop: 24, fontSize: 13, opacity: 0.7 }}>
        Former /agents, /mcp, /skills, and /topology URLs redirect here (#2273).
      </p>
    </div>
  );
}
