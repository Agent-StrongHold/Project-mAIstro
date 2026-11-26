/** Canonical Capabilities API wire shapes (#2273). Under `lib/` for typed-client. */

export type CapabilityProvider = {
  name: string;
  trust_tier: string;
  provenance: string;
  healthy: boolean | null;
};

export type CapabilitySlot = {
  slot: string;
  enabled: boolean;
  active_provider: string | null;
  providers: CapabilityProvider[];
};

export type CapabilitiesListResponse = {
  slots: CapabilitySlot[];
};

export type CapabilitiesDiscoverResponse = {
  registered: number;
  slots: CapabilitySlot[];
};

export const CAPABILITIES_PATH = "/v1/capabilities";
export const CAPABILITIES_DISCOVER_PATH = "/v1/capabilities/discover";

export function capabilitySlotPath(slot: string): string {
  return `/v1/capabilities/${encodeURIComponent(slot)}`;
}
