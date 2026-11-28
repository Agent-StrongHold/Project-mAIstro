/** Setup wizard wire calls. Under `lib/` for the typed-client ratchet: the
 * two raw fetches this module owns used to be banked debt rows in
 * `src/pages/Setup.tsx`, and the sanctioned in-lane fix for shifting banked
 * rows (55204762ae, #336) is eliminating the debt at this seam — the page
 * imports these instead of fetching inline. */

import { fallbackMessage } from "./api";

export type SetupCompleteRequest = {
  hardware_preset?: string;
  admin_username: string;
  admin_password: string;
  user_username: string;
  user_password: string;
  optional_modules: string[];
  conductor_name: string;
  default_model: string | null;
  /** Final gateway-preflight verdict (#287); absent means no claim. */
  model_availability?: "verified" | "unverified";
};

export type SetupCompleteResponse = {
  setup_complete?: boolean;
  mnemonic?: string[];
  config?: { user_did?: string | null };
};

export type Preset = { name: string; label: string; description: string; max_vcpu: number; max_memory_gb: number; db_backend: string; networking: string; gpu_available: boolean; reactor_enabled: boolean; max_agents: number };

/** One entry of the first-run question declaration served by
 * GET /v1/setup/questions — the same declaration the terminal wizard reads
 * directly (#443). The wizard seeds its state from these instead of
 * restating defaults, so identical answers produce an identical
 * /v1/setup/complete payload whichever path collected them. */
export type FirstRunQuestionMeta = { key: string; label: string; default: unknown; required: boolean; description: string };

export type IdentityStatus = "checking" | "operational" | "disabled" | "misconfigured" | "unavailable";

/** Gateway model-discovery lifecycle (#287): "pending" while the catalog
 * fetch is in flight, "ok" once the gateway answered with a non-empty,
 * well-formed catalog, "failed" for every distinguishable failure (auth,
 * not found, gateway error, network, malformed, empty). A failed check keeps
 * the curated list usable for offline setup, but it must never be presented
 * as successfully discovered gateway state. */
export type ModelCheck = "pending" | "ok" | "failed";

/** POST /v1/setup/complete — same error surface the page always showed: the
 * backend's `detail` sentence when it sent one, otherwise the shared
 * fallback for the status. */
export async function completeSetup(body: SetupCompleteRequest): Promise<SetupCompleteResponse> {
  const res = await fetch(`/v1/setup/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(
      (data as { detail?: string }).detail ?? fallbackMessage(res.status),
    );
  }
  return (await res.json()) as SetupCompleteResponse;
}

/** Session login for the setup wizard's auto-login step. Throws the same
 * "auto-login failed" sentence on refusal. */
export async function loginSession(username: string, password: string): Promise<void> {
  const r = await fetch(`/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error("auto-login failed");
}
